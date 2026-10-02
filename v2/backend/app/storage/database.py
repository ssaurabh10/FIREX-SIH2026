"""
FIREX v2 Database Connection & Session Management
Supports PostgreSQL+PostGIS with graceful fallback to SQLite for local development.
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings
from app.core.logging import logger

def normalize_database_url(url: str) -> str:
    """Normalize database URL for SQLAlchemy compatibility using psycopg2-binary driver."""
    if not url:
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url

db_url = normalize_database_url(settings.DATABASE_URL)

connect_args = {}
engine_kwargs = {
    "echo": False,
}

if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    engine_kwargs["connect_args"] = connect_args
    if db_url.startswith("sqlite:///"):
        sqlite_file = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(sqlite_file)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
else:
    # PostgreSQL connection resilience on cloud hosts like Render
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(
    db_url,
    **engine_kwargs
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
