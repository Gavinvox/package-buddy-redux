"""Core tracking logic: shared shipments, quota-safe registration, polling."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import carriers, config, runtime
from .models import ChangeLog, Package, RegistrationLog, Shipment, User, utcnow
from .security import aware
from .status import STATE_CODE, STATES, parse_iso, parse_track_info
from .track17 import (ALREADY_REGISTERED, CARRIER_POLICY_BLOCKED, NOT_REGISTERED, Track17Client,
                      Track17Error, chunks)

log = logging.getLogger("packagebuddy.tracking")

_client: Track17Client | None = None
poll_lock = threading.Lock()
last_poll: dict = {"started_at": None, "finished_at": None, "result": None, "error": None}


def get_client() -> Track17Client:
    global _client
    if _client is None:
        s = config.settings
        _client = Track17Client(s.track17_api_key, s.track17_base_url)
    return _client


def set_client(c) -> None:  # used by tests
    global _client
    _client = c


def normalize_number(n: str) -> str:
    return "".join(n.split()).upper()


# ------------------------------------------------------------------ helpers

def _log(db: Session, pkg: Package, kind: str, message: str, old: str | None = None, new: str | None = None):
    db.add(ChangeLog(user_id=pkg.user_id, package_id=pkg.id, tracking_number=pkg.tracking_number,
                     kind=kind, old_state=old, new_state=new, message=message))


def copy_to_package(db: Session, sh: Shipment, pkg: Package, log_changes: bool = True) -> None:
    old_state = pkg.state
    old_events = len(json.loads(pkg.events_json or "[]"))
    for f in ("state", "status_text", "carrier_name", "eta", "last_location", "last_event_time",
              "delivered_at", "days_in_transit", "events_json"):
        setattr(pkg, f, getattr(sh, f))
    if sh.carrier_code:
        pkg.carrier_code = sh.carrier_code
    pkg.status_code = STATE_CODE.get(sh.state, 0)
    if sh.state == "carrier_unsupported":
        pkg.note = carriers.LIMITED.get(sh.carrier_code or 0, sh.register_error or STATES["carrier_unsupported"])
    elif sh.register_error and not sh.registered:
        pkg.note = sh.register_error
    else:
        pkg.note = None
    pkg.updated_at = utcnow()
    if not log_changes:
        return
    new_events = len(json.loads(pkg.events_json or "[]"))
    if old_state == "pending":
        return  # first data for a newly added package: not worth a notification
    if old_state != pkg.state:
        extra = pkg.status_text if pkg.status_text and pkg.status_text != STATES.get(pkg.state) else ""
        _log(db, pkg, "status", f"{STATES.get(old_state, old_state)} -> {STATES.get(pkg.state, pkg.state)}"
             + (f": {extra}" if extra else ""), old_state, pkg.state)
    elif new_events > old_events:
        _log(db, pkg, "new_events", f"{new_events - old_events} new event(s): {pkg.status_text or ''}".strip(),
             old_state, pkg.state)


def _propagate(db: Session, sh: Shipment) -> None:
    for pkg in sh.packages:
        if pkg.tracking_mode == "tracked":
            copy_to_package(db, sh, pkg)


def apply_trackinfo(db: Session, sh: Shipment, item: dict) -> None:
    p = parse_track_info(item)
    sh.last_polled_at = utcnow()
    sh.last_error = None
    if p["carrier_code"]:
        sh.carrier_code = p["carrier_code"]
    if p["events_hash"] == sh.events_hash and sh.state == p["state"]:
        return
    sh.state = p["state"]
    sh.status_text = p["status_text"]
    sh.sub_status = p["sub_status"]
    sh.carrier_name = p["carrier_name"]
    sh.eta = p["eta"]
    sh.last_location = p["last_location"]
    sh.last_event_time = p["last_event_time"]
    sh.delivered_at = p["delivered_at"]
    sh.days_in_transit = p["days_in_transit"] or _days_between(sh.created_at, p)
    sh.events_json = json.dumps(p["events"])
    sh.events_hash = p["events_hash"]
    sh.updated_at = utcnow()
    _propagate(db, sh)


def _days_between(created: datetime, p: dict) -> int | None:
    evs = p["events"]
    if not evs:
        return None
    first = parse_iso(evs[-1].get("time_utc") or evs[-1].get("time"))
    end = parse_iso(p["delivered_at"]) or datetime.now(timezone.utc)
    if not first:
        return None
    return max(0, (end - first).days)


# ------------------------------------------------------------- registration

def month_usage(db: Session, user_id: int) -> int:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count(RegistrationLog.id)).where(
        RegistrationLog.user_id == user_id, RegistrationLog.used_quota.is_(True),
        RegistrationLog.created_at >= start)) or 0


def _limit_for(db: Session, user: User) -> int:
    return user.monthly_new_limit if user.monthly_new_limit is not None else runtime.get(db, "monthly_new_limit")


def get_or_create_shipment(db: Session, number: str, carrier_code: int | None) -> Shipment:
    sh = db.scalar(select(Shipment).where(Shipment.number == number))
    if sh is None:
        sh = Shipment(number=number, carrier_code=carrier_code, carrier_name=carriers.carrier_name(carrier_code))
        db.add(sh)
        db.flush()
    elif carrier_code and not sh.carrier_code:
        sh.carrier_code = carrier_code
    return sh


def start_tracking(db: Session, user: User, pkg: Package, register_now: bool = True) -> str:
    """Attach a package to its shared shipment and make sure 17TRACK tracks it.

    Returns a short outcome string: shared | registered | already_registered |
    awaiting_approval | limit_reached | queued | unsupported | rejected | error
    """
    sh = get_or_create_shipment(db, pkg.tracking_number, pkg.carrier_code)
    pkg.shipment_id = sh.id
    pkg.shipment = sh
    if sh.registered:
        pkg.tracking_mode = "tracked"
        if sh.tracking_stopped:
            _retrack(db, sh)
        if sh.last_polled_at is None:
            refresh_shipments(db, [sh])  # free
        copy_to_package(db, sh, pkg, log_changes=False)
        return "shared"

    if not user.is_admin:
        if runtime.get(db, "require_approval"):
            pkg.tracking_mode = "awaiting_approval"
            pkg.note = "Waiting for an admin to approve tracking (uses 1 of the shared 17TRACK quota)."
            return "awaiting_approval"
        limit = _limit_for(db, user)
        if limit and month_usage(db, user.id) >= limit:
            pkg.tracking_mode = "awaiting_approval"
            pkg.note = f"Monthly limit of {limit} new tracking numbers reached; an admin can approve it."
            return "limit_reached"

    pkg.tracking_mode = "tracked"
    if not register_now:
        pkg.note = "Queued; it will be registered with 17TRACK on the next poll."
        return "queued"
    res = register_shipments(db, [sh], user.id)
    outcome = res.get(sh.id, "error")
    if sh.registered:
        refresh_shipments(db, [sh])
    copy_to_package(db, sh, pkg, log_changes=False)
    return outcome


def register_shipments(db: Session, shipments: list[Shipment], user_id: int | None) -> dict[int, str]:
    client = get_client()
    out: dict[int, str] = {}
    if config.settings.disable_registration:
        for s in shipments:
            s.last_error = "Not registered: DISABLE_REGISTRATION is on for this server."
            out[s.id] = "registration_disabled"
        return out
    for batch in chunks(shipments):
        by_num = {s.number: s for s in batch}
        now = utcnow()
        for s in batch:
            s.last_register_attempt_at = now
        try:
            resp = client.register([(s.number, s.carrier_code) for s in batch])
        except Track17Error as e:
            for s in batch:
                s.last_error = str(e)
                out[s.id] = "error"
            continue
        data = resp.get("data") or {}
        for a in data.get("accepted") or []:
            s = by_num.get(normalize_number(a.get("number", "")))
            if not s:
                continue
            s.registered, s.registered_at, s.used_quota = True, now, True
            s.registered_by_user_id = user_id
            s.register_error = s.register_error_code = None
            if a.get("carrier"):
                s.carrier_code = a["carrier"]
                s.carrier_name = carriers.carrier_name(a["carrier"])
            db.add(RegistrationLog(user_id=user_id, number=s.number, carrier_code=s.carrier_code,
                                   result="accepted", used_quota=True))
            out[s.id] = "registered"
        for r in data.get("rejected") or []:
            s = by_num.get(normalize_number(r.get("number", "")))
            if not s:
                continue
            err = r.get("error") or {}
            code, msg = err.get("code"), err.get("message") or ""
            if code == ALREADY_REGISTERED:
                s.registered, s.registered_at = True, now
                s.register_error = s.register_error_code = None
                db.add(RegistrationLog(user_id=user_id, number=s.number, carrier_code=s.carrier_code,
                                       result="already", used_quota=False, message=msg))
                out[s.id] = "already_registered"
                continue
            s.register_error, s.register_error_code = f"17TRACK error {code}: {msg}", code
            policy = code == CARRIER_POLICY_BLOCKED or "not supported" in msg.lower()
            s.state = "carrier_unsupported" if policy else "not_found"
            s.status_text = STATES[s.state]
            db.add(RegistrationLog(user_id=user_id, number=s.number, carrier_code=s.carrier_code,
                                   result="rejected", used_quota=False, message=msg))
            out[s.id] = "unsupported" if policy else "rejected"
            _propagate(db, s)
    return out


def refresh_shipments(db: Session, shipments: list[Shipment]) -> int:
    """gettrackinfo in batches of 40. Free (does not use quota). Returns how many were updated."""
    client = get_client()
    n = 0
    for batch in chunks([s for s in shipments if s.registered]):
        by_num = {s.number: s for s in batch}
        try:
            resp = client.gettrackinfo([(s.number, s.carrier_code) for s in batch])
        except Track17Error as e:
            for s in batch:
                s.last_error = str(e)
            continue
        data = resp.get("data") or {}
        for a in data.get("accepted") or []:
            s = by_num.get(normalize_number(a.get("number", "")))
            if s:
                apply_trackinfo(db, s, a)
                n += 1
        for r in data.get("rejected") or []:
            s = by_num.get(normalize_number(r.get("number", "")))
            if not s:
                continue
            err = r.get("error") or {}
            s.last_error = f"17TRACK error {err.get('code')}: {err.get('message')}"
            s.last_polled_at = utcnow()
            if err.get("code") == NOT_REGISTERED:
                # Removed on the 17TRACK side; the next poll re-registers it
                # (17TRACK answers "already registered" without charging if it still exists).
                s.registered = False
    return n


def _retrack(db: Session, sh: Shipment) -> None:
    if sh.retracked:
        sh.last_error = "Tracking was stopped and 17TRACK allows restarting a number only once; showing the last known data."
        return
    try:
        get_client().retrack([(sh.number, sh.carrier_code)])
        sh.tracking_stopped = False
        sh.retracked = True
    except Track17Error as e:
        sh.last_error = str(e)


def on_unarchive(db: Session, pkg: Package) -> None:
    if pkg.shipment and pkg.shipment.tracking_stopped and pkg.tracking_mode == "tracked":
        _retrack(db, pkg.shipment)


def stop_finished(db: Session) -> int:
    """Stop 17TRACK updates for shipments nobody needs any more.

    Only numbers this server registered itself (used_quota) are ever stopped. Numbers that were
    already on the shared 17TRACK account (added by Mira or someone else, learned via
    sync_account or an "already registered" answer) are left alone, because stopping them would
    also stop them for the other user of the account."""
    cands = db.scalars(select(Shipment).where(Shipment.registered.is_(True),
                                              Shipment.tracking_stopped.is_(False),
                                              Shipment.used_quota.is_(True))).all()
    done = []
    for sh in cands:
        tracked = [p for p in sh.packages if p.tracking_mode == "tracked"]
        if not tracked:
            done.append(sh)
        elif all(p.archived for p in tracked) and sh.state in ("delivered", "expired"):
            done.append(sh)
    client = get_client()
    for batch in chunks(done):
        try:
            client.stoptrack([(s.number, s.carrier_code) for s in batch])
            for s in batch:
                s.tracking_stopped = True
        except Track17Error as e:
            log.warning("stoptrack failed: %s", e)
    return len(done)


def auto_archive(db: Session) -> int:
    days = runtime.get(db, "auto_archive_days")
    if days is None or days < 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    n = 0
    for pkg in db.scalars(select(Package).where(Package.archived.is_(False), Package.state == "delivered")).all():
        when = parse_iso(pkg.delivered_at) or aware(pkg.updated_at)
        if when and when <= cutoff:
            pkg.archived, pkg.archived_at = True, utcnow()
            _log(db, pkg, "archived", f"Moved to History {days} day(s) after delivery.", pkg.state, pkg.state)
            n += 1
    return n


def _needs_registration(db: Session) -> list[Shipment]:
    retry = timedelta(hours=config.settings.retry_unsupported_hours)
    now = datetime.now(timezone.utc)
    out = []
    for sh in db.scalars(select(Shipment).where(Shipment.registered.is_(False))).all():
        if not any(p.tracking_mode == "tracked" and not p.archived for p in sh.packages):
            continue
        last = aware(sh.last_register_attempt_at)
        if last is None:
            out.append(sh)
        elif sh.state == "carrier_unsupported" and now - last >= retry:
            out.append(sh)
        elif sh.register_error is None and now - last >= timedelta(minutes=30):
            out.append(sh)  # earlier network error or removed on 17TRACK side
    return out


def _needs_refresh(db: Session) -> list[Shipment]:
    out = []
    for sh in db.scalars(select(Shipment).where(Shipment.registered.is_(True),
                                                Shipment.tracking_stopped.is_(False))).all():
        if any(p.tracking_mode == "tracked" and not p.archived for p in sh.packages):
            out.append(sh)
    return out


def sync_account(db: Session, max_pages: int = 50) -> dict:
    """Learn which numbers are already registered on the 17TRACK account (for example by
    Mira's tool), so adding them here never calls `register` at all. Free."""
    client = get_client()
    seen = new = 0
    page = 1
    while page <= max_pages:
        resp = client.gettracklist(page_no=page)
        for it in (resp.get("data") or {}).get("accepted") or []:
            number = normalize_number(str(it.get("number") or ""))
            if not number:
                continue
            seen += 1
            sh = db.scalar(select(Shipment).where(Shipment.number == number))
            if sh is None:
                sh = Shipment(number=number)
                db.add(sh)
                new += 1
            if not sh.registered:
                sh.registered, sh.registered_at = True, utcnow()
                sh.register_error = sh.register_error_code = None
            if it.get("carrier"):
                sh.carrier_code = it["carrier"]
                sh.carrier_name = sh.carrier_name or carriers.carrier_name(it["carrier"])
            sh.tracking_stopped = str(it.get("tracking_status") or "").lower() == "stopped"
        pg = resp.get("page") or {}
        if not pg.get("has_next"):
            break
        page += 1
    db.flush()
    return {"numbers_on_account": seen, "new_to_server": new}


def poll_once(db: Session) -> dict:
    with poll_lock:
        last_poll["started_at"] = utcnow().isoformat()
        result: dict = {}
        try:
            regs = _needs_registration(db)
            result["registered"] = list(register_shipments(db, regs, None).values()) if regs else []
            db.flush()
            result["refreshed"] = refresh_shipments(db, _needs_refresh(db))
            db.flush()
            result["auto_archived"] = auto_archive(db)
            db.flush()
            result["stopped"] = stop_finished(db)
            last_poll["error"] = None
        except Exception as e:  # noqa: BLE001
            log.exception("poll failed")
            last_poll["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            last_poll["finished_at"] = utcnow().isoformat()
            last_poll["result"] = result
        return result


class Poller(threading.Thread):
    def __init__(self, interval_minutes: int):
        super().__init__(daemon=True, name="packagebuddy-poller")
        self.interval = interval_minutes * 60
        self._halt = threading.Event()

    def run(self):
        from .db import session_scope
        self._halt.wait(15)  # let the server finish starting
        if get_client().configured:
            try:
                with session_scope() as db:
                    log.info("17TRACK account sync: %s", sync_account(db))
            except Exception as e:  # noqa: BLE001
                log.warning("17TRACK account sync failed: %s", e)
        while not self._halt.is_set():
            if get_client().configured:
                try:
                    with session_scope() as db:
                        r = poll_once(db)
                    log.info("poll done: %s", r)
                except Exception:  # noqa: BLE001
                    pass
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
