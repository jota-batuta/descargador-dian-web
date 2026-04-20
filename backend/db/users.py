"""DB helpers for web_users table."""

from __future__ import annotations

from datetime import date
from typing import Optional


async def create_user(
    conn,
    email: str,
    full_name: str,
    phone: str,
    organization: str,
    password_hash: str,
    ip: Optional[str],
    user_agent: Optional[str],
) -> int:
    row = conn.execute(
        """
        INSERT INTO web_users
          (email, full_name, phone, organization, password_hash, ip, user_agent)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (email, full_name, phone, organization, password_hash, ip, user_agent),
    ).fetchone()
    return row[0]


def get_user_by_email(conn, email: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, email, full_name, password_hash, trial_expires FROM web_users WHERE email = %s",
        (email,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "full_name": row[2],
        "password_hash": row[3],
        "trial_expires": row[4],
    }


def is_trial_active(user: dict) -> bool:
    return date.today() <= user["trial_expires"]


def days_remaining(user: dict) -> int:
    delta = user["trial_expires"] - date.today()
    return max(0, delta.days)
