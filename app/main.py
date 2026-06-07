from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.openapi import configure_openapi
from app.db.database import engine
from app.exceptions.exception_handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Ingenieria para la Alimentación", version="1.0.0", lifespan=lifespan
)
register_exception_handlers(app)

app.include_router(api_router)

configure_openapi(app)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
