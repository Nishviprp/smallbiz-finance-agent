from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session_factory
from ..services import auth as auth_svc
from ..services.business import COUNTRIES, get_profile, update_profile
from .deps import bearer_token, get_tenant_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _plain_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def _accounts_only() -> None:
    if get_settings().auth_mode != "accounts":
        raise HTTPException(404, "Accounts are disabled (AUTH_MODE=local).")


class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    name: str = Field(default="", max_length=120)
    business_name: str = Field(min_length=1, max_length=120)
    country: str = "US"


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


def _login_out(r: auth_svc.LoginResult) -> dict:
    return {
        "token": r.token,
        "expires_at": r.expires_at,
        "user": {"id": r.user.id, "email": r.user.email, "name": r.user.name},
        "business": {"id": r.business.id, "name": r.business.name},
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: Session = Depends(_plain_db)):
    """Create an account + a new business with its own private books."""
    _accounts_only()
    if body.country not in COUNTRIES:
        raise HTTPException(422, f"Unknown country '{body.country}'")
    try:
        result = auth_svc.signup(db, body.email, body.password, body.name, body.business_name)
    except auth_svc.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Business profile from the sign-up form (country presets: currency, dates, tax year).
    preset = {k: v for k, v in COUNTRIES[body.country].items() if k != "name"}
    db.info["business_id"] = result.business.id
    update_profile(db, {"business_name": body.business_name, "country": body.country, **preset})
    return _login_out(result)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(_plain_db)):
    _accounts_only()
    try:
        return _login_out(auth_svc.login(db, body.email, body.password))
    except auth_svc.RateLimited as exc:
        raise HTTPException(429, str(exc)) from exc
    except auth_svc.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(_plain_db)):
    token = bearer_token(request)
    if token:
        auth_svc.logout(db, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(request: Request, db: Session = Depends(get_tenant_db)):
    """Who is logged in, which business, and its profile."""
    user = request.state.user
    biz = request.state.business
    return {
        "auth_mode": get_settings().auth_mode,
        "user": {"id": user.id, "email": user.email, "name": user.name} if user else None,
        "business": {"id": biz.id, "name": biz.name},
        "profile": get_profile(db).as_dict(),
    }


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordIn, request: Request, db: Session = Depends(get_tenant_db)):
    _accounts_only()
    user = db.merge(request.state.user)
    try:
        auth_svc.change_password(db, user, body.current_password, body.new_password)
    except auth_svc.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
