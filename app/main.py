import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config.logging import setup_logging
from app.config.settings import settings
from app.config.telemetry import setup_telemetry
from app.core.openapi import configure_openapi
from app.core.rate_limit import close_limiter
from app.db.database import engine
from app.exceptions.exception_handlers import register_exception_handlers
from app.services.notifications.stale_establishment_scheduler import (
    StaleEstablishmentScheduler,
)

logger = structlog.get_logger()


async def _shutdown_provider(name: str, provider) -> None:
    try:
        await asyncio.to_thread(provider.shutdown)
    except Exception:
        logger.exception(f"Failed to shutdown {name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ingenieria Para la Alimentacion service getting started")
    app.state.llm_client = None
    notification_scheduler = StaleEstablishmentScheduler()
    notification_scheduler.start()

    try:
        yield
    finally:
        await notification_scheduler.shutdown()

        client = app.state.llm_client
        app.state.llm_client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.exception("Failed to close Gemini client")

        logger.info("Shutting down service, flushing telemetry")

        await asyncio.gather(
            _shutdown_provider("tracer_provider", telemetry.tracer_provider),
            _shutdown_provider("meter_provider", telemetry.meter_provider),
            _shutdown_provider("logger_provider", telemetry.logger_provider),
        )

        try:
            await close_limiter()
        except Exception:
            logger.exception("Failed to close the rate limiter")

        await engine.dispose()


app = FastAPI(
    title="Ingenieria para la Alimentación", version="1.0.0", lifespan=lifespan
)
register_exception_handlers(app)

app.include_router(api_router)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

configure_openapi(app)

telemetry = setup_telemetry(app)

setup_logging(otel_handler=telemetry.logging_handler)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
