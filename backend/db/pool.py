"""
Postgres connection pool for the web service.

Source: https://www.psycopg.org/psycopg3/docs/advanced/pool.html
(verified 2026-04-20, psycopg_pool@3.2.3 / psycopg@3.2.13)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL env var is required")
    return url


pool: ConnectionPool = ConnectionPool(
    conninfo=_database_url(),
    min_size=1,
    max_size=10,
    open=False,
    reconnect_timeout=30,
    reconnect_failed=None,
    kwargs={"autocommit": True},
)


def open_pool() -> None:
    pool.open(wait=True, timeout=10)


def close_pool() -> None:
    pool.close()


def get_db():
    with pool.connection() as conn:
        yield conn
