"""
FIREX v2 Database Connection & Session Management
Supports PostgreSQL+PostGIS with graceful fallback to SQLite for local development.
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings
from app.core.logging import logger

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite:///"):
        sqlite_file = settings.DATABASE_URL.replace("sqlite:///", "")
        db_dir = os.path.dirname(sqlite_file)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_db_connection() -> dict:
    """Check database health status and driver information."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "status": "connected",
            "dialect": engine.dialect.name,
            "url": settings.DATABASE_URL.split("@")[-1]  # obscure credentials if any
        }
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "dialect": engine.dialect.name
        }
