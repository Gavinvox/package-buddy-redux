"""Password hashing (argon2id) and opaque bearer tokens (stored as SHA-256)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApiToken, User

_ph = PasswordHasher()
TOKEN_PREFIX = "pb_"


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def issue_token(db: Session, user: User, kind: str, name: str = "", days: int | None = None) -> tuple[str, ApiToken]:
    raw = TOKEN_PREFIX + ("s_" if kind == "session" else "a_") + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=days) if days else None
    row = ApiToken(user_id=user.id, kind=kind, name=name[:100], token_hash=_hash_token(raw),
                   prefix=raw[:10], expires_at=expires)
    db.add(row)
    db.flush()
    return raw, row


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lookup_token(db: Session, raw: str) -> ApiToken | None:
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == _hash_token(raw)))
    if not row:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at and aware(row.expires_at) < now:
        return None
    if not row.last_used_at or (now - aware(row.last_used_at)).total_seconds() > 300:
        row.last_used_at = now.replace(microsecond=0)
    # Sliding sessions: an app login that is still being used (for example by the phone's
    # background notification check) is extended instead of expiring mid-use.
    if row.kind == "session" and row.expires_at:
        from . import config  # local import: avoids an import cycle
        days = config.settings.session_days
        if days and (aware(row.expires_at) - now) < timedelta(days=days / 2):
            row.expires_at = (now + timedelta(days=days)).replace(microsecond=0)
    return row
