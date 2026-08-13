"""نقطة تشغيل الـ API — Venicia Resort Suite API.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.v1 import (
    auth,
    dashboard,
    folio,
    inventory,
    operations,
    pos,
    reservations,
    tape_chart,
)
from app.core.config import settings
from app.db.base import engine

DESCRIPTION = """
نظام إدارة قرية فينيسيا — المرحلة الأولى.

**الموديولات المتاحة:** المصادقة والصلاحيات · شاشة الحجوزات · داشبورد المالك

كل الرسائل بترجع بالعربي والإنجليزي عشان الواجهة تختار حسب لغة العرض.
"""

app = FastAPI(
    title="Venicia Resort Suite",
    description=DESCRIPTION,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Response-Time-Ms"],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    """زمن الاستجابة في هيدر — مفيد وقت العرض وفي تتبّع البطء."""
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):  # pragma: no cover
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "ar": "حصل خطأ غير متوقع في السيرفر",
                "en": "An unexpected server error occurred",
            }
        },
    )


app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(tape_chart.router, prefix=settings.API_V1_PREFIX)
app.include_router(reservations.router, prefix=settings.API_V1_PREFIX)
app.include_router(folio.router, prefix=settings.API_V1_PREFIX)
app.include_router(pos.router, prefix=settings.API_V1_PREFIX)
app.include_router(inventory.router, prefix=settings.API_V1_PREFIX)
app.include_router(operations.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["النظام — System"], summary="فحص الصحة")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "database": "postgresql" if settings.is_postgres else "sqlite",
    }


# ═══════════════════════════════════════════════════ الواجهة المبنية
#
# لو فيه نسخة مبنية من الواجهة، السيرفر ده بيقدّمها بنفسه. يعني عملية
# واحدة بدل اتنين، ومن غير بروكسي، والصفحات بتيجي جاهزة مش بتتترجم لحظياً.
# لو مفيش نسخة مبنية، بنفضل API بس والتطوير بيمشي على فيت زي ما هو.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
HAS_UI = (DIST / "index.html").is_file()

if HAS_UI:
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_ui(full_path: str) -> FileResponse:
        """أي مسار مش API بيرجّع الواجهة — التوجيه بيتم في المتصفح."""
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(DIST):
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": "Venicia Resort Suite",
            "docs": "/docs",
            "health": "/health",
            "ui": "شغّل الواجهة على فيت — أو ابنيها بـ npm run build",
        }
