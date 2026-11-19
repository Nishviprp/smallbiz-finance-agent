"""Encryption at rest for secrets such as bank access tokens (Fernet: AES-128-CBC + HMAC).

The key comes from ENCRYPTION_KEY, or is generated once into data/secret.key (owner-only file
permissions). Back that file up with your database: without it, bank links must be redone.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


class DecryptionError(RuntimeError):
    pass


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.encryption_key:
        return Fernet(s.encryption_key.encode())
    path = s.secret_key_file
    if path.exists():
        return Fernet(path.read_bytes().strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Cannot decrypt a stored bank token — the encryption key changed. "
            "Restore data/secret.key (or ENCRYPTION_KEY), or reconnect the bank."
        ) from exc


def reset_cache() -> None:
    _fernet.cache_clear()
