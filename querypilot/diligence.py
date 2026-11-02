"""Diligence review checklists: link each requirement to cited evidence or record a gap."""

from __future__ import annotations

from .db import Database
from .rag import Hit, Retriever, tokenize

MIN_SCORE = 1.0
MIN_MATCHED_TERMS = 2


def _is_evidence(hit: Hit, query: str) -> bool:
    needed = min(MIN_MATCHED_TERMS, len(set(tokenize(query))))
    return hit.score >= MIN_SCORE and hit.matched_terms >= needed


class DiligenceReviewer:
    def __init__(self, db: Database, retriever: Retriever | None = None):
        self.db = db
        self.retriever = retriever or Retriever(db)

    def _items(self, tenant_id: str, workstream: str | None) -> list[dict]:
        sql = "SELECT item_id, workstream, requirement, query FROM checklist_items WHERE tenant_id = ?"
        params: list = [tenant_id]
        if workstream:
            sql += " AND workstream = ?"
            params.append(workstream)
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(sql + " ORDER BY item_id", params)]

    def review_item(self, tenant_id: str, item: dict) -> dict:
        approved = [h for h in self.retriever.search(tenant_id, item["query"], k=3)
                    if _is_evidence(h, item["query"])]
        result = {
            "item_id": item["item_id"],
            "workstream": item["workstream"],
            "requirement": item["requirement"],
        }
        if approved:
            return {**result, "status": "evidenced",
                    "citations": [h.chunk_id for h in approved],
                    "evidence": [{"chunk_id": h.chunk_id, "title": h.title, "text": h.text} for h in approved]}

        drafts = [h for h in self.retriever.search(tenant_id, item["query"], k=3, statuses=("draft",))
                  if _is_evidence(h, item["query"])]
        if drafts:
            reason = ("Evidence exists only in unapproved draft version(s): "
                      + ", ".join(sorted({f"{h.doc_id}@v{h.version}" for h in drafts}))
                      + ". Approval is required before it can be cited.")
        else:
            reason = "No supporting evidence found in approved documents; request from the target."
        return {**result, "status": "gap", "citations": [], "evidence": [], "gap_reason": reason}

    def checklist(self, tenant_id: str, workstream: str | None = None) -> dict:
        items = [self.review_item(tenant_id, item) for item in self._items(tenant_id, workstream)]
        evidenced = sum(1 for i in items if i["status"] == "evidenced")
        return {
            "items": items,
            "summary": {"total": len(items), "evidenced": evidenced, "gaps": len(items) - evidenced},
        }

    def gaps(self, tenant_id: str) -> list[dict]:
        return [
            {k: item[k] for k in ("item_id", "workstream", "requirement", "gap_reason")}
            for item in self.checklist(tenant_id)["items"] if item["status"] == "gap"
        ]
