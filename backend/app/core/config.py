"""إعدادات النظام — Application settings.

نقطة التبديل بين SQLite (العرض) و PostgreSQL (التنفيذ) هي ``DATABASE_URL`` وبس.
The single switch between SQLite (demo) and PostgreSQL (production) is ``DATABASE_URL``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application -----------------------------------------------------
    APP_NAME: str = "Venicia Resort Suite"
    ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- Database --------------------------------------------------------
    # العرض / demo:      sqlite:///./venicia.db
    # التنفيذ / production: postgresql+psycopg://user:pass@host:5432/venicia
    DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'venicia.db').as_posix()}"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800

    # --- Security --------------------------------------------------------
    SECRET_KEY: str = "change-me-in-production-please-use-a-long-random-value"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # --- Localisation ----------------------------------------------------
    DEFAULT_LOCALE: str = "ar"
    SUPPORTED_LOCALES: tuple[str, ...] = ("ar", "en")
    DEFAULT_CURRENCY: str = "EGP"
    DEFAULT_TIMEZONE: str = "Africa/Cairo"

    # --- CORS ------------------------------------------------------------
    CORS_ORIGINS: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    # --- Pagination ------------------------------------------------------
    # الترقيم بالـ keyset — الحد الأقصى يمنع أي استعلام مفتوح على جدول بالملايين
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
