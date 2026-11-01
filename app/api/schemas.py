from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import carriers
from ..models import Package
from ..status import STATES


class LoginIn(BaseModel):
    username: str
    password: str
    device_name: str = Field("", description="Shown in your token list, e.g. 'Pixel phone'")


class TokenOut(BaseModel):
    token: str = Field(description="Shown only once. Send as 'Authorization: Bearer <token>'.")
    id: int
    kind: str
    name: str
    expires_at: Optional[datetime]


class TokenInfo(BaseModel):
    id: int
    kind: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    current: bool = False


class NewApiToken(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Mira (Open WebUI)"])
    days: Optional[int] = Field(None, ge=1, description="Leave empty for a token that never expires")


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    monthly_new_limit: Optional[int]
    created_at: datetime
    new_numbers_this_month: int = 0
    package_count: int = 0


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(..., min_length=8, max_length=200)
    is_admin: bool = False
    monthly_new_limit: Optional[int] = Field(None, ge=0, description="Per-user override; 0 = unlimited")


class SignupIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(..., min_length=8, max_length=200)


class UserPatch(BaseModel):
    password: Optional[str] = Field(None, min_length=8, max_length=200)
    is_admin: Optional[bool] = None
    monthly_new_limit: Optional[int] = Field(None, ge=0)
    clear_monthly_limit: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=200)


class PackageCreate(BaseModel):
    tracking_number: str = Field(..., min_length=3, max_length=64)
    carrier: Optional[str | int] = Field(None, description="Name ('ups', 'royal mail'), 17TRACK code, or empty to auto-detect")
    description: str = Field("", max_length=500)
    direction: Literal["receiving", "sending"] = "receiving"
    track: bool = Field(True, description="Register with 17TRACK now (may use 1 of the shared quota). False = just save it.")


class PackagePatch(BaseModel):
    description: Optional[str] = Field(None, max_length=500)
    direction: Optional[Literal["receiving", "sending"]] = None
    archived: Optional[bool] = None
    carrier: Optional[str | int] = Field(None, description="Only changes the local label for untracked packages")


class EventOut(BaseModel):
    time: Optional[str]
    time_utc: Optional[str] = None
    description: str = ""
    location: Optional[str] = None
    stage: Optional[str] = None
    sub_status: Optional[str] = None
    carrier: Optional[str] = None


class PackageOut(BaseModel):
    id: int
    tracking_number: str
    carrier_code: Optional[int]
    carrier_name: Optional[str]
    description: str
    direction: str
    archived: bool
    tracking_mode: str
    state: str
    state_label: str
    status_text: Optional[str]
    status_code: int
    eta: Optional[str]
    last_location: Optional[str]
    last_event_time: Optional[str]
    delivered_at: Optional[str]
    days_in_transit: Optional[int]
    event_count: int
    note: Optional[str]
    carrier_limited: bool
    carrier_site_url: str
    source: str
    created_at: datetime
    updated_at: datetime
    last_checked_at: Optional[datetime] = None
    events: Optional[list[EventOut]] = None

    @classmethod
    def of(cls, p: Package, with_events: bool = False) -> "PackageOut":
        evs = json.loads(p.events_json or "[]")
        code = p.carrier_code or carriers.detect(p.tracking_number, strong_only=False)
        return cls(
            id=p.id, tracking_number=p.tracking_number, carrier_code=p.carrier_code,
            carrier_name=p.carrier_name or carriers.carrier_name(p.carrier_code),
            description=p.description, direction=p.direction, archived=p.archived,
            tracking_mode=p.tracking_mode, state=p.state, state_label=STATES.get(p.state, p.state),
            status_text=p.status_text, status_code=p.status_code, eta=p.eta, last_location=p.last_location,
            last_event_time=p.last_event_time, delivered_at=p.delivered_at, days_in_transit=p.days_in_transit,
            event_count=len(evs), note=p.note, carrier_limited=(code or 0) in carriers.LIMITED,
            carrier_site_url=carriers.site_url(code, p.tracking_number), source=p.source,
            created_at=p.created_at, updated_at=p.updated_at,
            last_checked_at=p.shipment.last_polled_at if p.shipment else None,
            events=[EventOut(**e) for e in evs] if with_events else None,
        )


class PackageCreated(BaseModel):
    package: PackageOut
    outcome: str = Field(description="shared | registered | already_registered | awaiting_approval | limit_reached | unsupported | rejected | error | saved")


class ChangeOut(BaseModel):
    id: int
    package_id: Optional[int]
    tracking_number: str
    kind: str
    old_state: Optional[str]
    new_state: Optional[str]
    message: str
    created_at: datetime


class SettingsPatch(BaseModel):
    require_approval: Optional[bool] = None
    monthly_new_limit: Optional[int] = Field(None, ge=0)
    auto_archive_days: Optional[int] = Field(None, ge=0, le=365)
    allow_signup: Optional[bool] = None
