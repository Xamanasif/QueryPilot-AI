import pytest

from querypilot.sql_guard import SQLGuard, SQLGuardError

WRITES_AND_STACKED = [
    "DELETE FROM orders",
    "UPDATE customers SET name = 'x'",
    "DROP TABLE orders",
    "SELECT 1; DROP TABLE orders",
    "PRAGMA table_info(orders)",
    "ATTACH DATABASE 'other.db' AS other",
]

TENANT_BYPASS = [
    "SELECT * FROM api_keys",
    "SELECT COUNT(*) FROM main.customers",
    "SELECT * FROM (SELECT tenant_id, name FROM main.customers)",
    "SELECT name FROM sqlite_master",
    "SELECT tenant_id FROM customers",
    "SELECT load_extension('evil')",
]


def test_rejects_writes_and_multiple_statements(db):
    guard = SQLGuard(db)
    for query in WRITES_AND_STACKED:
        with pytest.raises(SQLGuardError):
            guard.execute("acme", query)
    assert guard.execute("acme", "SELECT COUNT(*) FROM orders")["rows"] == [[15]]


def test_rejects_unlisted_tables_and_tenant_bypass(db):
    guard = SQLGuard(db)
    for query in TENANT_BYPASS:
        with pytest.raises(SQLGuardError):
            guard.execute("acme", query)


def test_tenant_filter_is_applied_automatically(db):
    guard = SQLGuard(db)
    acme = guard.execute("acme", "SELECT COUNT(*), SUM(quantity * unit_price) FROM orders")
    globex = guard.execute("globex", "SELECT COUNT(*), SUM(quantity * unit_price) FROM orders")
    assert acme["rows"] == [[15, 221960.0]]
    assert globex["rows"] == [[3, 105200.0]]


def test_row_limit_is_enforced(db):
    result = SQLGuard(db, max_rows=5).execute("acme", "SELECT order_id FROM orders ORDER BY order_id")
    assert result["row_count"] == 5 and result["truncated"] is True
    assert result["rows"][0] == ["O1001"]
