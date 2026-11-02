"""Offline walkthrough of the agent loop using scripted model turns (no Groq key needed).

The scripted "model" makes the same kind of tool calls a Groq model would, then
writes its answer only from the tool results it received, with citations checked.
"""

from __future__ import annotations

import json

from .agent import Agent
from .config import Settings
from .db import Database
from .llm import ScriptedChatModel, call, final, tool_turn

QUESTION = ("Summarise Project Falcon diligence: change-of-control exposure, customer concentration, "
            "pricing on the main product line and open evidence gaps.")


def _results(messages: list[dict]) -> dict[str, dict]:
    return {m["name"]: json.loads(m["content"]) for m in messages if m["role"] == "tool"}


def _write_answer(messages: list[dict]):
    r = _results(messages)
    items = {i["item_id"]: i for i in r["get_review_checklist"]["items"]}
    coc = items["CL-01"]["citations"][0]
    rev = items["CL-02"]["citations"][0]
    conc = r["customer_concentration"]
    top = conc["customers"][0]
    bs100 = r["weighted_price_summary"]["products"][0]
    gaps = r["list_evidence_gaps"]["gaps"]
    eu_revenue = r["run_sql"]["rows"][0][0]
    lines = [
        f"1. Change of control: Helios Motors may terminate on 90 days notice after a change of control "
        f"without consent [{coc}].",
        f"2. Concentration: {top['name']} is {top['share_pct']}% of revenue; top-{conc['top_n']} share is "
        f"{conc['top_n_share_pct']}% and HHI is {conc['hhi']} ({conc['classification']}). The audited "
        f"accounts report a similar pattern [{rev}].",
        f"3. Pricing: {bs100['product']} weighted average price {bs100['weighted_avg_price']} vs simple "
        f"average {bs100['simple_avg_price']} across {bs100['orders']} orders. EU revenue is {eu_revenue}.",
        "4. Open gaps: " + "; ".join(f"{g['item_id']} {g['requirement']}" for g in gaps) + ".",
    ]
    return final("\n".join(lines))


def build_script() -> ScriptedChatModel:
    return ScriptedChatModel([
        tool_turn(call("get_review_checklist"), call("list_evidence_gaps")),
        tool_turn(call("customer_concentration", top_n=3),
                  call("weighted_price_summary", product="BS-100"),
                  call("run_sql", query="SELECT SUM(o.quantity * o.unit_price) FROM orders o "
                                        "JOIN customers c USING (customer_id) WHERE c.region = 'EU'")),
        _write_answer,
    ])


def run_demo(db: Database, settings: Settings, tenant_id: str = "acme") -> dict:
    return Agent(db, build_script(), settings).run(QUESTION, tenant_id, principal="demo").to_dict()
