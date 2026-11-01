from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import runtime, tracking
from ..db import get_db
from ..models import Package, RegistrationLog, Shipment, User
from ..security import hash_password
from ..track17 import Track17Error
from .auth import user_out
from .deps import admin_user
from .schemas import PackageCreated, PackageOut, SettingsPatch, UserCreate, UserOut, UserPatch

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [user_out(db, u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users", response_model=UserOut, status_code=201, summary="Create an account for a friend or family member")
def create_user(body: UserCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "That username is taken")
    u = User(username=body.username, password_hash=hash_password(body.password), is_admin=body.is_admin,
             monthly_new_limit=body.monthly_new_limit)
    db.add(u)
    db.flush()
    return user_out(db, u)


@router.patch("/users/{uid}", response_model=UserOut, summary="Reset password, change admin flag or monthly limit")
def patch_user(uid: int, body: UserPatch, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "No such user")
    if body.password:
        u.password_hash = hash_password(body.password)
    if body.is_admin is not None:
        if u.id == admin.id and not body.is_admin:
            raise HTTPException(400, "You cannot remove your own admin rights")
        u.is_admin = body.is_admin
    if body.clear_monthly_limit:
        u.monthly_new_limit = None
    elif body.monthly_new_limit is not None:
        u.monthly_new_limit = body.monthly_new_limit
    return user_out(db, u)


@router.delete("/users/{uid}", status_code=204, summary="Delete a user and their package list")
def delete_user(uid: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "No such user")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot delete yourself")
    db.delete(u)


@router.get("/quota", summary="17TRACK quota (live) plus this server's own usage")
def quota(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    live, err = None, None
    try:
        live = (tracking.get_client().getquota().get("data") or {})
        live = {k: live.get(k) for k in ("quota_total", "quota_used", "quota_remain", "today_used", "max_track_daily")}
    except Track17Error as e:
        err = str(e)
    per_user = db.execute(select(RegistrationLog.user_id, func.count(RegistrationLog.id))
                          .where(RegistrationLog.used_quota.is_(True)).group_by(RegistrationLog.user_id)).all()
    names = {u.id: u.username for u in db.scalars(select(User)).all()}
    return {
        "seventeen_track": live, "error": err,
        "server": {
            "shipments_total": db.scalar(select(func.count(Shipment.id))) or 0,
            "shipments_registered": db.scalar(select(func.count(Shipment.id)).where(Shipment.registered.is_(True))) or 0,
            "shipments_stopped": db.scalar(select(func.count(Shipment.id)).where(Shipment.tracking_stopped.is_(True))) or 0,
            "quota_used_by_this_server": db.scalar(select(func.count(RegistrationLog.id)).where(RegistrationLog.used_quota.is_(True))) or 0,
            "quota_used_by_user": {names.get(uid, "poller/unknown" if uid is None else f"deleted user {uid}"): n for uid, n in per_user},
            "packages_awaiting_approval": db.scalar(select(func.count(Package.id)).where(Package.tracking_mode == "awaiting_approval")) or 0,
        },
        "settings": runtime.all_(db),
    }


@router.get("/settings")
def get_settings(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return runtime.all_(db)


@router.patch("/settings", summary="Approval mode, per-user monthly limit, auto-archive days, sign-up")
def patch_settings(body: SettingsPatch, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_none=True).items():
        runtime.set_(db, k, v)
    db.flush()
    return runtime.all_(db)


@router.get("/approvals", response_model=list[PackageOut], summary="Packages waiting for approval")
def approvals(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Package).where(Package.tracking_mode == "awaiting_approval").order_by(Package.id)).all()
    return [PackageOut.of(p) for p in rows]


@router.post("/approvals/{pid}/approve", response_model=PackageCreated, summary="Approve: registers with 17TRACK (1 quota)")
def approve(pid: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(Package, pid)
    if not p or p.tracking_mode != "awaiting_approval":
        raise HTTPException(404, "No such pending package")
    # Run as the admin (bypasses limits) but log usage against the package owner.
    outcome = tracking.start_tracking(db, admin, p)
    for r in db.scalars(select(RegistrationLog).where(RegistrationLog.number == p.tracking_number,
                                                      RegistrationLog.user_id == admin.id)).all():
        r.user_id = p.user_id
    return PackageCreated(package=PackageOut.of(p, with_events=True), outcome=outcome)


@router.post("/approvals/{pid}/reject", response_model=PackageOut, summary="Reject: keep it saved but untracked")
def reject(pid: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    p = db.get(Package, pid)
    if not p or p.tracking_mode != "awaiting_approval":
        raise HTTPException(404, "No such pending package")
    p.tracking_mode, p.note = "rejected", "An admin declined tracking for this number."
    return PackageOut.of(p)


@router.post("/poll-now", summary="Run the background poller once right now")
def poll_now(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        return tracking.poll_once(db)
    except Track17Error as e:
        raise HTTPException(502, str(e)) from e


@router.post("/sync-account", summary="Import the list of numbers already on the 17TRACK account (free)")
def sync_account(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        return tracking.sync_account(db)
    except Track17Error as e:
        raise HTTPException(502, str(e)) from e


@router.get("/poller", summary="Last poll result")
def poller_status(_: User = Depends(admin_user)):
    return tracking.last_poll
