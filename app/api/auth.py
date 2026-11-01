from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, runtime, tracking
from ..db import get_db
from ..models import ApiToken, Package, User
from ..security import hash_password, issue_token, verify_password
from .deps import current_token, current_user
from .schemas import (LoginIn, NewApiToken, PasswordChange, SignupIn, TokenInfo, TokenOut,
                      UserOut)

router = APIRouter(tags=["auth"])


def user_out(db: Session, u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, is_admin=u.is_admin, monthly_new_limit=u.monthly_new_limit,
                   created_at=u.created_at, new_numbers_this_month=tracking.month_usage(db, u.id),
                   package_count=db.scalar(select(func.count(Package.id)).where(Package.user_id == u.id)) or 0)


@router.post("/auth/login", response_model=TokenOut, summary="Log in and get a session token")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    raw, row = issue_token(db, u, "session", body.device_name or "session", days=config.settings.session_days)
    return TokenOut(token=raw, id=row.id, kind=row.kind, name=row.name, expires_at=row.expires_at)


@router.post("/auth/signup", response_model=UserOut, status_code=201,
             summary="Create an account (only if the admin enabled sign-up)")
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if not runtime.get(db, "allow_signup"):
        raise HTTPException(403, "Sign-up is turned off on this server. Ask the admin for an account.")
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "That username is taken")
    u = User(username=body.username, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    return user_out(db, u)


@router.post("/auth/logout", status_code=204, summary="Revoke the token used for this request")
def logout(tok: ApiToken = Depends(current_token), db: Session = Depends(get_db)):
    db.delete(db.get(ApiToken, tok.id))


@router.get("/me", response_model=UserOut, summary="Who am I")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.post("/me/password", status_code=204, summary="Change my password (logs out other sessions)")
def change_password(body: PasswordChange, tok: ApiToken = Depends(current_token), db: Session = Depends(get_db)):
    u = db.get(User, tok.user_id)
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(400, "Current password is wrong")
    u.password_hash = hash_password(body.new_password)
    for t in db.scalars(select(ApiToken).where(ApiToken.user_id == u.id, ApiToken.kind == "session",
                                               ApiToken.id != tok.id)).all():
        db.delete(t)


@router.get("/tokens", response_model=list[TokenInfo], summary="List my sessions and API tokens")
def list_tokens(tok: ApiToken = Depends(current_token), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiToken).where(ApiToken.user_id == tok.user_id).order_by(ApiToken.id)).all()
    return [TokenInfo(id=r.id, kind=r.kind, name=r.name, prefix=r.prefix, created_at=r.created_at,
                      last_used_at=r.last_used_at, expires_at=r.expires_at, current=r.id == tok.id) for r in rows]


@router.post("/tokens", response_model=TokenOut, status_code=201,
             summary="Create a long-lived API token (for an app, a script, or Mira)")
def create_token(body: NewApiToken, user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw, row = issue_token(db, user, "api", body.name, days=body.days)
    return TokenOut(token=raw, id=row.id, kind=row.kind, name=row.name, expires_at=row.expires_at)


@router.delete("/tokens/{token_id}", status_code=204, summary="Revoke one of my tokens")
def delete_token(token_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(ApiToken, token_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "No such token")
    db.delete(row)
