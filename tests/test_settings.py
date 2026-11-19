import pytest


def test_defaults_are_us(client):
    s = client.get("/settings").json()
    assert s["currency"] == "USD"
    assert s["date_dayfirst"] is False
    assert s["tax_year_start"] == "01-01"
    assert s["setup_complete"] is False
    assert client.get("/health").json()["setup_complete"] is False


def test_save_profile(client):
    r = client.put(
        "/settings",
        json={
            "business_name": "  Corner Shop Ltd ",
            "country": "GB",
            "currency": "gbp",
            "date_dayfirst": True,
            "tax_year_start": "04-06",
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["business_name"], s["currency"], s["setup_complete"]) == (
        "Corner Shop Ltd",
        "GBP",
        True,
    )
    health = client.get("/health").json()
    assert health["currency"] == "GBP" and health["business_name"] == "Corner Shop Ltd"
    years = client.get("/export/tax-years").json()
    assert years == []  # no data yet, but the endpoint uses the saved tax year


@pytest.mark.parametrize(
    "body",
    [
        {"country": "XX"},
        {"currency": "US1"},
        {"tax_year_start": "13-45"},
        {"business_name": "   "},
    ],
)
def test_invalid_profile(client, body):
    assert client.put("/settings", json=body).status_code == 422


def test_profile_drives_imports_and_dates(client):
    client.put(
        "/settings",
        json={
            "business_name": "UK Café",
            "country": "GB",
            "currency": "GBP",
            "date_dayfirst": True,
        },
    )
    csv = b"Date,Description,Amount\n03/04/2026,SUMUP PAYOUT,100.00\n"  # ambiguous date
    client.post(
        "/uploads/statement", files={"file": ("s.csv", csv, "text/csv")}, data={"use_llm": "false"}
    )
    t = client.get("/transactions").json()["items"][0]
    assert t["currency"] == "GBP"
    assert t["date"] == "2026-04-03"  # DD/MM because of the profile


def test_relabel_existing_currency(client):
    client.post(
        "/uploads/statement",
        files={"file": ("s.csv", b"Date,Description,Amount\n2026-01-05,X,-5\n", "text/csv")},
        data={"use_llm": "false"},
    )
    s = client.put("/settings", json={"currency": "CAD"}).json()
    assert s["other_currency_transactions"] == 1
    s = client.put("/settings", json={"currency": "CAD", "relabel_existing": True}).json()
    assert s["other_currency_transactions"] == 0
    assert client.get("/transactions").json()["items"][0]["currency"] == "CAD"


def test_demo_and_reset(client):
    r = client.post("/settings/demo").json()
    assert (r["transactions"], r["invoices"], r["receipts"]) == (337, 2, 2)
    again = client.post("/settings/demo").json()
    assert again["transactions"] == 0 and len(again["skipped"]) == 2  # idempotent

    assert client.post("/settings/reset", json={"confirm": "yes"}).status_code == 400
    r = client.post("/settings/reset", json={"confirm": "DELETE"}).json()
    assert r["deleted"]["transactions"] == 337
    assert client.get("/transactions").json()["total"] == 0
    assert client.get("/invoices").json() == []
    assert len(client.get("/categories").json()) > 20  # categories are kept


def test_dates_follow_profile(client):
    client.post("/settings/demo")
    q = {"question": "How much did we spend on rent?", "use_llm": False}
    assert "Jan 1, 2026 – Jun 30, 2026" in client.post("/chat", json=q).json()["answer"]
    client.put("/settings", json={"date_dayfirst": True})
    assert "1 Jan 2026 – 30 Jun 2026" in client.post("/chat", json=q).json()["answer"]
