# QueryPilot AI: Governed RAG & SQL Agent

**Python · Groq · FastAPI · SQLite**

QueryPilot AI is a governed retrieval and analytics agent for **simulated M&A due diligence**. It links
approved document versions to source-cited review checklists, finds evidence gaps, and answers
tenant-filtered analytical questions through an authenticated FastAPI service. A Groq-hosted model
orchestrates typed tools inside a bounded loop. Every answer goes through a citation check and is
stored for human review.

> All companies, contracts and figures in the dataset are fictional.

## What it does

| Capability | Where |
|---|---|
| Versioned documents (`draft → approved → superseded`); only approved versions are searchable or citable | [querypilot/db.py](querypilot/db.py), [querypilot/rag.py](querypilot/rag.py) |
| BM25 retrieval scoped to the caller's tenant | [querypilot/rag.py](querypilot/rag.py) |
| Diligence checklists that link each requirement to cited evidence, or record a gap (missing, or present only in an unapproved draft) | [querypilot/diligence.py](querypilot/diligence.py) |
| Restricted SQL: read-only connection, a single SELECT/WITH statement, tenant-filtered TEMP views, an SQLite authorizer, a function allow-list, a row cap and a VM step limit | [querypilot/sql_guard.py](querypilot/sql_guard.py) |
| RFM customer scoring, revenue concentration (top-N share, HHI), weighted-price summaries; exact `Decimal` maths, fixed as-of date | [querypilot/analytics.py](querypilot/analytics.py) |
| Typed tools (Pydantic arguments → Groq/OpenAI function schemas) | [querypilot/tools.py](querypilot/tools.py) |
| Bounded agent: step budget, tool-call budget, output truncation, error handling, citation verification with one repair round | [querypilot/agent.py](querypilot/agent.py), [querypilot/citations.py](querypilot/citations.py) |
| API-key auth (SHA-256 hashed keys), analyst/reviewer roles, tenant isolation, human review of agent runs | [querypilot/api.py](querypilot/api.py) |

## Architecture

```
            X-API-Key ──► FastAPI ──► Principal(tenant, role)
                              │
      ┌───────────────────────┼────────────────────────────┐
      ▼                       ▼                            ▼
 /v1/search, /diligence   /v1/sql, /analytics        /v1/agent/run
      │                       │                            │
  Retriever (BM25,        SQLGuard (TEMP views +       Agent loop ──► Groq chat completions
  approved only,          authorizer, read-only)       │  ▲            (tool calling)
  tenant filtered)            │                        ▼  │
      │                   analytics (Decimal)       Typed tools ──► ToolContext(evidence)
      └──────────┬────────────┘                        │
                 ▼                                     ▼
              SQLite  ◄──────── agent_runs (trace, citations, review_status)
```

### Governance rules

1. **Only approved evidence counts.** Chunks from `draft` or `superseded` versions are never returned to
   the model. When a reviewer approves a new version, the previously approved one becomes `superseded`.
2. **Citations must be earned.** Answers cite chunks as `[ACME-MSA-001@v1#c2]`. A citation is valid only
   if that chunk was retrieved by a tool *during the same run*. If evidence was retrieved but the answer
   cites none of it, the check fails too. A failed check gets one repair prompt. If that still fails,
   the run ends with status `citation_failed` instead of returning an answer that passes as verified.
3. **SQL cannot leave its tenant.** Each query runs on a fresh `mode=ro` connection. TEMP views named
   `customers`, `orders` and `documents` shadow the real tables and filter by tenant (the `tenant_id`
   column is not exposed). The authorizer allows reads only from these views or on their behalf, so
   `main.customers`, `sqlite_master`, `api_keys`, PRAGMA, ATTACH, DML and unlisted functions are all denied.
4. **Bounded execution.** The agent stops at `max_steps` model turns and `max_tool_calls` tool
   executions. Tool output is truncated. Unknown tools, malformed JSON, schema violations, SQL
   rejections and tool exceptions go back to the model as tool errors and never crash the run.
   Groq failures are recorded as `llm_error`.
5. **Humans sign off.** Every run is stored with its full trace and `review_status = pending`. Only users
   with the `reviewer` role can approve or reject runs, or approve document versions.

## Quick start

```bash
pip install -r requirements.txt
python -m querypilot init-db                # creates and seeds data/querypilot.db
python -m querypilot checklist --tenant acme
python -m querypilot demo                   # full agent loop offline, scripted model turns

export GROQ_API_KEY=...                     # PowerShell: $env:GROQ_API_KEY="..."
uvicorn querypilot.api:app_factory --factory --reload
```

Interactive docs: http://127.0.0.1:8000/docs

Demo API keys:

| Key | Tenant | Role |
|---|---|---|
| `qp_acme_analyst_demo` | acme (Project Falcon) | analyst |
| `qp_acme_reviewer_demo` | acme | reviewer |
| `qp_globex_analyst_demo` | globex (Project Orion) | analyst |

