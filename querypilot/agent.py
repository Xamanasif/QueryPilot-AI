"""Bounded tool-calling agent with citation verification and human review records."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field

from pydantic import ValidationError

from .citations import check_citations
from .config import Settings
from .db import Database, now_iso
from .llm import ChatModel, LLMError
from .sql_guard import SQLGuardError
from .tools import TOOLS, ToolContext, tool_schemas

SYSTEM_PROMPT = """You are QueryPilot, an M&A due-diligence analyst assistant.
Rules:
- Use the tools to gather facts. Never invent figures, clauses or documents.
- Cite every statement drawn from documents with its chunk id in square brackets, e.g. [ACME-MSA-001@v1#c2].
  Only cite chunk ids returned by search_documents or get_review_checklist in this conversation.
- Quote numbers from analytics and SQL tools exactly as returned.
- If evidence is missing, say so plainly and name the gap instead of guessing.
- Keep answers concise and structured for a human reviewer."""


@dataclass
class AgentResult:
    run_id: str
    status: str  # completed | citation_failed | step_limit | llm_error
    answer: str | None
    citations: list[str]
    tool_calls: int
    steps: int
    trace: list[dict] = field(default_factory=list)
    review_status: str = "pending"

    @property
    def needs_attention(self) -> bool:
        return self.status != "completed"

    def to_dict(self) -> dict:
        return {**asdict(self), "needs_attention": self.needs_attention}


class Agent:
    def __init__(self, db: Database, llm: ChatModel, settings: Settings | None = None):
        self.db = db
        self.llm = llm
        self.settings = settings or Settings()

    def _execute(self, ctx: ToolContext, name: str, raw_args: str) -> tuple[dict, bool]:
        tool = TOOLS.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'. Available: {', '.join(TOOLS)}"}, False
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"Invalid arguments: not valid JSON ({exc.msg})"}, False
        if not isinstance(args, dict):
            return {"error": "Invalid arguments: expected a JSON object"}, False
        try:
            return tool.run(ctx, args), True
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors())
            return {"error": f"Invalid arguments: {problems}"}, False
        except SQLGuardError as exc:
            return {"error": str(exc)}, False
        except Exception as exc:  # a failing tool must not crash the run
            return {"error": f"Tool '{name}' failed: {type(exc).__name__}: {exc}"}, False

    def _truncate(self, payload: dict) -> str:
        text = json.dumps(payload, default=str)
        limit = self.settings.max_tool_output_chars
        if len(text) > limit:
            text = text[:limit] + '... [truncated]'
        return text

    def run(self, question: str, tenant_id: str, principal: str = "system") -> AgentResult:
        s = self.settings
        ctx = ToolContext(self.db, tenant_id, max_sql_rows=s.max_sql_rows)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": question}]
        schemas = tool_schemas()
        trace: list[dict] = []
        tool_calls = repairs = steps = 0
        status, answer, cited = "step_limit", None, []

        while steps < s.max_steps:
            steps += 1
            try:
                turn = self.llm.complete(messages, schemas)
            except LLMError as exc:
                trace.append({"step": steps, "event": "llm_error", "error": str(exc)})
                status = "llm_error"
                break

            if turn.tool_calls:
                messages.append(turn.to_message())
                for c in turn.tool_calls:
                    if tool_calls >= s.max_tool_calls:
                        payload, ok = {"error": "Tool-call budget exhausted; answer with the evidence you have."}, False
                    else:
                        tool_calls += 1
                        payload, ok = self._execute(ctx, c.name, c.arguments)
                    trace.append({"step": steps, "event": "tool", "tool": c.name, "arguments": c.arguments,
                                  "ok": ok, **({} if ok else {"error": payload["error"]})})
                    messages.append({"role": "tool", "tool_call_id": c.id, "name": c.name,
                                     "content": self._truncate(payload)})
                continue

            answer = turn.content or ""
            check = check_citations(answer, ctx.evidence)
            cited = check.cited
            trace.append({"step": steps, "event": "answer", "citations_ok": check.ok,
                          **({"problem": check.problem} if check.problem else {})})
            if check.ok:
                status = "completed"
                break
            if repairs < s.max_citation_repairs:
                repairs += 1
                messages.append({"role": "assistant", "content": answer})
                messages.append({"role": "user", "content": (
                    f"Citation check failed: {check.problem} Revise the answer citing only chunk ids "
                    f"you retrieved: {', '.join(ctx.evidence) or 'none'}. Search again if needed.")})
                continue
            status = "citation_failed"
            break

        result = AgentResult(str(uuid.uuid4()), status, answer, cited, tool_calls, steps, trace)
        self._persist(result, tenant_id, principal, question)
        return result

    def _persist(self, r: AgentResult, tenant_id: str, principal: str, question: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO agent_runs (run_id, tenant_id, principal, question, status, answer,
                                           citations, trace, review_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (r.run_id, tenant_id, principal, question, r.status, r.answer,
                 json.dumps(r.citations), json.dumps(r.trace), now_iso()),
            )


def get_run(db: Database, tenant_id: str, run_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE tenant_id = ? AND run_id = ?",
                           (tenant_id, run_id)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["citations"] = json.loads(data["citations"])
    data["trace"] = json.loads(data["trace"])
    data.pop("tenant_id")
    return data


def review_run(db: Database, tenant_id: str, run_id: str, reviewer: str, decision: str, note: str | None) -> dict | None:
    with db.connect() as conn:
        cur = conn.execute(
            """UPDATE agent_runs SET review_status = ?, reviewer = ?, review_note = ?
               WHERE tenant_id = ? AND run_id = ?""",
            (decision, reviewer, note, tenant_id, run_id),
        )
        if cur.rowcount == 0:
            return None
    return get_run(db, tenant_id, run_id)
