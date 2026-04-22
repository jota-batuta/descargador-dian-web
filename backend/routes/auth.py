"""Auth routes: register, login, logout."""

from __future__ import annotations

import asyncio
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend.email import send_welcome_background

from backend.auth import (
    clear_auth_cookie,
    create_token,
    decode_token,
    get_auth_cookie,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from backend.db.pool import get_db
from backend.db.users import (
    create_user,
    days_remaining,
    get_user_by_email,
    is_trial_active,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def require_active_user(request: Request, db=Depends(get_db)) -> dict:
    token = get_auth_cookie(request)
    if not token:
        raise HTTPException(status_code=302, headers={"Location": "/login.html"})
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=302, headers={"Location": "/login.html"})
    except jwt.PyJWTError:
        raise HTTPException(status_code=302, headers={"Location": "/login.html"})
    user = get_user_by_email(db, payload["email"])
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/login.html"})
    if not is_trial_active(user):
        raise HTTPException(status_code=403, detail="trial_expired")
    return user


@router.post("/register")
async def register(
    request: Request,
    email: Annotated[str, Form()],
    full_name: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    organization: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    erp: Annotated[str | None, Form()] = None,
    db=Depends(get_db),
):
    if password != password_confirm:
        raise HTTPException(status_code=422, detail="Las contraseñas no coinciden")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 8 caracteres")

    existing = get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=409, detail="Este email ya está registrado")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    pw_hash = hash_password(password)

    user_id = await create_user(db, email, full_name, phone, organization, pw_hash, ip, ua, erp)

    asyncio.create_task(send_welcome_background(email, full_name))

    response = RedirectResponse(url="/app.html", status_code=303)
    token = create_token(user_id, email)
    set_auth_cookie(response, token)
    return response


@router.post("/login")
async def login(
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db=Depends(get_db),
):
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
    if not is_trial_active(user):
        raise HTTPException(
            status_code=403,
            detail=f"Tu período de prueba expiró. Contacta a Batuta AI para renovar tu acceso.",
        )

    response = RedirectResponse(url="/app.html", status_code=303)
    token = create_token(user["id"], user["email"])
    set_auth_cookie(response, token)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/login.html", status_code=303)
    clear_auth_cookie(response)
    return response


@router.get("/me")
async def me(user: dict = Depends(require_active_user)):
    return {
        "email": user["email"],
        "full_name": user["full_name"],
        "days_remaining": days_remaining(user),
    }
