"""
FastAPI application factory.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.publishing_routes import router as publishing_router
from app.api.pro_routes import router as pro_router
from app.api.routes import router as api_router
from app.config import settings
from app.data_ingestion.commodity_collector import run_commodity_collector
from app.data_ingestion.global_news_collector import run_global_news_collector
from app.data_ingestion.options_collector import run_collector
from app.data_ingestion.quick_signal_collector import run_quick_signal_collector
from app.db.database import create_all_tables
from app.logging_config import configure_logging, get_logger
from app.services.cache_warmers import warm_startup_caches
from app.services.runtime_cache import runtime_cache

configure_logging()
logger = get_logger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Optionthropic", environment=settings.environment)
    for attempt in range(10):
        try:
            await create_all_tables()
            logger.info("Database tables ready")
            break
        except Exception as exc:
            logger.warning(
                "DB init attempt failed, retrying",
                attempt=attempt + 1,
                error=str(exc),
            )
            await asyncio.sleep(3)

    # Ensure shivraj@thrivify.ai is admin + pro (for existing users)
    try:
        from sqlalchemy import select, update
        from app.api.auth_routes import ADMIN_EMAIL
        from app.db.database import AsyncSessionLocal
        from app.models.user import User, UserPlan

        async with AsyncSessionLocal() as session:
            stmt = select(User).where(User.email == ADMIN_EMAIL)
            user = (await session.execute(stmt)).scalar_one_or_none()
            if user and (not user.is_admin or user.plan == UserPlan.FREE):
                await session.execute(
                    update(User)
                    .where(User.email == ADMIN_EMAIL)
                    .values(is_admin=True, plan=UserPlan.PRO)
                )
                await session.commit()
                logger.info("Ensured admin user", email=ADMIN_EMAIL)
    except Exception as exc:
        logger.warning("Admin ensure failed", error=str(exc))

    from app.services.tick_stream import start_tick_stream
    start_tick_stream()
    logger.info("Tick stream started (live prices when Zerodha connected)")

    await runtime_cache.start()
    warmers_task = None
    if settings.startup_warm_caches:
        warmers_task = asyncio.create_task(warm_startup_caches())
        logger.info("Startup cache warmers scheduled")

    collector_task = asyncio.create_task(run_collector())
    logger.info("Options collector started")
    quick_signal_task = asyncio.create_task(run_quick_signal_collector())
    logger.info("Quick signal collector started")
    commodity_task = asyncio.create_task(run_commodity_collector())
    logger.info("Commodity collector started")
    global_news_task = asyncio.create_task(run_global_news_collector())
    logger.info("Global news collector started")

    yield

    collector_task.cancel()
    quick_signal_task.cancel()
    commodity_task.cancel()
    global_news_task.cancel()
    try:
        await collector_task
    except asyncio.CancelledError:
        pass
    try:
        await quick_signal_task
    except asyncio.CancelledError:
        pass
    try:
        await commodity_task
    except asyncio.CancelledError:
        pass
    try:
        await global_news_task
    except asyncio.CancelledError:
        pass
    if warmers_task is not None:
        warmers_task.cancel()
        try:
            await warmers_task
        except asyncio.CancelledError:
            pass
    await runtime_cache.close()
    logger.info("Optionthropic shutdown complete")


# ─── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Optionthropic",
        description="Institutional-grade options analytics for NIFTY, BANKNIFTY & SENSEX",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    _origins = (
        [
            "https://optionthropic.io",
            "https://www.optionthropic.io",
        ]
        if settings.is_production
        else [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(publishing_router)
    app.include_router(pro_router)
    app.include_router(admin_router)

    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok", "environment": settings.environment}

    @app.get("/api/last-refresh", tags=["system"])
    async def last_refresh():
        """Return the latest data refresh time from DB (max chain_snapshots.timestamp). No auth."""
        from sqlalchemy import func, select
        from app.db.database import AsyncSessionLocal
        from app.models.chain_snapshot import ChainSnapshot
        async with AsyncSessionLocal() as session:
            r = await session.execute(select(func.max(ChainSnapshot.timestamp)))
            ts = r.scalar()
        return {
            "last_refresh_utc": ts.isoformat() if ts else None,
        }

    @app.get("/api/zerodha-status", tags=["system"])
    async def zerodha_status():
        """Return Zerodha token validity and BFO/SENSEX availability. No auth required."""
        from app.config import settings as s
        out = {
            "data_source": s.data_source,
            "token_set": bool(s.zerodha_api_key and s.zerodha_access_token),
            "token_valid": False,
            "bfo_sensex_instruments": 0,
            "message": None,
        }
        if s.data_source != "ZERODHA":
            out["message"] = "Data source is not ZERODHA."
            return out
        if not out["token_set"]:
            out["message"] = "ZERODHA_ACCESS_TOKEN or ZERODHA_API_KEY missing in .env"
            return out
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=s.zerodha_api_key)
            kite.set_access_token(s.zerodha_access_token)
            kite.quote(["NSE:NIFTY 50"])
            out["token_valid"] = True
        except Exception as e:
            out["message"] = str(e)
            return out
        try:
            inst = kite.instruments("BFO")
            sensex = [i for i in inst if i.get("instrument_type") in ("CE", "PE") and (i.get("name") == "SENSEX" or (isinstance(i.get("tradingsymbol"), str) and i.get("tradingsymbol", "").upper().startswith("SENSEX")))]
            out["bfo_sensex_instruments"] = len(sensex)
            if not sensex and inst:
                out["sample_bfo_name"] = inst[0].get("name") if inst else None
                out["sample_bfo_tradingsymbol"] = inst[0].get("tradingsymbol") if inst else None
        except Exception as e:
            out["bfo_error"] = str(e)
        out["message"] = "Token valid." if out["token_valid"] else None
        return out

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        import traceback
        logger.error(
            "Unhandled exception",
            error=str(exc),
            path=str(request.url),
            traceback=traceback.format_exc(),
        )
        # Manually echo CORS headers so the browser sees them even on 500s.
        # FastAPI's exception handler creates a new response that bypasses the
        # CORSMiddleware response phase, so we must add them here.
        origin = request.headers.get("origin", "")
        headers = {}
        if origin in _origins:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(exc)},
            headers=headers,
        )

    return app


app = create_app()
