def _upload(client, data: bytes, name="statement.csv", **form):
    return client.post(
        "/uploads/statement",
        files={"file": (name, data, "text/csv")},
        data={"use_llm": "false", **form},
    )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_default_categories_seeded(client):
    names = {c["name"] for c in client.get("/categories").json()}
    assert {"Sales", "Rent", "Payroll", "Transfers"} <= names


def test_upload_import_and_dedupe(client, sample_csv):
    r = _upload(client, sample_csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] > 300
    assert body["duplicates"] == 0
    # Most lines are recognised offline by built-in keywords.
    assert body["categorized"].get("keyword", 0) > body["imported"] * 0.7

    again = _upload(client, sample_csv).json()
    assert again["imported"] == 0
    assert again["duplicates"] == body["imported"]


def test_same_day_identical_lines_are_kept(client):
    csv = b"Date,Description,Amount\n2026-01-01,COFFEE,-3.00\n2026-01-01,COFFEE,-3.00\n"
    assert _upload(client, csv).json()["imported"] == 2


def test_rejects_unsupported_and_bad_files(client):
    assert _upload(client, b"x", name="statement.xlsx").status_code == 415
    assert _upload(client, b"%PDF-1.4 broken", name="s.pdf").status_code == 422
    assert _upload(client, b"hello,world\n1,2\n").status_code == 422
    assert _upload(client, b"").status_code == 400


def test_list_filters(client, sample_csv):
    _upload(client, sample_csv)
    page = client.get("/transactions", params={"limit": 5}).json()
    assert len(page["items"]) == 5 and page["total"] > 300
    dates = [i["date"] for i in page["items"]]
    assert dates == sorted(dates, reverse=True)

    out = client.get("/transactions", params={"direction": "out", "limit": 1000}).json()
    assert all(i["amount"] < 0 for i in out["items"])

    jan = client.get("/transactions", params={"start": "2026-01-01", "end": "2026-01-31"}).json()
    assert all(i["date"].startswith("2026-01") for i in jan["items"])

    found = client.get("/transactions", params={"search": "landlord"}).json()
    assert found["total"] == 6


def test_edit_category_and_remember(client, sample_csv):
    _upload(client, sample_csv)
    cats = {c["name"]: c["id"] for c in client.get("/categories").json()}
    uncats = client.get("/transactions", params={"search": "window cleaning"}).json()["items"]
    assert len(uncats) >= 2
    assert all(t["category_id"] is None for t in uncats)

    target = uncats[0]
    r = client.patch(
        f"/transactions/{target['id']}",
        json={"category_id": cats["Repairs & Maintenance"], "remember": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transaction"]["category_source"] == "user"
    assert body["rule_created"]["pattern"] == "smith window cleaning"
    assert body["also_updated"] == len(uncats) - 1

    after = client.get("/transactions", params={"search": "window cleaning"}).json()["items"]
    assert {t["category_name"] for t in after} == {"Repairs & Maintenance"}

    # Future imports use the learned rule.
    csv = b"Date,Description,Amount\n2026-07-04,J SMITH WINDOW CLEANING,-25.00\n"
    assert _upload(client, csv).json()["categorized"] == {"rule": 1}


def test_category_crud_and_delete_uncategorizes(client):
    r = client.post("/categories", json={"name": "Pet Supplies", "kind": "expense"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.post("/categories", json={"name": "Pet Supplies"}).status_code == 409

    csv = b"Date,Description,Amount\n2026-01-01,HAPPY HOUND DOG TREATS,-20.00\n"
    _upload(client, csv)
    tid = client.get("/transactions").json()["items"][0]["id"]
    client.patch(f"/transactions/{tid}", json={"category_id": cid, "remember": True})
    assert len(client.get("/rules").json()) == 1

    assert client.patch(f"/categories/{cid}", json={"name": "Pets"}).json()["name"] == "Pets"
    assert client.delete(f"/categories/{cid}").status_code == 204
    t = client.get(f"/transactions/{tid}").json()
    assert t["category_id"] is None and t["category_source"] == "none"
    assert client.get("/rules").json() == []


def test_rules_endpoint_applies_to_existing(client):
    csv = b"Date,Description,Amount\n2026-01-01,ACME WIDGETS 001,-10\n2026-01-02,ACME WIDGETS 002,-12\n"
    _upload(client, csv)
    cats = {c["name"]: c["id"] for c in client.get("/categories").json()}
    r = client.post("/rules", json={"pattern": "ACME widgets", "category_id": cats["Equipment"]})
    assert r.status_code == 201
    items = client.get("/transactions").json()["items"]
    assert {i["category_name"] for i in items} == {"Equipment"}


def test_recategorize_without_llm_is_noop_for_unknowns(client):
    _upload(client, b"Date,Description,Amount\n2026-01-01,UNKNOWN THING,-1\n")
    r = client.post("/transactions/recategorize", json={"use_llm": False})
    assert r.status_code == 200
    assert r.json() == {"updated": {}}
