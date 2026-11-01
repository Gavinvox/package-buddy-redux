"""Admin-changeable settings stored in the database (env vars give defaults)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import config
from .models import Setting

KEYS = {
    "require_approval": bool,
    "monthly_new_limit": int,
    "auto_archive_days": int,
    "allow_signup": bool,
}


def _default(key: str):
    s = config.settings
    return {"require_approval": s.require_approval, "monthly_new_limit": s.monthly_new_limit,
            "auto_archive_days": s.auto_archive_days, "allow_signup": s.allow_signup}[key]


def get(db: Session, key: str):
    row = db.get(Setting, key)
    if row is None:
        return _default(key)
    t = KEYS[key]
    if t is bool:
        return row.value == "1"
    return int(row.value)


def set_(db: Session, key: str, value) -> None:
    if key not in KEYS:
        raise KeyError(key)
    v = ("1" if value else "0") if KEYS[key] is bool else str(int(value))
    row = db.get(Setting, key)
    if row:
        row.value = v
    else:
        db.add(Setting(key=key, value=v))


def all_(db: Session) -> dict:
    return {k: get(db, k) for k in KEYS}
