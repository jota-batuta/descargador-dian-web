"""Apply the web_users table migration if it doesn't exist yet."""

from __future__ import annotations

from psycopg_pool import ConnectionPool

_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS web_users (
  id            BIGSERIAL    PRIMARY KEY,
  email         CITEXT       NOT NULL UNIQUE,
  full_name     TEXT         NOT NULL,
  phone         TEXT         NOT NULL,
  organization  TEXT         NOT NULL,
  password_hash TEXT         NOT NULL,
  ip            INET,
  user_agent    TEXT,
  registered_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  trial_expires DATE         NOT NULL DEFAULT (CURRENT_DATE + INTERVAL '120 days')
);

CREATE INDEX IF NOT EXISTS web_users_email_idx ON web_users (email);
CREATE INDEX IF NOT EXISTS web_users_trial_idx  ON web_users (trial_expires);
"""


def run_migrations(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute(_SCHEMA)
