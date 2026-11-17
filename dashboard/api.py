"""Small HTTP client for the FastAPI backend (API_URL, default http://localhost:8000)."""

from __future__ import annotations

import os
from typing import Any

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

_client: httpx.Client | None = None


class APIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=API_URL, timeout=180)
    return _client


def set_client(c: httpx.Client | None) -> None:
    """Swap the transport (tests use FastAPI's TestClient)."""
    global _client
    _client = c


def _clean(params: dict | None) -> dict | None:
    if not params:
        return None
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in params.items()
        if v is not None
    }


def request(method: str, path: str, **kw) -> Any:
    try:
        r = client().request(method, path, **kw)
    except httpx.HTTPError as exc:
        raise APIError(f"Cannot reach the API at {API_URL} ({exc.__class__.__name__}).") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(str(d.get("msg", d)) for d in detail)
        raise APIError(str(detail), r.status_code)
    if r.status_code == 204 or not r.content:
        return None
    return r.json()


def get(path: str, **params) -> Any:
    return request("GET", path, params=_clean(params))


def post(path: str, json: Any = None, **kw) -> Any:
    return request("POST", path, json=json, **kw)


def patch(path: str, json: Any) -> Any:
    return request("PATCH", path, json=json)


def delete(path: str) -> Any:
    return request("DELETE", path)


def upload(path: str, file_name: str, content: bytes, mime: str, **form) -> Any:
    data = {
        k: str(v).lower() if isinstance(v, bool) else str(v)
        for k, v in form.items()
        if v is not None
    }
    return request("POST", path, files={"file": (file_name, content, mime)}, data=data)
