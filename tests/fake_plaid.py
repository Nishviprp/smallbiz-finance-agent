"""An in-memory stand-in for the Plaid API, served through httpx.MockTransport."""

from __future__ import annotations

import copy
import itertools
import json

import httpx


def txn(tid, date, name, amount, *, merchant=None, pfc=None, pending=False, account="acc-chk"):
    return {
        "transaction_id": tid,
        "account_id": account,
        "date": date,
        "name": name,
        "merchant_name": merchant,
        "amount": amount,  # Plaid sign: positive = money out
        "pending": pending,
        "personal_finance_category": {
            "primary": pfc.split(":")[0],
            "detailed": pfc.replace(":", "_"),
        }
        if pfc
        else None,
    }


DEFAULT_TXNS = [
    txn("t1", "2026-07-01", "SQUARE INC DEPOSIT", -850.25, pfc="INCOME"),
    txn("t2", "2026-07-02", "SYSCO NEW JERSEY", 412.50, pfc="FOOD_AND_DRINK"),
    txn("t3", "2026-07-03", "Starbucks", 4.33, merchant="Starbucks", pfc="FOOD_AND_DRINK"),
    txn("t4", "2026-07-05", "ACME LEGAL PARTNERS", 300.00,
        pfc="GENERAL_SERVICES:CONSULTING_AND_LEGAL"),
    txn("t5", "2026-07-06", "RIVERSIDE BOOK CLUB PAYMENT", -486.00, pfc="TRANSFER_IN"),
    txn("t6", "2026-07-07", "MYSTERY VENDOR 22", 19.99),
    txn("t7", "2026-07-08", "COSTCO WHSE", 75.10, pfc="GENERAL_MERCHANDISE", pending=True),
]  # fmt: skip


class FakePlaid:
    def __init__(self, page_size: int = 4):
        self.page_size = page_size
        self.items: dict[str, dict] = {}  # access_token -> item state
        self._ids = itertools.count(1)
        self.calls: list[str] = []
        self.fail: dict[str, dict] = {}  # path -> error body (one-shot)
        self.mutate_once = False
        self.link_requests: list[dict] = []

    # -- helpers for tests --------------------------------------------------------------
    def item(self, n: int = 0) -> dict:
        return list(self.items.values())[n]

    def queue(self, access_token: str | None = None, *, added=(), modified=(), removed=()):
        item = self.items[access_token] if access_token else self.item()
        item["pending_changes"].append(
            {"added": list(added), "modified": list(modified), "removed": list(removed)}
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # -- API ----------------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}")
        self.calls.append(path)
        if not body.get("client_id") or not body.get("secret"):
            return self._err(400, "INVALID_API_KEYS", "missing keys")
        if path in self.fail:
            err = self.fail.pop(path)
            return self._err(400, err["code"], err.get("message", "error"), err.get("display"))
        handler = getattr(self, "_" + path.strip("/").replace("/", "_"), None)
        if handler is None:
            return self._err(404, "NOT_FOUND", path)
        return handler(body)

    def _err(self, status, code, message, display=None):
        return httpx.Response(
            status,
            json={"error_code": code, "error_message": message, "display_message": display},
        )

    def _link_token_create(self, body):
        self.link_requests.append(body)
        return httpx.Response(200, json={"link_token": f"link-sandbox-{next(self._ids)}"})

    def _sandbox_public_token_create(self, body):
        return httpx.Response(200, json={"public_token": f"public-sandbox-{next(self._ids)}"})

    def _item_public_token_exchange(self, body):
        n = next(self._ids)
        token = f"access-sandbox-{n}"
        self.items[token] = {
            "item_id": f"item-{n}",
            "txns": copy.deepcopy(DEFAULT_TXNS),
            "pending_changes": [],
            "served_initial": False,
        }
        return httpx.Response(200, json={"access_token": token, "item_id": f"item-{n}"})

    def _accounts_get(self, body):
        if body["access_token"] not in self.items:
            return self._err(400, "INVALID_ACCESS_TOKEN", "bad token")
        return httpx.Response(
            200,
            json={
                "accounts": [
                    {"account_id": "acc-chk", "name": "Business Checking", "mask": "0000",
                     "type": "depository", "subtype": "checking"},
                    {"account_id": "acc-sav", "name": "Business Savings", "mask": "1111",
                     "type": "depository", "subtype": "savings"},
                ]
            },
        )  # fmt: skip

    def _item_get(self, body):
        return httpx.Response(200, json={"item": {"institution_id": "ins_109508"}})

    def _institutions_get_by_id(self, body):
        return httpx.Response(200, json={"institution": {"name": "First Platypus Bank"}})

    def _item_remove(self, body):
        self.items.pop(body["access_token"], None)
        return httpx.Response(200, json={})

    def _transactions_sync(self, body):
        token = body["access_token"]
        if token not in self.items:
            return self._err(400, "INVALID_ACCESS_TOKEN", "bad token")
        item = self.items[token]
        cursor = body.get("cursor") or ""
        count = body.get("count", 100)
        # Cursor format: "<batch>:<offset>"; batch 0 = initial history.
        batch, offset = (int(x) for x in cursor.split(":")) if cursor else (0, 0)
        if self.mutate_once and offset > 0:
            self.mutate_once = False
            return self._err(400, "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION", "changed")
        if batch == 0:
            source = {"added": item["txns"], "modified": [], "removed": []}
        elif batch - 1 < len(item["pending_changes"]):
            source = item["pending_changes"][batch - 1]
        else:
            return httpx.Response(
                200,
                json={"added": [], "modified": [], "removed": [], "has_more": False,
                      "next_cursor": cursor or f"{batch}:0"},
            )  # fmt: skip
        page_size = min(count, self.page_size)
        added = source["added"][offset : offset + page_size]
        has_more = offset + page_size < len(source["added"])
        resp = {
            "added": added,
            "modified": source["modified"] if offset == 0 else [],
            "removed": source["removed"] if offset == 0 else [],
            "has_more": has_more,
            "next_cursor": f"{batch}:{offset + page_size}" if has_more else f"{batch + 1}:0",
        }
        return httpx.Response(200, json=resp)
