"""Restricted, tenant-filtered SQL execution.

Each query runs on a fresh read-only connection. Tenant-filtered TEMP views shadow
the real tables, and an SQLite authorizer only allows reads that go through those
views, so a query can neither escape its tenant nor touch other tables.
"""

from __future__ import annotations

import re
import sqlite3

from .db import Database

# view name -> columns exposed (tenant_id is never exposed)
ALLOWED_VIEWS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id", "name", "segment", "region"),
    "orders": ("order_id", "customer_id", "order_date", "product", "quantity", "unit_price"),
    "documents": ("doc_id", "title", "category"),
}

ALLOWED_FUNCTIONS = frozenset({
    "count", "sum", "total", "avg", "min", "max", "round", "abs", "coalesce", "ifnull", "nullif",
    "lower", "upper", "length", "substr", "trim", "date", "strftime", "julianday", "printf", "iif",
    "group_concat",
})

MAX_QUERY_CHARS = 4000
MAX_VM_STEPS = 2_000_000
_LEADING_KEYWORD = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class SQLGuardError(ValueError):
    """Raised when a query is rejected or fails under the guard."""


def describe_schema() -> dict:
    return {
        "dialect": "sqlite",
        "tables": {name: list(cols) for name, cols in ALLOWED_VIEWS.items()},
        "notes": [
            "Read-only SELECT/WITH queries only; one statement.",
            "Rows are automatically restricted to the caller's tenant.",
            "orders.unit_price is a decimal string; multiply by quantity for revenue.",
        ],
    }


def _validate_text(query: str) -> str:
    if len(query) > MAX_QUERY_CHARS:
        raise SQLGuardError("Query is too long.")
    stripped = _COMMENT.sub(" ", query).strip().rstrip(";").strip()
    if not stripped:
        raise SQLGuardError("Query is empty.")
    if ";" in stripped:
        raise SQLGuardError("Only a single statement is allowed.")
    if not _LEADING_KEYWORD.match(stripped):
        raise SQLGuardError("Only SELECT or WITH queries are allowed.")
    return stripped


class SQLGuard:
    def __init__(self, db: Database, max_rows: int = 200):
        self.db = db
        self.max_rows = max_rows

    def _install_views(self, conn: sqlite3.Connection, tenant_id: str) -> None:
        tenant = tenant_id.replace("'", "''")
        for view, cols in ALLOWED_VIEWS.items():
            conn.execute(
                f"CREATE TEMP VIEW {view} AS SELECT {', '.join(cols)} "
                f"FROM main.{view} WHERE tenant_id = '{tenant}'"
            )

    @staticmethod
    def _authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # Allow columns of the tenant views themselves, and underlying-table
            # reads performed on behalf of those views. Nothing else.
            if dbname == "temp" and arg1 in ALLOWED_VIEWS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_OK if source in ALLOWED_VIEWS else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (arg2 or "").lower() in ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY

    def execute(self, tenant_id: str, query: str) -> dict:
        sql = _validate_text(query)
        conn = self.db.readonly_connection()
        try:
            self._install_views(conn, tenant_id)
            conn.set_authorizer(self._authorizer)
            steps = {"n": 0}

            def progress() -> int:
                steps["n"] += 1000
                return 1 if steps["n"] > MAX_VM_STEPS else 0

            conn.set_progress_handler(progress, 1000)
            try:
                cursor = conn.execute(sql)
                rows = cursor.fetchmany(self.max_rows + 1)
            except sqlite3.DatabaseError as exc:
                raise SQLGuardError(f"Query rejected: {exc}") from exc
            columns = [d[0] for d in cursor.description or []]
            truncated = len(rows) > self.max_rows
            rows = rows[: self.max_rows]
            return {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }
        finally:
            conn.close()
