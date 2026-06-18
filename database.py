"""
database.py  ─  MySQL connection setup using SQLAlchemy.

Reads credentials from .env and exposes:
  - engine        : raw SQLAlchemy engine
  - SessionLocal  : scoped session factory (for FastAPI dependency injection)
  - Base           : declarative base for ORM models
  - get_db()       : FastAPI dependency that yields a DB session
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ── Load environment variables from .env ─────────────────────
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "mediflow")

# ── Build the MySQL connection URL ───────────────────────────
# Using PyMySQL as the connector (pure‑Python, no C deps needed)
DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

# ── Create engine & session factory ──────────────────────────
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # auto‑reconnect stale connections
    pool_size=10,
    max_overflow=20,
    echo=False,           # set True for SQL debug logging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Declarative base for ORM models ─────────────────────────
Base = declarative_base()


def get_db():
    """
    FastAPI dependency: yields a SQLAlchemy session and
    ensures it is closed after the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Create all tables declared on `Base.metadata`.
    Call once at startup (idempotent thanks to checkfirst).
    """
    Base.metadata.create_all(bind=engine)
