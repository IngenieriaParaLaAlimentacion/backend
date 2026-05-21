from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.core.config import settings
from app.core.openapi import configure_openapi
from app.db.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Ingenieria para la Alimentación", version="1.0.0", lifespan=lifespan
)

configure_openapi(app)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
