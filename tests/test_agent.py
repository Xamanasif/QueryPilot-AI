import json
from dataclasses import replace

from conftest import ACME_ANALYST, ACME_REVIEWER, GLOBEX_ANALYST
from fastapi.testclient import TestClient

from querypilot.agent import Agent, get_run
from querypilot.api import create_app
from querypilot.llm import LLMError, ScriptedChatModel, call, final, tool_turn


def tool_results(messages):
    return {m["name"]: json.loads(m["content"]) for m in messages if m["role"] == "tool"}


def test_multi_tool_execution_with_verified_citations(db, settings):
    def answer(messages):
        results = tool_results(messages)
        conc = results["customer_concentration"]
        rev = results["run_sql"]["rows"][0][0]
        chunk = results["search_documents"]["results"][0]["chunk_id"]
        return final(f"Helios Motors can terminate on a change of control with 90 days notice [{chunk}]. "
                     f"Top-3 customers hold {conc['top_n_share_pct']}% of revenue (HHI {conc['hhi']}); "
                     f"Helios revenue is {rev}.")

    llm = ScriptedChatModel([
        tool_turn(call("search_documents", query="change of control termination", k=3),
                  call("customer_concentration", top_n=3)),
        tool_turn(call("run_sql", query="SELECT SUM(quantity * unit_price) FROM orders WHERE customer_id = 'C001'")),
        answer,
    ])
    result = Agent(db, llm, settings).run("Assess Helios change-of-control risk", "acme", "ana.analyst")

    assert result.status == "completed" and not result.needs_attention
    assert result.tool_calls == 3 and result.steps == 3
    assert result.citations == ["ACME-MSA-001@v1#c2"]
    assert "83.7%" in result.answer and "HHI 3310.09" in result.answer and "113875.0" in result.answer
    assert [t["tool"] for t in result.trace if t["event"] == "tool"] == [
        "search_documents", "customer_concentration", "run_sql"]
    # Tools were offered to the model in Groq function-calling format.
    assert llm.received[0][0]["role"] == "system"
    assert get_run(db, "acme", result.run_id)["review_status"] == "pending"


def test_hallucinated_citation_triggers_repair_then_fails_closed(db, settings):
    fake = "[ACME-MSA-001@v2#c2]"  # draft version: never retrieved, so never citable
    llm = ScriptedChatModel([
        tool_turn(call("search_documents", query="change of control")),
        final(f"Customer may terminate immediately {fake}."),
        final(f"Customer may terminate immediately {fake}."),
    ])
    result = Agent(db, llm, settings).run("What are the change of control terms?", "acme")

    assert result.status == "citation_failed" and result.needs_attention
    repair_prompt = llm.received[2][-1]["content"]
    assert "Citation check failed" in repair_prompt and "ACME-MSA-001@v2#c2" in repair_prompt

    repaired = ScriptedChatModel([
        tool_turn(call("search_documents", query="change of control")),
        final("Termination needs 90 days notice."),  # uncited answer is also rejected
        final("Termination needs 90 days notice [ACME-MSA-001@v1#c2]."),
    ])
    ok = Agent(db, repaired, settings).run("What are the change of control terms?", "acme")
    assert ok.status == "completed" and ok.citations == ["ACME-MSA-001@v1#c2"]


def test_unknown_tool_bad_arguments_and_sql_errors_are_returned_to_model(db, settings):
    llm = ScriptedChatModel([
        tool_turn(call("delete_everything"),
                  call("search_documents", raw="{not json"),
                  call("customer_concentration", top_n=0),
                  call("run_sql", query="DELETE FROM orders"),
                  call("rfm_analysis", limit=2, unexpected=True)),
        lambda messages: final("Recovered after tool errors; no evidence cited."),
    ])
    result = Agent(db, llm, settings).run("Try some tools", "acme")

    assert result.status == "completed"
    errors = [t["error"] for t in result.trace if t["event"] == "tool"]
    assert len(errors) == 5
    assert errors[0].startswith("Unknown tool 'delete_everything'")
    assert "not valid JSON" in errors[1]
    assert "top_n" in errors[2]
    assert "Only SELECT or WITH" in errors[3]
    assert "unexpected" in errors[4]
    tool_messages = [m for m in llm.received[1] if m["role"] == "tool"]
    assert len(tool_messages) == 5 and all("error" in json.loads(m["content"]) for m in tool_messages)


def test_step_and_tool_call_budgets_bound_the_run(db, settings):
    looping = ScriptedChatModel([tool_turn(call("rfm_analysis"))] * 10)
    result = Agent(db, looping, replace(settings, max_steps=3)).run("Loop forever", "acme")
    assert result.status == "step_limit" and result.steps == 3 and len(looping.received) == 3

    burst = ScriptedChatModel([
        tool_turn(*[call("weighted_price_summary", call_id=f"c{i}") for i in range(4)]),
        final("Done."),
    ])
    capped = Agent(db, burst, replace(settings, max_tool_calls=2)).run("Burst", "acme")
    assert capped.status == "completed" and capped.tool_calls == 2
    assert [t["ok"] for t in capped.trace if t["event"] == "tool"] == [True, True, False, False]


def test_model_failure_is_recorded_not_raised(db, settings):
    llm = ScriptedChatModel([tool_turn(call("list_evidence_gaps")), LLMError("Groq request failed: 503")])
    result = Agent(db, llm, settings).run("Which gaps remain?", "acme")
    assert result.status == "llm_error" and result.answer is None
    assert result.trace[-1] == {"step": 2, "event": "llm_error", "error": "Groq request failed: 503"}
    assert get_run(db, "acme", result.run_id)["status"] == "llm_error"


def test_agent_endpoint_and_human_review_flow(app, client):
    app.state.llm_factory = lambda: ScriptedChatModel([
        tool_turn(call("get_review_checklist", workstream="compliance")),
        final("GDPR compliance is a gap: the memo is still an unapproved draft."),
    ])
    run = client.post("/v1/agent/run", json={"question": "Is GDPR compliance evidenced?"},
                      headers=ACME_ANALYST).json()
    assert run["status"] == "completed" and run["review_status"] == "pending"

    path = f"/v1/runs/{run['run_id']}"
    assert client.get(path, headers=GLOBEX_ANALYST).status_code == 404
    assert client.post(f"{path}/review", json={"decision": "approved"}, headers=ACME_ANALYST).status_code == 403
    reviewed = client.post(f"{path}/review", json={"decision": "approved", "note": "Agrees with gap log"},
                           headers=ACME_REVIEWER).json()
    assert reviewed["review_status"] == "approved" and reviewed["reviewer"] == "rui.reviewer"
    assert client.get(path, headers=ACME_ANALYST).json()["review_note"] == "Agrees with gap log"

    # Without GROQ_API_KEY the real model is unavailable and the API says so.
    unconfigured = TestClient(create_app(app.state.settings))
    resp = unconfigured.post("/v1/agent/run", json={"question": "hi there"}, headers=ACME_ANALYST)
    assert resp.status_code == 503
