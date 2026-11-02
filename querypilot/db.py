"""SQLite storage: schema, connections, document versioning and seeding."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import seed_data

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    deal_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash  TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    principal TEXT NOT NULL,
    role      TEXT NOT NULL CHECK (role IN ('analyst', 'reviewer'))
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id    TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    title     TEXT NOT NULL,
    category  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_versions (
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id),
    version     INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'superseded')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    PRIMARY KEY (doc_id, version)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id  TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL,
    version   INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    ordinal   INTEGER NOT NULL,
    text      TEXT NOT NULL,
    FOREIGN KEY (doc_id, version) REFERENCES document_versions(doc_id, version)
);
CREATE TABLE IF NOT EXISTS checklist_items (
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    item_id     TEXT NOT NULL,
    workstream  TEXT NOT NULL,
    requirement TEXT NOT NULL,
    query       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, item_id)
);
CREATE TABLE IF NOT EXISTS customers (
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    customer_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    segment     TEXT NOT NULL,
    region      TEXT NOT NULL,
    PRIMARY KEY (tenant_id, customer_id)
);
CREATE TABLE IF NOT EXISTS orders (
    tenant_id   TEXT NOT NULL REFERENCES tenants(tenant_id),
    order_id    TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    order_date  TEXT NOT NULL,
    product     TEXT NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, order_id)
);
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id        TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    principal     TEXT NOT NULL,
    question      TEXT NOT NULL,
    status        TEXT NOT NULL,
    answer        TEXT,
    citations     TEXT NOT NULL,
    trace         TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    reviewer      TEXT,
    review_note   TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(tenant_id, customer_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def chunk_id(doc_id: str, version: int, ordinal: int) -> str:
    return f"{doc_id}@v{version}#c{ordinal}"


def split_paragraphs(content: str) -> list[str]:
    return [p.strip() for p in content.split("\n\n") if p.strip()]


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def readonly_connection(self) -> sqlite3.Connection:
        """A connection that cannot write to the main database file."""
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # -- documents ---------------------------------------------------------

    def add_document_version(self, conn: sqlite3.Connection, doc_id: str, version: int,
                             status: str, content: str, approved_by: str | None = None) -> None:
        tenant_id = conn.execute(
            "SELECT tenant_id FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()["tenant_id"]
        ts = now_iso()
        conn.execute(
            "INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, version, status, content, ts, approved_by,
             ts if status in ("approved", "superseded") else None),
        )
        conn.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)",
            [(chunk_id(doc_id, version, i), doc_id, version, tenant_id, i, text)
             for i, text in enumerate(split_paragraphs(content), start=1)],
        )

    def submit_draft(self, tenant_id: str, doc_id: str, content: str,
                     title: str | None = None, category: str | None = None) -> dict:
        """Add a new draft version, creating the document if needed. Drafts are not
        searchable or citable until a reviewer approves them."""
        if not split_paragraphs(content):
            raise ValueError("Document content is empty")
        with self.connect() as conn:
            doc = conn.execute("SELECT tenant_id FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
            if doc is None:
                if not (title and category):
                    raise ValueError("title and category are required for a new document")
                conn.execute("INSERT INTO documents VALUES (?, ?, ?, ?)", (doc_id, tenant_id, title, category))
            elif doc["tenant_id"] != tenant_id:
                raise LookupError(f"{doc_id} not found")
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM document_versions WHERE doc_id = ?", (doc_id,)
            ).fetchone()[0]
            self.add_document_version(conn, doc_id, version, "draft", content)
        return {"doc_id": doc_id, "version": version, "status": "draft",
                "chunks": len(split_paragraphs(content))}

    def approve_version(self, tenant_id: str, doc_id: str, version: int, approver: str) -> dict:
        """Approve a draft version; the previously approved version becomes superseded."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT v.status FROM document_versions v JOIN documents d USING (doc_id)
                   WHERE d.tenant_id = ? AND v.doc_id = ? AND v.version = ?""",
                (tenant_id, doc_id, version),
            ).fetchone()
            if row is None:
                raise LookupError(f"{doc_id} v{version} not found")
            if row["status"] != "draft":
                raise ValueError(f"{doc_id} v{version} is {row['status']}; only drafts can be approved")
            conn.execute(
                "UPDATE document_versions SET status = 'superseded' WHERE doc_id = ? AND status = 'approved'",
                (doc_id,),
            )
            conn.execute(
                """UPDATE document_versions SET status = 'approved', approved_by = ?, approved_at = ?
                   WHERE doc_id = ? AND version = ?""",
                (approver, now_iso(), doc_id, version),
            )
        return {"doc_id": doc_id, "version": version, "status": "approved", "approved_by": approver}

    def list_documents(self, tenant_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT d.doc_id, d.title, d.category, v.version, v.status, v.approved_by, v.approved_at
                   FROM documents d JOIN document_versions v USING (doc_id)
                   WHERE d.tenant_id = ? ORDER BY d.doc_id, v.version""",
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- seeding -----------------------------------------------------------

    def seed_demo(self) -> None:
        """Load the deterministic simulated diligence dataset (idempotent)."""
        self.init_schema()
        with self.connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]:
                return
            for tenant in seed_data.TENANTS:
                conn.execute("INSERT INTO tenants VALUES (?, ?, ?)",
                             (tenant["tenant_id"], tenant["name"], tenant["deal_name"]))
            for key in seed_data.API_KEYS:
                conn.execute("INSERT INTO api_keys VALUES (?, ?, ?, ?)",
                             (hash_key(key["key"]), key["tenant_id"], key["principal"], key["role"]))
            for doc in seed_data.DOCUMENTS:
                conn.execute("INSERT INTO documents VALUES (?, ?, ?, ?)",
                             (doc["doc_id"], doc["tenant_id"], doc["title"], doc["category"]))
                for v in doc["versions"]:
                    self.add_document_version(conn, doc["doc_id"], v["version"], v["status"],
                                              v["content"], v.get("approved_by"))
            conn.executemany("INSERT INTO checklist_items VALUES (?, ?, ?, ?, ?)", seed_data.CHECKLIST)
            conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?)", seed_data.CUSTOMERS)
            conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", seed_data.ORDERS)
