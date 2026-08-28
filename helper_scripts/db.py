"""PostgreSQL connection helpers for the Agentic CRM Platform.

Defaults match docker-compose.yaml (crm_db).
Override with DATABASE_URL in backend/.env.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://user:pswd@localhost:5432/crm_db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_connection() -> psycopg.Connection:
    """Open a new Postgres connection (caller must close)."""
    return psycopg.connect(get_database_url())


@contextmanager
def db_cursor() -> Iterator[psycopg.Cursor]:
    """Yield a cursor inside a committed transaction."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            yield cur
            conn.commit()
