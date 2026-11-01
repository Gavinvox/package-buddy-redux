from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiToken, User
from ..security import lookup_token

bearer = HTTPBearer(auto_error=False, description="Session token from /auth/login or an API token from /tokens")


def current_token(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> ApiToken:
    raw = creds.credentials if creds else request.headers.get("X-API-Key", "")
    tok = lookup_token(db, raw)
    if not tok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid token",
                            headers={"WWW-Authenticate": "Bearer"})
    return tok


def current_user(tok: ApiToken = Depends(current_token)) -> User:
    return tok.user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
