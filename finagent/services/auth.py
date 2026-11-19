"""Accounts: password hashing, login sessions, sign-up.

* Passwords: scrypt (memory-hard, Python standard library) with a random salt per user.
* Sessions: random 256-bit tokens; only their SHA-256 hash is stored, so a database leak does
  not reveal usable tokens. Sessions expire (SESSION_DAYS) and can be revoked (logout).
* Brute force: a small in-memory limiter blocks an email after repeated failures.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import scope_session
from ..models import AuthSession, Business, Membership, User
from .seed import seed_defaults

_N, _R, _P = 2**14, 8, 1
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


class AuthError(ValueError):
    pass


class RateLimited(AuthError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def _utcnow() -> dt.datetime:
    """Naive UTC (stored that way in SQLite and Postgres TIMESTAMP columns)."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Please enter a valid email address.")
    return email


def check_password_strength(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > 256:
        raise AuthError("Password is too long.")


# ---- brute-force limiter ------------------------------------------------------


class _Limiter:
    def __init__(self, max_failures: int = 5, window_s: int = 15 * 60):
        self.max, self.window = max_failures, window_s
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._fails[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                raise RateLimited("Too many failed attempts. Please wait 15 minutes and try again.")

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._fails.clear()
            else:
                self._fails.pop(key, None)


limiter = _Limiter()


# ---- business / user creation -------------------------------------------------


def create_business(db: Session, name: str) -> Business:
    """Create a business with its default categories. `db` may be unscoped."""
    biz = Business(name=(name or "My Business").strip()[:120] or "My Business")
    db.add(biz)
    db.flush()
    previous = db.info.get("business_id")
    scope_session(db, biz.id)
    try:
        seed_defaults(db)
    finally:
        if previous is None:
            db.info.pop("business_id", None)
        else:
            db.info["business_id"] = previous
    return biz


@dataclass
class LoginResult:
    token: str
    user: User
    business: Business
    expires_at: dt.datetime


def _new_session(db: Session, user: User, business: Business) -> LoginResult:
    token = secrets.token_urlsafe(32)
    expires = _utcnow() + dt.timedelta(days=get_settings().session_days)
    db.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            business_id=business.id,
            expires_at=expires,
        )
    )
    user.last_login_at = _utcnow()
    db.commit()
    return LoginResult(token, user, business, expires)


def signup(db: Session, email: str, password: str, name: str, business_name: str) -> LoginResult:
    if not get_settings().allow_signup:
        raise AuthError("Sign-up is disabled on this server.")
    email = normalize_email(email)
    check_password_strength(password)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AuthError("An account with this email already exists. Please log in.")
    user = User(email=email, name=(name or "").strip()[:120], password_hash=hash_password(password))
    db.add(user)
    db.flush()
    biz = create_business(db, business_name)
    db.add(Membership(user_id=user.id, business_id=biz.id, role="owner"))
    db.flush()
    return _new_session(db, user, biz)


def login(db: Session, email: str, password: str) -> LoginResult:
    key = (email or "").strip().lower()
    limiter.check(key)
    user = db.scalar(select(User).where(User.email == key))
    if user is None or not verify_password(password or "", user.password_hash):
        limiter.fail(key)
        raise AuthError("Email or password is incorrect.")
    limiter.reset(key)
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
    )
    if membership is None:
        raise AuthError("This account is not linked to a business.")
    return _new_session(db, user, db.get(Business, membership.business_id))


def resolve(db: Session, token: str) -> tuple[User, Business] | None:
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if s is None or s.expires_at < _utcnow():
        return None
    user = db.get(User, s.user_id)
    biz = db.get(Business, s.business_id)
    if user is None or biz is None:
        return None
    still_member = db.scalar(
        select(Membership.id).where(Membership.user_id == user.id, Membership.business_id == biz.id)
    )
    return (user, biz) if still_member else None


def logout(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    db.commit()


def change_password(db: Session, user: User, old: str, new: str) -> None:
    if not verify_password(old, user.password_hash):
        raise AuthError("Current password is incorrect.")
    check_password_strength(new)
    user.password_hash = hash_password(new)
    # Sign out everywhere else.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()


def set_password(db: Session, email: str, new: str) -> None:
    """Admin reset (CLI)."""
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise AuthError("No user with that email.")
    check_password_strength(new)
    user.password_hash = hash_password(new)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()


# ---- local (single-business, no login) mode -----------------------------------


def local_business(db: Session) -> Business:
    """The one business used when AUTH_MODE=local; created on first use."""
    biz = db.scalar(select(Business).order_by(Business.id))
    if biz is None:
        biz = create_business(db, get_settings().business_name)
        db.commit()
    return biz
