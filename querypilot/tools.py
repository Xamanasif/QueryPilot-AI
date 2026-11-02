"""Typed tools exposed to the model in Groq (OpenAI-compatible) function-calling format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import analytics
from .db import Database
from .diligence import DiligenceReviewer
from .rag import Retriever
from .sql_guard import SQLGuard, describe_schema


@dataclass
class ToolContext:
    """Per-run state: who is asking, and which evidence chunks have been retrieved."""
    db: Database
    tenant_id: str
    max_sql_rows: int = 200
    evidence: dict[str, dict] = field(default_factory=dict)

    def record(self, chunk_id: str, title: str, text: str) -> None:
        self.evidence[chunk_id] = {"chunk_id": chunk_id, "title": title, "text": text}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(_Args):
    query: str = Field(min_length=2, max_length=500, description="Natural-language search query.")
    k: int = Field(default=4, ge=1, le=10, description="Number of passages to return.")


class ChecklistArgs(_Args):
    workstream: Literal["legal", "financial", "compliance", "hr"] | None = Field(
        default=None, description="Optional workstream filter.")


class NoArgs(_Args):
    pass


class SQLArgs(_Args):
    query: str = Field(min_length=6, max_length=4000, description="A single read-only SQLite SELECT query.")


class RFMArgs(_Args):
    limit: int | None = Field(default=None, ge=1, le=100, description="Return only the top customers by monetary value.")


class ConcentrationArgs(_Args):
    top_n: int = Field(default=3, ge=1, le=20, description="Number of top customers for the share metric.")


class WeightedPriceArgs(_Args):
    product: str | None = Field(default=None, max_length=50, description="Optional product code filter.")


def _search(ctx: ToolContext, args: SearchArgs) -> dict:
    hits = Retriever(ctx.db).search(ctx.tenant_id, args.query, k=args.k)
    for h in hits:
        ctx.record(h.chunk_id, h.title, h.text)
    return {"results": [{"chunk_id": h.chunk_id, "title": h.title, "text": h.text, "score": h.score}
                        for h in hits]}


def _checklist(ctx: ToolContext, args: ChecklistArgs) -> dict:
    result = DiligenceReviewer(ctx.db).checklist(ctx.tenant_id, args.workstream)
    for item in result["items"]:
        for ev in item["evidence"]:
            ctx.record(ev["chunk_id"], ev["title"], ev["text"])
    return result


def _gaps(ctx: ToolContext, args: NoArgs) -> dict:
    return {"gaps": DiligenceReviewer(ctx.db).gaps(ctx.tenant_id)}


def _schema(ctx: ToolContext, args: NoArgs) -> dict:
    return describe_schema()


def _sql(ctx: ToolContext, args: SQLArgs) -> dict:
    return SQLGuard(ctx.db, max_rows=ctx.max_sql_rows).execute(ctx.tenant_id, args.query)


def _rfm(ctx: ToolContext, args: RFMArgs) -> dict:
    result = analytics.rfm(ctx.db, ctx.tenant_id)
    if args.limit:
        result["customers"] = result["customers"][: args.limit]
    return result


def _concentration(ctx: ToolContext, args: ConcentrationArgs) -> dict:
    return analytics.concentration(ctx.db, ctx.tenant_id, args.top_n)


def _weighted(ctx: ToolContext, args: WeightedPriceArgs) -> dict:
    return analytics.weighted_prices(ctx.db, ctx.tenant_id, args.product)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[_Args]
    fn: Callable[[ToolContext, Any], dict]

    def schema(self) -> dict:
        params = self.args_model.model_json_schema()
        params.pop("title", None)
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": params}}

    def run(self, ctx: ToolContext, raw_args: dict) -> dict:
        return self.fn(ctx, self.args_model.model_validate(raw_args))


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("search_documents",
         "Search approved diligence documents. Returns passages with chunk_id values to cite as [chunk_id].",
         SearchArgs, _search),
    Tool("get_review_checklist",
         "Diligence review checklist: each requirement with status (evidenced/gap) and supporting citations.",
         ChecklistArgs, _checklist),
    Tool("list_evidence_gaps", "List checklist requirements that lack approved evidence, with reasons.",
         NoArgs, _gaps),
    Tool("describe_sql_schema", "Describe the tables and columns available to run_sql.", NoArgs, _schema),
    Tool("run_sql", "Run one read-only SQLite SELECT over customers, orders and documents for this tenant.",
         SQLArgs, _sql),
    Tool("rfm_analysis", "Recency/frequency/monetary customer scores (1-5) and segments.", RFMArgs, _rfm),
    Tool("customer_concentration", "Revenue by customer, top-N share and HHI concentration index.",
         ConcentrationArgs, _concentration),
    Tool("weighted_price_summary", "Quantity-weighted average unit price and revenue per product.",
         WeightedPriceArgs, _weighted),
]}


def tool_schemas() -> list[dict]:
    return [t.schema() for t in TOOLS.values()]
