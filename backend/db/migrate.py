"""Apply schema migrations: web_users + download_log tables."""

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

ALTER TABLE web_users ADD COLUMN IF NOT EXISTS erp TEXT;

CREATE TABLE IF NOT EXISTS download_log (
  id           BIGSERIAL    PRIMARY KEY,
  user_email   CITEXT       NOT NULL REFERENCES web_users(email) ON DELETE CASCADE,
  job_id       TEXT         NOT NULL,
  start_date   DATE         NOT NULL,
  end_date     DATE         NOT NULL,
  empresa      TEXT,
  total_docs   INT          DEFAULT 0,
  ok_docs      INT          DEFAULT 0,
  err_docs     INT          DEFAULT 0,
  coverage_pct NUMERIC(5,2) DEFAULT 0,
  duration_s   NUMERIC(8,2) DEFAULT 0,
  status       TEXT         NOT NULL DEFAULT 'running',
  started_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS dl_log_user_idx    ON download_log (user_email);
CREATE INDEX IF NOT EXISTS dl_log_started_idx ON download_log (started_at DESC);
"""


def run_migrations(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute(_SCHEMA)
