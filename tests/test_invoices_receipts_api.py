import pytest

from finagent.ingest.text import ocr_available

from .conftest import SAMPLE_DIR

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="Tesseract OCR not installed")


def _post_file(client, endpoint, path, mime, **form):
    return client.post(
        endpoint,
        files={"file": (path.name, path.read_bytes(), mime)},
        data={"use_llm": "false", **form},
    )


def _import_statement(client):
    r = _post_file(client, "/uploads/statement", SAMPLE_DIR / "bank_statement_cafe.csv", "text/csv")
    assert r.status_code == 200, r.text
    return r.json()


# ---- Statements -------------------------------------------------------------


def test_pdf_statement_upload_dedupes_against_csv(client):
    _import_statement(client)
    r = _post_file(
        client, "/uploads/statement", SAMPLE_DIR / "bank_statement_cafe.pdf", "application/pdf"
    )
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 0
    assert r.json()["duplicates"] == 58


# ---- Invoices ---------------------------------------------------------------


def test_invoice_upload_auto_paid_from_statement(client):
    _import_statement(client)
    r = _post_file(
        client, "/uploads/invoice", SAMPLE_DIR / "invoices" / "INV-2026-014.pdf", "application/pdf"
    )
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["client"] == "Green Ltd"
    assert inv["status"] == "paid"
    assert inv["paid_date"] == "2026-01-18"
    assert inv["transaction_id"] is not None

    again = _post_file(
        client, "/uploads/invoice", SAMPLE_DIR / "invoices" / "INV-2026-014.pdf", "application/pdf"
    )
    assert again.status_code == 409


def test_invoice_paid_when_statement_arrives_later(client):
    r = _post_file(
        client, "/uploads/invoice", SAMPLE_DIR / "invoices" / "INV-2026-014.pdf", "application/pdf"
    )
    assert r.json()["status"] == "unpaid"
    assert _import_statement(client)["invoices_paid"] == 1
    assert client.get(f"/invoices/{r.json()['id']}").json()["status"] == "paid"


def test_overdue_invoice_and_alerts(client):
    _import_statement(client)
    r = _post_file(
        client, "/uploads/invoice", SAMPLE_DIR / "invoices" / "INV-2026-021.pdf", "application/pdf"
    )
    inv = r.json()
    assert inv["status"] == "unpaid"
    assert inv["effective_status"] == "overdue"

    client.post(
        "/invoices",
        json={
            "client": "Acme",
            "issue_date": "2026-06-01",
            "due_date": "2026-06-20",
            "amount": 100,
        },
    )
    alerts = client.get("/invoices/alerts", params={"today": "2026-06-15", "days": 7}).json()
    assert [a["client"] for a in alerts["overdue"]] == ["Riverside Book Club"]
    assert alerts["overdue"][0]["days"] == 10
    assert [a["client"] for a in alerts["due_soon"]] == ["Acme"]
    assert alerts["total_outstanding"] == 586.0
    assert alerts["total_overdue"] == 486.0
    assert alerts["aging"]["1-30"] == 486.0

    overdue = client.get("/invoices", params={"status": "overdue"}).json()
    assert "INV-2026-021" in [i["number"] for i in overdue]  # vs. the real today


def test_invoice_crud_and_mark_paid(client):
    r = client.post(
        "/invoices",
        json={"number": "A-1", "client": "Bob", "issue_date": "2026-03-01", "amount": "250.00"},
    )
    assert r.status_code == 201
    inv = r.json()
    assert inv["due_date"] == "2026-03-31"  # default 30-day terms

    bad = client.post(
        "/invoices",
        json={"client": "X", "issue_date": "2026-03-10", "due_date": "2026-03-01", "amount": 1},
    )
    assert bad.status_code == 422

    paid = client.post(f"/invoices/{inv['id']}/mark-paid", json={"paid_date": "2026-03-20"})
    assert paid.json()["status"] == "paid" and paid.json()["paid_date"] == "2026-03-20"

    reopened = client.patch(f"/invoices/{inv['id']}", json={"status": "unpaid"}).json()
    assert reopened["paid_date"] is None

    assert client.delete(f"/invoices/{inv['id']}").status_code == 204
    assert client.get(f"/invoices/{inv['id']}").status_code == 404


def test_ambiguous_payments_not_auto_matched(client):
    csv = (
        b"Date,Description,Amount\n2026-04-10,FPI PAYMENT,500.00\n2026-04-12,FPI TRANSFER,500.00\n"
    )
    client.post(
        "/uploads/statement", files={"file": ("s.csv", csv, "text/csv")}, data={"use_llm": "false"}
    )
    r = client.post(
        "/invoices", json={"client": "Zed Corp", "issue_date": "2026-04-01", "amount": 500}
    )
    assert r.json()["status"] == "unpaid"  # two identical payments, no name/number to decide


# ---- Receipts ---------------------------------------------------------------


def test_receipt_pdf_links_to_transaction(client):
    _import_statement(client)
    r = _post_file(
        client, "/uploads/receipt", SAMPLE_DIR / "receipts" / "receipt_makro.pdf", "application/pdf"
    )
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["total"] == 132.91
    txn = client.get(f"/transactions/{rec['transaction_id']}").json()
    assert txn["amount"] == -132.91 and "MAKRO" in txn["description"]


@needs_ocr
def test_receipt_photo_links_after_statement_import(client):
    r = _post_file(
        client, "/uploads/receipt", SAMPLE_DIR / "receipts" / "receipt_screwfix.png", "image/png"
    )
    assert r.status_code == 200, r.text
    assert r.json()["transaction_id"] is None
    assert _import_statement(client)["receipts_linked"] == 1
    linked = client.get("/receipts").json()[0]
    assert linked["transaction_id"] is not None


def test_receipt_edit_and_delete(client):
    r = _post_file(
        client, "/uploads/receipt", SAMPLE_DIR / "receipts" / "receipt_makro.pdf", "application/pdf"
    )
    rid = r.json()["id"]
    upd = client.patch(f"/receipts/{rid}", json={"vendor": "Makro Charlton", "notes": "stock"})
    assert upd.json()["vendor"] == "Makro Charlton"
    assert client.patch(f"/receipts/{rid}", json={"transaction_id": 99999}).status_code == 404
    assert client.get("/receipts", params={"unlinked": True}).json()[0]["id"] == rid
    assert client.delete(f"/receipts/{rid}").status_code == 204


def test_document_upload_rejects_bad_types(client):
    r = client.post("/uploads/receipt", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 415
