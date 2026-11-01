"""Database tables.

Design notes
- `Shipment` is one tracking number as known to 17TRACK, shared by every user
  who tracks it. That is how a number is registered (and paid for) only once.
- `Package` is one user's entry in their list. It points at a Shipment (or at
  nothing, for imported history that is not tracked) and holds a copy of the
  display fields so each user's list can be read without joins.
- `ChangeLog` records every state/status change per package; clients and the
  future notification service read it with `GET /api/v1/changes?since_id=`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_new_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = use global setting
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")
    packages = relationship("Package", back_populates="user", cascade="all, delete-orphan")


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    kind: Mapped[str] = mapped_column(String(16), default="session")  # session | api
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(12), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="tokens")


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    carrier_code: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 17TRACK carrier key
    # 17TRACK bookkeeping
    registered: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    register_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    register_error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_register_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    retracked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Normalized tracking state (copied to packages)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eta: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_event_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    days_in_transit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    events_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    packages = relationship("Package", back_populates="shipment")


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = (UniqueConstraint("user_id", "tracking_number", name="uq_user_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True)
    tracking_number: Mapped[str] = mapped_column(String(64))
    carrier_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(10), default="receiving")  # receiving | sending
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # tracking_mode: tracked | awaiting_approval | not_tracked | rejected
    tracking_mode: Mapped[str] = mapped_column(String(24), default="tracked")
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual | import_xml | import_db | api
    # Display copy of the shipment state
    state: Mapped[str] = mapped_column(String(32), default="pending")
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=0)  # Package Buddy-style numeric code
    carrier_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eta: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_event_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    days_in_transit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="packages")
    shipment = relationship("Shipment", back_populates="packages")


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id", ondelete="SET NULL"), nullable=True, index=True)
    tracking_number: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))  # status | new_events | archived | registered | error
    old_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegistrationLog(Base):
    """One row per 17TRACK register call result, for quota accounting."""
    __tablename__ = "registration_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    number: Mapped[str] = mapped_column(String(64))
    carrier_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(24))  # accepted | already | rejected
    used_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
