"""Auth helpers: bcrypt password hashing and JWT cookies."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Request, Response

_JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_TTL_HOURS = 24
_COOKIE_NAME = "dian_session"


# --- password ---

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# --- JWT ---

def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_TTL_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])


# --- cookie helpers ---

def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=_JWT_TTL_HOURS * 3600,
        secure=os.environ.get("SECURE_COOKIES", "false").lower() == "true",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(_COOKIE_NAME)


def get_auth_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(_COOKIE_NAME)
