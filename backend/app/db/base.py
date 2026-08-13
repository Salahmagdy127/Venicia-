"""محرك قاعدة البيانات والجلسات — Engine, session factory, declarative base."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import Engine, MetaData, create_engine, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from app.core.config import settings
from app.db.types import BigIntPK, TZDateTime

# تسمية موحّدة للقيود عشان الـ migrations تفضل مستقرة على المحركين.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """أعمدة التتبّع الزمني الموجودة في كل جدول."""

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, default=utcnow, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class PKMixin:
    """مفتاح أساسي 64-بت — يكفي مليارات الصفوف."""

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)


def _build_engine() -> Engine:
    url = settings.DATABASE_URL

    if settings.is_sqlite:
        # SQLite للعرض: WAL + timeout عشان القراءة والكتابة ميتعارضوش.
        engine = create_engine(
            url,
            echo=settings.DB_ECHO,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=StaticPool if ":memory:" in url else QueuePool,
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver level
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")       # قراءة أثناء الكتابة
            cur.execute("PRAGMA foreign_keys=ON")        # سلامة العلاقات
            cur.execute("PRAGMA synchronous=NORMAL")     # سرعة مع أمان مقبول
            cur.execute("PRAGMA cache_size=-64000")      # 64 ميجا كاش
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA mmap_size=268435456")    # 256 ميجا mmap
            cur.close()

        return engine

    # PostgreSQL للتنفيذ: تجمّع اتصالات حقيقي.
    return create_engine(
        url,
        echo=settings.DB_ECHO,
        future=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency — جلسة واحدة لكل طلب."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
