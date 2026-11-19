"""Minimal Plaid API client (httpx). Docs: https://plaid.com/docs/api/"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

HOSTS = {"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}
SANDBOX_INSTITUTION = "ins_109508"  # "First Platypus Bank" — Plaid's sandbox test bank
REAUTH_CODES = {"ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION", "ACCESS_NOT_GRANTED"}


class PlaidError(RuntimeError):
    def __init__(self, code: str, message: str, display: str | None = None, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.display, self.status = code, message, display, status

    @property
    def user_message(self) -> str:
        return self.display or self.message

    @property
    def needs_reauth(self) -> bool:
        return self.code in REAUTH_CODES


class PlaidNotConfigured(RuntimeError):
    pass


class PlaidClient:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None
    ):
        s = settings or get_settings()
        if not (s.plaid_client_id and s.plaid_secret):
            raise PlaidNotConfigured(
                "Bank feeds are not set up. Add PLAID_CLIENT_ID and PLAID_SECRET to .env."
            )
        self.env = s.plaid_env
        self.countries = [c.strip().upper() for c in s.plaid_country_codes.split(",") if c.strip()]
        self._auth = {"client_id": s.plaid_client_id, "secret": s.plaid_secret}
        base = s.plaid_base_url or HOSTS[s.plaid_env]
        self._http = httpx.Client(base_url=base, timeout=60, transport=transport)

    def _post(self, path: str, body: dict) -> dict[str, Any]:
        try:
            r = self._http.post(path, json={**self._auth, **body})
        except httpx.HTTPError as exc:
            raise PlaidError(
                "NETWORK_ERROR", f"Could not reach Plaid ({exc.__class__.__name__})"
            ) from exc
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            raise PlaidError(
                data.get("error_code", "UNKNOWN"),
                data.get("error_message", r.text[:200]),
                data.get("display_message"),
                r.status_code,
            )
        return data

    # -- Link -------------------------------------------------------------------------

    def create_link_token(self, client_user_id: str, *, access_token: str | None = None) -> str:
        """Token for Plaid Link. Pass access_token to repair a connection (update mode)."""
        body: dict[str, Any] = {
            "client_name": "SmallBiz Finance",
            "user": {"client_user_id": client_user_id},
            "country_codes": self.countries,
            "language": "en",
        }
        if access_token:
            body["access_token"] = access_token
        else:
            body["products"] = ["transactions"]
            body["transactions"] = {"days_requested": 730}
        return self._post("/link/token/create", body)["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        data = self._post("/item/public_token/exchange", {"public_token": public_token})
        return data["access_token"], data["item_id"]

    def sandbox_public_token(self, institution_id: str = SANDBOX_INSTITUTION) -> str:
        if self.env != "sandbox":
            raise PlaidError("INVALID_ENV", "Test banks are only available with PLAID_ENV=sandbox.")
        data = self._post(
            "/sandbox/public_token/create",
            {"institution_id": institution_id, "initial_products": ["transactions"]},
        )
        return data["public_token"]

    # -- Data -------------------------------------------------------------------------

    def get_accounts(self, access_token: str) -> list[dict]:
        return self._post("/accounts/get", {"access_token": access_token})["accounts"]

    def institution_name(self, access_token: str) -> str | None:
        try:
            item = self._post("/item/get", {"access_token": access_token})["item"]
            inst_id = item.get("institution_id")
            if not inst_id:
                return None
            inst = self._post(
                "/institutions/get_by_id",
                {"institution_id": inst_id, "country_codes": self.countries},
            )["institution"]
            return inst.get("name")
        except (PlaidError, KeyError):
            return None

    def sync_transactions(self, access_token: str, cursor: str | None) -> dict[str, Any]:
        """All changes since `cursor` (pages followed). Restarts the pass if Plaid reports the
        data changed mid-pagination, as Plaid recommends."""
        for _attempt in range(3):
            added, modified, removed = [], [], []
            next_cursor = cursor
            try:
                while True:
                    body: dict[str, Any] = {"access_token": access_token, "count": 500}
                    if next_cursor:
                        body["cursor"] = next_cursor
                    page = self._post("/transactions/sync", body)
                    added += page.get("added", [])
                    modified += page.get("modified", [])
                    removed += page.get("removed", [])
                    next_cursor = page.get("next_cursor")
                    if not page.get("has_more"):
                        break
                return {
                    "added": added,
                    "modified": modified,
                    "removed": removed,
                    "cursor": next_cursor,
                }
            except PlaidError as exc:
                if exc.code != "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                    raise
                log.info("Plaid data changed during sync; restarting the pass")
        raise PlaidError("SYNC_FAILED", "Plaid kept changing data during sync; try again shortly.")

    def remove_item(self, access_token: str) -> None:
        self._post("/item/remove", {"access_token": access_token})


def get_plaid(transport: httpx.BaseTransport | None = None) -> PlaidClient:
    return PlaidClient(transport=transport or _test_transport)


# Tests install a fake Plaid server here (see tests/fake_plaid.py).
_test_transport: httpx.BaseTransport | None = None


def plaid_configured() -> bool:
    s = get_settings()
    return bool(s.plaid_client_id and s.plaid_secret)
