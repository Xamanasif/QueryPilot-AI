"""FastAPI application: authenticated, tenant-scoped diligence and analytics endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import analytics, __version__
from .agent import Agent, get_run, list_runs, review_run
from .config import Settings
from .db import Database, hash_key
from .diligence import DiligenceReviewer
from .llm import ChatModel, GroqChatModel
from .rag import Retriever
from .sql_guard import SQLGuard, SQLGuardError, describe_schema


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    principal: str
    role: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=4, ge=1, le=10)


class DraftRequest(BaseModel):
    content: str = Field(min_length=10, max_length=100_000,
                         description="Document text; blank lines separate citable passages.")
    title: str | None = Field(default=None, max_length=200)
    category: Literal["contract", "financial", "legal", "compliance", "hr"] | None = None


class SQLRequest(BaseModel):
    query: str = Field(min_length=6, max_length=4000)


class AgentRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


def create_app(settings: Settings | None = None,
               llm_factory: Callable[[], ChatModel] | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    db.seed_demo()

    def default_llm() -> ChatModel:
        if not settings.groq_api_key:
            raise HTTPException(503, "GROQ_API_KEY is not configured")
        return GroqChatModel(settings.groq_api_key, settings.model)

    app = FastAPI(title="QueryPilot AI", version=__version__,
                  description="Governed RAG and SQL agent for simulated M&A diligence.")
    app.state.db = db
    app.state.settings = settings
    app.state.llm_factory = llm_factory or default_llm

    def get_db(request: Request) -> Database:
        return request.app.state.db

    def authenticate(request: Request, x_api_key: str | None = Header(default=None)) -> Principal:
        if not x_api_key:
            raise HTTPException(401, "Missing X-API-Key header", headers={"WWW-Authenticate": "ApiKey"})
        with request.app.state.db.connect() as conn:
            row = conn.execute("SELECT tenant_id, principal, role FROM api_keys WHERE key_hash = ?",
                               (hash_key(x_api_key),)).fetchone()
        if row is None:
            raise HTTPException(401, "Invalid API key", headers={"WWW-Authenticate": "ApiKey"})
        return Principal(row["tenant_id"], row["principal"], row["role"])

    def require_reviewer(p: Principal = Depends(authenticate)) -> Principal:
        if p.role != "reviewer":
            raise HTTPException(403, "Reviewer role required")
        return p

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/me")
    def me(p: Principal = Depends(authenticate)) -> dict:
        return {"tenant_id": p.tenant_id, "principal": p.principal, "role": p.role}

    @app.get("/v1/documents")
    def documents(p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        return {"documents": db.list_documents(p.tenant_id)}

    @app.post("/v1/documents/{doc_id}/versions", status_code=201)
    def submit_draft(doc_id: str, body: DraftRequest, p: Principal = Depends(authenticate),
                     db: Database = Depends(get_db)) -> dict:
        try:
            return db.submit_draft(p.tenant_id, doc_id, body.content, body.title, body.category)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/v1/documents/{doc_id}/versions/{version}/approve")
    def approve(doc_id: str, version: int, p: Principal = Depends(require_reviewer),
                db: Database = Depends(get_db)) -> dict:
        try:
            return db.approve_version(p.tenant_id, doc_id, version, p.principal)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/v1/search")
    def search(body: SearchRequest, p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        hits = Retriever(db).search(p.tenant_id, body.query, k=body.k)
        return {"results": [h.to_dict() for h in hits]}

    @app.get("/v1/diligence/checklist")
    def checklist(workstream: str | None = None, p: Principal = Depends(authenticate),
                  db: Database = Depends(get_db)) -> dict:
        return DiligenceReviewer(db).checklist(p.tenant_id, workstream)

    @app.get("/v1/diligence/gaps")
    def gaps(p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        return {"gaps": DiligenceReviewer(db).gaps(p.tenant_id)}

    @app.get("/v1/sql/schema")
    def sql_schema(p: Principal = Depends(authenticate)) -> dict:
        return describe_schema()

    @app.post("/v1/sql")
    def sql(body: SQLRequest, p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        try:
            return SQLGuard(db, max_rows=settings.max_sql_rows).execute(p.tenant_id, body.query)
        except SQLGuardError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/v1/analytics/rfm")
    def rfm(p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        return analytics.rfm(db, p.tenant_id)

    @app.get("/v1/analytics/concentration")
    def concentration(top_n: int = Query(default=3, ge=1, le=20), p: Principal = Depends(authenticate),
                      db: Database = Depends(get_db)) -> dict:
        return analytics.concentration(db, p.tenant_id, top_n)

    @app.get("/v1/analytics/weighted-prices")
    def weighted(product: str | None = None, p: Principal = Depends(authenticate),
                 db: Database = Depends(get_db)) -> dict:
        return analytics.weighted_prices(db, p.tenant_id, product)

    @app.post("/v1/agent/run")
    def agent_run(body: AgentRequest, request: Request, p: Principal = Depends(authenticate),
                  db: Database = Depends(get_db)) -> dict:
        llm = request.app.state.llm_factory()
        return Agent(db, llm, settings).run(body.question, p.tenant_id, p.principal).to_dict()

    @app.get("/v1/runs")
    def runs(review_status: Literal["pending", "approved", "rejected"] | None = None,
             limit: int = Query(default=50, ge=1, le=200), p: Principal = Depends(authenticate),
             db: Database = Depends(get_db)) -> dict:
        return {"runs": list_runs(db, p.tenant_id, review_status, limit)}

    @app.get("/v1/runs/{run_id}")
    def run_detail(run_id: str, p: Principal = Depends(authenticate), db: Database = Depends(get_db)) -> dict:
        run = get_run(db, p.tenant_id, run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    @app.post("/v1/runs/{run_id}/review")
    def run_review(run_id: str, body: ReviewRequest, p: Principal = Depends(require_reviewer),
                   db: Database = Depends(get_db)) -> dict:
        run = review_run(db, p.tenant_id, run_id, p.principal, body.decision, body.note)
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn querypilot.api:app_factory --factory`."""
    return create_app()
