from conftest import ACME_ANALYST

from querypilot import analytics


def test_rfm_scores_are_fixed(db):
    result = analytics.rfm(db, "acme")
    assert result["as_of"] == "2025-12-31"
    table = {c["customer_id"]: (c["recency_days"], c["frequency"], c["monetary"], c["rfm_code"], c["segment"])
             for c in result["customers"]}
    assert table == {
        "C001": (31, 4, 113875.0, "355", "Loyal"),
        "C002": (26, 3, 38100.0, "434", "Developing"),
        "C003": (113, 2, 33800.0, "113", "Hibernating"),
        "C005": (90, 3, 26375.0, "232", "Hibernating"),
        "C006": (11, 2, 5960.0, "511", "Developing"),
        "C004": (225, 1, 3850.0, "111", "Hibernating"),
    }
    assert [c["customer_id"] for c in result["customers"]] == ["C001", "C002", "C003", "C005", "C006", "C004"]


def test_customer_concentration_is_fixed(db, client):
    result = analytics.concentration(db, "acme", top_n=3)
    assert result["total_revenue"] == 221960.0
    assert [c["share_pct"] for c in result["customers"]] == [51.3, 17.17, 15.23, 11.88, 2.69, 1.73]
    assert result["top_n_share_pct"] == 83.7
    assert result["hhi"] == 3310.09
    assert result["classification"] == "highly concentrated"
    api = client.get("/v1/analytics/concentration?top_n=1", headers=ACME_ANALYST).json()
    assert api["top_n_share_pct"] == 51.3


def test_weighted_price_summary_is_fixed(db):
    products = {p["product"]: p for p in analytics.weighted_prices(db, "acme")["products"]}
    assert products["BS-100"] == {
        "product": "BS-100", "orders": 6, "total_quantity": 2490, "revenue": 104160.0,
        "weighted_avg_price": 41.83, "simple_avg_price": 42.33, "min_price": 41.0, "max_price": 44.0,
    }
    assert (products["CU-300"]["weighted_avg_price"], products["CU-300"]["simple_avg_price"]) == (323.33, 327.5)
    assert (products["TS-200"]["weighted_avg_price"], products["TS-200"]["revenue"]) == (18.91, 20800.0)
    only = analytics.weighted_prices(db, "acme", product="CU-300")["products"]
    assert [p["product"] for p in only] == ["CU-300"]
