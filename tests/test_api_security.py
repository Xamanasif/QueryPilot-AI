from conftest import ACME_ANALYST, ACME_REVIEWER, GLOBEX_ANALYST


def test_missing_api_key_is_rejected(client):
    assert client.get("/health").status_code == 200
    resp = client.get("/v1/documents")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing X-API-Key header"


def test_invalid_api_key_is_rejected(client):
    resp = client.post("/v1/search", json={"query": "change of control"}, headers={"X-API-Key": "qp_wrong"})
    assert resp.status_code == 401


def test_only_reviewers_can_approve_document_versions(client):
    path = "/v1/documents/ACME-MSA-001/versions/2/approve"
    assert client.post(path, headers=ACME_ANALYST).status_code == 403
    resp = client.post(path, headers=ACME_REVIEWER)
    assert resp.status_code == 200
    assert resp.json()["approved_by"] == "rui.reviewer"
    # Already-approved versions cannot be approved again.
    assert client.post(path, headers=ACME_REVIEWER).status_code == 409

    # Analysts submit new documents as drafts; they become citable only after approval.
    body = {"title": "Senior Facility Agreement", "category": "financial",
            "content": "Debt. A EUR 12 million revolving facility carries a net leverage covenant of 2.5x.\n\n"
                       "Lender. The facility is provided by a single relationship lender."}
    draft = client.post("/v1/documents/ACME-DEBT-007/versions", json=body, headers=ACME_ANALYST)
    assert draft.status_code == 201
    assert draft.json() == {"doc_id": "ACME-DEBT-007", "version": 1, "status": "draft", "chunks": 2}
    gaps = {g["item_id"] for g in client.get("/v1/diligence/gaps", headers=ACME_ANALYST).json()["gaps"]}
    assert "CL-06" in gaps
    client.post("/v1/documents/ACME-DEBT-007/versions/1/approve", headers=ACME_REVIEWER)
    gaps = {g["item_id"] for g in client.get("/v1/diligence/gaps", headers=ACME_ANALYST).json()["gaps"]}
    assert gaps == {"CL-05"}


def test_api_enforces_tenant_isolation(client):
    acme_docs = {d["doc_id"] for d in client.get("/v1/documents", headers=ACME_ANALYST).json()["documents"]}
    globex_docs = {d["doc_id"] for d in client.get("/v1/documents", headers=GLOBEX_ANALYST).json()["documents"]}
    assert acme_docs and globex_docs and not acme_docs & globex_docs

    hits = client.post("/v1/search", json={"query": "Brightline refrigerated trailers lease"},
                       headers=ACME_ANALYST).json()["results"]
    assert hits == []

    sql = client.post("/v1/sql", json={"query": "SELECT customer_id FROM customers ORDER BY 1"},
                      headers=GLOBEX_ANALYST).json()
    assert [r[0] for r in sql["rows"]] == ["G001", "G002", "G003"]

    # A reviewer from another tenant cannot touch Acme's documents.
    assert client.post("/v1/documents/GLX-LEASE-001/versions/1/approve",
                       headers=ACME_REVIEWER).status_code == 404
    # ...and Globex cannot slip a draft into an Acme document.
    assert client.post("/v1/documents/ACME-MSA-001/versions", json={"content": "Change of control waived."},
                       headers=GLOBEX_ANALYST).status_code == 404
