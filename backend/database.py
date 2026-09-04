"""Postgres/Supabase connection, env-driven.

`DATABASE_URL` is the single source of truth. Local dev points at the pgvector
container; production points at the Supabase pooler connection string.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    # 127.0.0.1, not localhost: localhost resolves to ::1 first and a
    # docker-published IPv4 port does not answer there, so every connect eats a
    # ~26s TCP timeout before falling back.
    "DATABASE_URL",
    "postgresql+psycopg://postgres:devpass@127.0.0.1:55432/logistics",
)

# Statement timeout applied to LLM-generated SQL, in milliseconds.
SQL_TIMEOUT_MS = int(os.getenv("SQL_TIMEOUT_MS", "5000"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    # Supabase's pooler runs pgbouncer in transaction mode, which rejects
    # server-side prepared statements. Disabling them keeps one code path for
    # both local Postgres and Supabase.
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
