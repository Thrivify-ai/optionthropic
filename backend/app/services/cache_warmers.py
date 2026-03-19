"""
Startup warmers for shared runtime caches.
"""

from __future__ import annotations

from app.ai_engine.market_explainer import warm_market_summary_shared_cache
from app.analytics.dashboard_cache import warm_dashboard_overview_cache
from app.logging_config import get_logger

logger = get_logger(__name__)


async def warm_startup_caches() -> None:
    try:
        await warm_market_summary_shared_cache()
        await warm_dashboard_overview_cache()
        logger.info("Startup cache warmers completed")
    except Exception as exc:
        logger.warning("Startup cache warming failed", error=str(exc))
