from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI

from app.api.establishments import router as establishments_router
from app.core.config import settings
from app.db.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="Ingenieria para la Alimentación", version="1.0.0", lifespan=lifespan
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(establishments_router)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
