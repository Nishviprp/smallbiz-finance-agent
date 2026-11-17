import datetime as dt
from decimal import Decimal

import pytest

from finagent.services.analytics import months_between


def _load(client, csv: bytes):
    r = client.post(
        "/uploads/statement", files={"file": ("s.csv", csv, "text/csv")}, data={"use_llm": "false"}
    )
    assert r.status_code == 200, r.text


SMALL = (
    b"Date,Description,Amount\n"
    b"2026-01-05,SUMUP PAYOUT,1000.00\n"
    b"2026-01-06,BOOKERS WHOLESALE,-300.00\n"
    b"2026-01-07,TRANSFER TO SAVINGS,-200.00\n"
    b"2026-01-08,MYSTERY SHOP,-50.00\n"
    b"2026-02-02,SUMUP PAYOUT,800.00\n"
    b"2026-02-03,LANDLORD RENT,-500.00\n"
    b"2026-02-04,BOOKERS WHOLESALE REFUND,40.00\n"
)


def test_months_between():
    assert months_between(dt.date(2025, 11, 20), dt.date(2026, 2, 1)) == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]


def test_empty_db(client):
    assert client.get("/reports/summary").json() == {"empty": True}
    assert client.get("/reports/monthly").json() == []
    assert client.get("/reports/range").json() == {"start": None, "end": None}


def test_summary_definitions(client):
    _load(client, SMALL)
    s = client.get("/reports/summary").json()
    # Income: payouts (1800) + uncategorized money in (the refund has no keyword: 40)
    assert s["income"] == 1840.0
    # Expenses: 300 COGS + 500 rent + 50 uncategorized; transfer excluded
    assert s["expenses"] == 850.0
    assert s["net_profit"] == 990.0
    assert s["cash_out"] == 1050.0  # transfer counted in cash
    assert s["net_cash"] == 790.0
    assert s["uncategorized_count"] == 2
    assert s["profit_margin_pct"] == pytest.approx(990 / 1840 * 100)


def test_summary_previous_period_deltas(client):
    _load(client, SMALL)
    s = client.get("/reports/summary", params={"start": "2026-02-01", "end": "2026-02-28"}).json()
    assert s["previous"]["start"] == "2026-01-04"  # same 28-day length, right before
    assert s["change_pct"]["income"] is not None


def test_monthly_and_cumulative(client):
    _load(client, SMALL)
    rows = client.get("/reports/monthly").json()
    assert [r["month"] for r in rows] == ["2026-01", "2026-02"]
    assert rows[0]["net_cash"] == 450.0
    assert rows[1]["cumulative_net_cash"] == 790.0


def test_pnl_excludes_transfers(client):
    _load(client, SMALL)
    p = client.get("/reports/pnl").json()
    names = {x["category"] for x in p["expenses"]}
    assert "Transfers" not in names
    assert p["net_transfers"] == -200.0
    assert p["net_profit"] == p["total_income"] - p["total_expenses"]
    rent = next(x for x in p["expenses"] if x["category"] == "Rent")
    assert rent["by_month"] == {"2026-01": 0.0, "2026-02": 500.0}


def test_refund_reduces_expense_category(client):
    _load(client, SMALL)
    cats = {c["name"]: c["id"] for c in client.get("/categories").json()}
    refund = client.get("/transactions", params={"search": "refund"}).json()["items"][0]
    client.patch(f"/transactions/{refund['id']}", json={"category_id": cats["Cost of Goods Sold"]})
    p = client.get("/reports/pnl").json()
    cogs = next(x for x in p["expenses"] if x["category"] == "Cost of Goods Sold")
    assert cogs["total"] == 260.0


def test_top_expenses_and_trends(client, sample_csv):
    client.post(
        "/uploads/statement",
        files={"file": ("s.csv", sample_csv, "text/csv")},
        data={"use_llm": "false"},
    )
    top = client.get("/reports/top-expenses", params={"limit": 3}).json()
    assert [c["category"] for c in top["categories"]] == ["Payroll", "Cost of Goods Sold", "Rent"]
    assert sum(c["share_pct"] for c in top["categories"]) < 100
    assert top["merchants"][0]["count"] == 6

    full = client.get("/reports/category-trends", params={"top": 3}).json()
    jan = client.get(
        "/reports/category-trends", params={"top": 3, "start": "2026-01-01", "end": "2026-01-31"}
    ).json()
    # Series order (→ colours) is stable when the period filter changes.
    assert [s["category"] for s in jan["series"]] == [s["category"] for s in full["series"]]
    assert full["series"][-1]["category"] == "Other"
    total = sum(sum(Decimal(str(v)) for v in s["values"]) for s in full["series"])
    assert float(total) == pytest.approx(top["total_expenses"], abs=0.05)