```bash
H='X-API-Key: qp_acme_analyst_demo'
curl -H "$H" localhost:8000/v1/diligence/checklist
curl -H "$H" localhost:8000/v1/diligence/gaps
curl -H "$H" "localhost:8000/v1/analytics/concentration?top_n=3"
curl -H "$H" -H 'Content-Type: application/json' localhost:8000/v1/sql \
     -d '{"query":"SELECT product, SUM(quantity*unit_price) AS revenue FROM orders GROUP BY product"}'
curl -H "$H" -H 'Content-Type: application/json' localhost:8000/v1/agent/run \
     -d '{"question":"Assess change-of-control risk on the Helios contract and quantify customer concentration."}'
```

## API

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/v1/me` | any | Caller identity |
| GET | `/v1/documents` | any | Documents and version statuses |
| POST | `/v1/documents/{doc_id}/versions` | any | Submit a new draft version (or a new document) |
| POST | `/v1/documents/{doc_id}/versions/{v}/approve` | reviewer | Approve a draft; supersede the prior version |
| POST | `/v1/search` | any | BM25 search over approved chunks |
| GET | `/v1/diligence/checklist` | any | Checklist with statuses and citations |
| GET | `/v1/diligence/gaps` | any | Unevidenced requirements with reasons |
| GET | `/v1/sql/schema` · POST `/v1/sql` | any | Restricted SQL |
| GET | `/v1/analytics/rfm` · `/concentration` · `/weighted-prices` | any | Commercial metrics |
| POST | `/v1/agent/run` | any | Run the Groq agent |
| GET | `/v1/runs?review_status=pending` | any | Human review queue |
| GET | `/v1/runs/{id}` · POST `/v1/runs/{id}/review` | any · reviewer | Inspect / sign off a run |

### Governed document lifecycle

```
analyst: POST /versions ──► draft (not searchable, not citable; gaps list it as "only in draft")
reviewer: POST /approve ──► approved (searchable, citable) ; previous approved ──► superseded
```

For example, submitting and approving a facility agreement closes Acme's `CL-06` debt-covenant gap.

## Agent tools

`search_documents`, `get_review_checklist`, `list_evidence_gaps`, `describe_sql_schema`, `run_sql`,
`rfm_analysis`, `customer_concentration`, `weighted_price_summary`. Each tool has a Pydantic argument
model with `extra="forbid"`, and its JSON schema is sent to Groq as an OpenAI-compatible function definition.

## Reference outputs (tenant `acme`, as of 2025-12-31)

| Metric | Value |
|---|---|
| Total revenue | 221,960.00 |
| Top-3 customer share | 83.70 % |
| HHI | 3,310.09 (highly concentrated) |
| Largest customer | Helios Motors, 113,875.00 (51.30 %), RFM `355` |
| BS-100 weighted / simple average price | 41.83 / 42.33 |
| CU-300 weighted / simple average price | 323.33 / 327.50 |
| Checklist | 7 items: 5 evidenced, 2 gaps (GDPR only in draft; no debt-facility evidence) |

## Tests

```bash
pytest -q        # 22 passed
```

The 22 local tests run without network access. A `ScriptedChatModel` replays fixed model turns,
including tool calls, malformed arguments, hallucinated citations and Groq failures. This makes the
agent's orchestration deterministic. The tests cover:

- **Security and API:** missing or invalid keys, role checks, the draft → approval lifecycle closing a
  gap, cross-tenant isolation across documents, drafts, search, SQL and runs.
- **RAG and diligence:** approved-only retrieval, version supersession, tenant-filtered search,
  checklist citations, gap reasons.
- **SQL guard:** DML, PRAGMA, ATTACH and stacked statements rejected; `main.*`, `sqlite_master`,
  `api_keys` and `tenant_id` bypasses blocked; automatic tenant filter; row cap.
- **Analytics:** exact RFM codes, concentration shares, HHI and weighted prices.
- **Agent:** multi-tool execution with verified citations (including the five-tool offline demo),
  citation repair and fail-closed behaviour, tool error recovery, step and tool-call budgets, and the
  end-to-end API, review queue and human review flow.
- **Groq compatibility:** the real `GroqChatModel` adapter runs against scripted HTTP responses in Groq's
  chat-completions wire format. The test checks the tool schemas sent, the tool-call round trip, and
  how a Groq API error is handled.

## Configuration

| Variable | Default |
|---|---|
| `GROQ_API_KEY` | none (the agent endpoint returns 503 without it) |
| `QUERYPILOT_MODEL` | `llama-3.3-70b-versatile` |
| `QUERYPILOT_DB` | `data/querypilot.db` |
| `QUERYPILOT_MAX_STEPS` | `8` |
| `QUERYPILOT_MAX_TOOL_CALLS` | `12` |
| `QUERYPILOT_MAX_SQL_ROWS` | `200` |

## License

MIT
