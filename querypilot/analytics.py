"""Commercial analytics with exact decimal arithmetic and deterministic outputs.

- RFM: recency / frequency / monetary scoring against a fixed as-of date.
- Concentration: top-N revenue share and Herfindahl-Hirschman Index (HHI).
- Weighted prices: quantity-weighted average unit price per product.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .db import Database
from .seed_data import ANALYSIS_AS_OF

CENT = Decimal("0.01")
SCORE_BUCKETS = 5


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _num(value: Decimal) -> float:
    """Serialise a 2dp decimal for JSON."""
    return float(q2(value))


def _orders(db: Database, tenant_id: str) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT o.order_id, o.customer_id, c.name, o.order_date, o.product, o.quantity, o.unit_price
               FROM orders o JOIN customers c
                 ON c.tenant_id = o.tenant_id AND c.customer_id = o.customer_id
               WHERE o.tenant_id = ? ORDER BY o.order_id""",
            (tenant_id,),
        ).fetchall()
    return [{**dict(r), "unit_price": Decimal(r["unit_price"])} for r in rows]


def _bucket_scores(values: dict[str, Decimal | int], higher_is_better: bool) -> dict[str, int]:
    """Rank-based 1..5 scores; equal values share a score; ties ordered by key."""
    ordered = sorted(values, key=lambda k: (values[k] if higher_is_better else -values[k], k))
    n = len(ordered)
    scores: dict[str, int] = {}
    first_score_for_value: dict = {}
    for i, key in enumerate(ordered):
        score = first_score_for_value.setdefault(values[key], i * SCORE_BUCKETS // n + 1)
        scores[key] = score
    return scores


def _segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4:
        return "Champion"
    if r <= 2 and m >= 4:
        return "At Risk"
    if f >= 4:
        return "Loyal"
    if r <= 2:
        return "Hibernating"
    return "Developing"


def rfm(db: Database, tenant_id: str, as_of: str = ANALYSIS_AS_OF) -> dict:
    ref = date.fromisoformat(as_of)
    last: dict[str, date] = {}
    freq: dict[str, int] = defaultdict(int)
    money: dict[str, Decimal] = defaultdict(Decimal)
    names: dict[str, str] = {}
    for o in _orders(db, tenant_id):
        cid = o["customer_id"]
        names[cid] = o["name"]
        d = date.fromisoformat(o["order_date"])
        last[cid] = max(last.get(cid, d), d)
        freq[cid] += 1
        money[cid] += o["quantity"] * o["unit_price"]
    if not names:
        return {"as_of": as_of, "customers": []}

    recency = {cid: (ref - d).days for cid, d in last.items()}
    r_s = _bucket_scores(recency, higher_is_better=False)
    f_s = _bucket_scores(dict(freq), higher_is_better=True)
    m_s = _bucket_scores(dict(money), higher_is_better=True)
    customers = [
        {
            "customer_id": cid,
            "name": names[cid],
            "recency_days": recency[cid],
            "frequency": freq[cid],
            "monetary": _num(money[cid]),
            "r": r_s[cid], "f": f_s[cid], "m": m_s[cid],
            "rfm_code": f"{r_s[cid]}{f_s[cid]}{m_s[cid]}",
            "segment": _segment(r_s[cid], f_s[cid], m_s[cid]),
        }
        for cid in names
    ]
    customers.sort(key=lambda c: (-c["monetary"], c["customer_id"]))
    return {"as_of": as_of, "customers": customers}


def concentration(db: Database, tenant_id: str, top_n: int = 3) -> dict:
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    names: dict[str, str] = {}
    for o in _orders(db, tenant_id):
        revenue[o["customer_id"]] += o["quantity"] * o["unit_price"]
        names[o["customer_id"]] = o["name"]
    total = sum(revenue.values(), Decimal(0))
    if total == 0:
        return {"total_revenue": 0.0, "customers": [], "top_n": top_n,
                "top_n_share_pct": 0.0, "hhi": 0.0, "classification": "n/a"}

    ranked = sorted(revenue, key=lambda c: (-revenue[c], c))
    shares = {c: revenue[c] * 100 / total for c in ranked}
    hhi = sum((s * s for s in shares.values()), Decimal(0))
    top_share = sum((shares[c] for c in ranked[:top_n]), Decimal(0))
    if hhi < 1500:
        classification = "unconcentrated"
    elif hhi <= 2500:
        classification = "moderately concentrated"
    else:
        classification = "highly concentrated"
    return {
        "total_revenue": _num(total),
        "customers": [
            {"customer_id": c, "name": names[c], "revenue": _num(revenue[c]), "share_pct": _num(shares[c])}
            for c in ranked
        ],
        "top_n": top_n,
        "top_n_share_pct": _num(top_share),
        "hhi": _num(hhi),
        "classification": classification,
    }


def weighted_prices(db: Database, tenant_id: str, product: str | None = None) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in _orders(db, tenant_id):
        if product is None or o["product"] == product:
            groups[o["product"]].append(o)
    products = []
    for name in sorted(groups):
        rows = groups[name]
        qty = sum(r["quantity"] for r in rows)
        revenue = sum((r["quantity"] * r["unit_price"] for r in rows), Decimal(0))
        prices = [r["unit_price"] for r in rows]
        products.append({
            "product": name,
            "orders": len(rows),
            "total_quantity": qty,
            "revenue": _num(revenue),
            "weighted_avg_price": _num(revenue / qty),
            "simple_avg_price": _num(sum(prices, Decimal(0)) / len(prices)),
            "min_price": _num(min(prices)),
            "max_price": _num(max(prices)),
        })
    return {"products": products}
