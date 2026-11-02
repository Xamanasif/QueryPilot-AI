from querypilot.diligence import DiligenceReviewer
from querypilot.rag import Retriever


def test_search_returns_only_approved_versions(db):
    hits = Retriever(db).search("acme", "change of control terminate", k=10)
    assert hits[0].chunk_id == "ACME-MSA-001@v1#c2"
    assert all(h.status == "approved" for h in hits)
    # Draft v2 of the MSA and the superseded IP register are never retrievable.
    ids = {h.chunk_id for h in Retriever(db).search("acme", "terminate immediately without notice patents", k=20)}
    assert not any(i.startswith("ACME-MSA-001@v2") or i.startswith("ACME-IP-003@v1") for i in ids)


def test_approving_new_version_supersedes_previous(db):
    db.approve_version("acme", "ACME-MSA-001", 2, "rui.reviewer")
    hits = Retriever(db).search("acme", "change of control terminate", k=3)
    assert hits[0].chunk_id == "ACME-MSA-001@v2#c2"
    assert "immediately and without notice" in hits[0].text
    statuses = {(d["doc_id"], d["version"]): d["status"] for d in db.list_documents("acme")}
    assert statuses[("ACME-MSA-001", 1)] == "superseded"
    assert statuses[("ACME-MSA-001", 2)] == "approved"


def test_retrieval_is_tenant_filtered(db):
    acme = Retriever(db).search("acme", "change of control", k=10)
    globex = Retriever(db).search("globex", "change of control", k=10)
    assert acme and all(h.doc_id.startswith("ACME-") for h in acme)
    assert globex and all(h.doc_id.startswith("GLX-") for h in globex)


def test_checklist_links_requirements_to_approved_citations(db):
    result = DiligenceReviewer(db).checklist("acme")
    items = {i["item_id"]: i for i in result["items"]}
    assert result["summary"] == {"total": 7, "evidenced": 5, "gaps": 2}
    assert items["CL-01"]["citations"] == ["ACME-MSA-001@v1#c2"]
    assert items["CL-02"]["citations"] == ["ACME-FIN-002@v1#c1"]
    assert items["CL-03"]["citations"] == ["ACME-IP-003@v2#c2"]
    assert items["CL-04"]["citations"] == ["ACME-LIT-004@v1#c1"]
    for item in result["items"]:
        for ev in item["evidence"]:
            assert ev["chunk_id"] in item["citations"]


def test_evidence_gaps_distinguish_drafts_from_missing_evidence(db, client):
    gaps = {g["item_id"]: g["gap_reason"] for g in DiligenceReviewer(db).gaps("acme")}
    assert set(gaps) == {"CL-05", "CL-06"}
    assert "unapproved draft" in gaps["CL-05"] and "ACME-PRIV-005@v1" in gaps["CL-05"]
    assert "No supporting evidence" in gaps["CL-06"]
    # Globex has a debt facility document, but it never fills Acme's gap.
    globex = {i["item_id"]: i["status"] for i in DiligenceReviewer(db).checklist("globex")["items"]}
    assert globex == {"CL-01": "evidenced", "CL-02": "evidenced"}
