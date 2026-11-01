from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import carriers, config, tracking
from ..db import get_db
from ..models import ChangeLog, Package, User, utcnow
from ..security import aware
from ..track17 import Track17Error
from .deps import current_user
from .schemas import (ChangeOut, EventOut, PackageCreate, PackageCreated, PackageOut,
                      PackagePatch)

router = APIRouter(tags=["packages"])


def _own(db: Session, user: User, pid: int) -> Package:
    p = db.get(Package, pid)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "No such package")
    return p


def _resolve(carrier) -> Optional[int]:
    try:
        return carriers.resolve(carrier)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/packages", response_model=list[PackageOut], summary="List my packages")
def list_packages(
    view: Literal["active", "history", "all"] = Query("active", description="active = main list, history = archived"),
    direction: Optional[Literal["receiving", "sending"]] = None,
    q: Optional[str] = Query(None, description="Search number or description"),
    state: Optional[str] = None,
    sort: Literal["newest", "oldest", "status", "description", "carrier"] = "newest",
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Package).where(Package.user_id == user.id)
    if view == "active":
        stmt = stmt.where(Package.archived.is_(False))
    elif view == "history":
        stmt = stmt.where(Package.archived.is_(True))
    if direction:
        stmt = stmt.where(Package.direction == direction)
    if state:
        stmt = stmt.where(Package.state == state)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Package.tracking_number.ilike(like), Package.description.ilike(like)))
    order = {"newest": Package.id.desc(), "oldest": Package.id.asc(), "status": Package.status_code.asc(),
             "description": Package.description.asc(), "carrier": Package.carrier_name.asc()}[sort]
    return [PackageOut.of(p) for p in db.scalars(stmt.order_by(order)).all()]


@router.post("/packages", response_model=PackageCreated, status_code=201, summary="Add a package")
def create_package(body: PackageCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    number = tracking.normalize_number(body.tracking_number)
    if db.scalar(select(Package).where(Package.user_id == user.id, Package.tracking_number == number)):
        raise HTTPException(409, "You already have this tracking number in your list")
    code = _resolve(body.carrier)
    if code is None:
        code = carriers.detect(number)
    p = Package(user_id=user.id, tracking_number=number, carrier_code=code,
                carrier_name=carriers.carrier_name(code), description=body.description,
                direction=body.direction, tracking_mode="not_tracked", source="api")
    db.add(p)
    db.flush()
    outcome = "saved"
    if body.track:
        outcome = tracking.start_tracking(db, user, p)
    db.flush()
    db.refresh(p)
    return PackageCreated(package=PackageOut.of(p, with_events=True), outcome=outcome)


@router.post("/packages/refresh", summary="Check all my active tracked packages now (free, batched; never registers)")
def refresh_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pkgs = db.scalars(select(Package).where(Package.user_id == user.id, Package.archived.is_(False),
                                            Package.tracking_mode == "tracked")).all()
    cool = config.settings.refresh_cooldown_seconds
    now = datetime.now(timezone.utc)
    seen, due = set(), []
    for p in pkgs:
        sh = p.shipment
        if sh is None or sh.id in seen or not sh.registered or sh.tracking_stopped:
            continue
        seen.add(sh.id)
        last = aware(sh.last_polled_at)
        if last is None or (now - last).total_seconds() >= cool:
            due.append(sh)
    try:
        n = tracking.refresh_shipments(db, due) if due else 0
    except Track17Error as e:
        raise HTTPException(502, str(e)) from e
    return {"refreshed": n, "checked": len(due), "skipped_recent": len(seen) - len(due)}


@router.get("/packages/{pid}", response_model=PackageOut, summary="One package, with events")
def get_package(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return PackageOut.of(_own(db, user, pid), with_events=True)


@router.get("/packages/{pid}/events", response_model=list[EventOut], summary="Tracking events, newest first")
def get_events(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return PackageOut.of(_own(db, user, pid), with_events=True).events or []


@router.patch("/packages/{pid}", response_model=PackageOut, summary="Edit description/direction, archive or restore")
def patch_package(pid: int, body: PackagePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    if body.description is not None:
        p.description = body.description
    if body.direction is not None:
        p.direction = body.direction
    if body.carrier is not None:
        if p.shipment and p.shipment.registered:
            raise HTTPException(409, "This number is already tracked by 17TRACK; its carrier cannot be changed here yet.")
        p.carrier_code = _resolve(body.carrier)
        p.carrier_name = carriers.carrier_name(p.carrier_code)
        if p.shipment and not p.shipment.registered:
            p.shipment.carrier_code = p.carrier_code
    if body.archived is not None and body.archived != p.archived:
        p.archived = body.archived
        p.archived_at = utcnow() if body.archived else None
        if not body.archived:
            tracking.on_unarchive(db, p)
    p.updated_at = utcnow()
    return PackageOut.of(p, with_events=True)


@router.delete("/packages/{pid}", status_code=204, summary="Delete a package from my list")
def delete_package(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    db.delete(p)
    db.flush()
    # If nobody else uses the number, the poller stops it at 17TRACK (stoptrack, not delete).


@router.post("/packages/{pid}/track", response_model=PackageCreated,
             summary="Start tracking an imported/saved package (may use 1 quota)")
def track_package(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    if p.tracking_mode == "tracked" and p.shipment and p.shipment.registered:
        return PackageCreated(package=PackageOut.of(p, with_events=True), outcome="shared")
    outcome = tracking.start_tracking(db, user, p)
    return PackageCreated(package=PackageOut.of(p, with_events=True), outcome=outcome)


@router.post("/packages/{pid}/refresh", response_model=PackageOut, summary="Check 17TRACK for this package now (free)")
def refresh_package(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    sh = p.shipment
    if p.tracking_mode != "tracked" or sh is None:
        raise HTTPException(409, f"This package is not being tracked (mode: {p.tracking_mode}). Use POST /packages/{pid}/track first.")
    if not sh.registered:
        tracking.start_tracking(db, user, p)
        return PackageOut.of(p, with_events=True)
    last = aware(sh.last_polled_at)
    cool = config.settings.refresh_cooldown_seconds
    if last and (datetime.now(timezone.utc) - last).total_seconds() < cool:
        return PackageOut.of(p, with_events=True)
    try:
        tracking.refresh_shipments(db, [sh])
    except Track17Error as e:
        raise HTTPException(502, str(e)) from e
    if sh.last_error and p.tracking_mode == "tracked":
        p.note = sh.last_error
    return PackageOut.of(p, with_events=True)


@router.get("/changes/latest", summary="Newest change id (start notification polling from here)")
def changes_latest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from sqlalchemy import func
    latest = db.scalar(select(func.max(ChangeLog.id)).where(ChangeLog.user_id == user.id)) or 0
    return {"latest_id": latest, "poll_interval_minutes": config.settings.poll_interval_minutes}


@router.get("/changes", response_model=list[ChangeOut], summary="Change log for notifications (poll with since_id)")
def changes(since_id: int = 0, limit: int = Query(100, le=500), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    rows = db.scalars(select(ChangeLog).where(ChangeLog.user_id == user.id, ChangeLog.id > since_id)
                      .order_by(ChangeLog.id).limit(limit)).all()
    return [ChangeOut(id=r.id, package_id=r.package_id, tracking_number=r.tracking_number, kind=r.kind,
                      old_state=r.old_state, new_state=r.new_state, message=r.message, created_at=r.created_at)
            for r in rows]
