from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from app.api.router import api_router
from app.config.logging import setup_logging
from app.config.settings import settings
from app.config.telemetry import setup_telemetry
from app.core.openapi import configure_openapi
from app.db.database import engine
from app.exceptions.exception_handlers import register_exception_handlers

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ingenieria Para la Alimentacion service getting started")

    yield

    logger.info("Shutting down service, flushing telemetry")
    try:
        telemetry.tracer_provider.shutdown()
        telemetry.meter_provider.shutdown()
        telemetry.logger_provider.shutdown()
    finally:
        await engine.dispose()


app = FastAPI(
    title="Ingenieria para la Alimentación", version="1.0.0", lifespan=lifespan
)
register_exception_handlers(app)

app.include_router(api_router)

configure_openapi(app)

telemetry = setup_telemetry(app)

setup_logging(otel_handler=telemetry.logging_handler)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
