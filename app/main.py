from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.establishments import router as establishments_router
from app.api.subjects import router as subjects_router
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

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(establishments_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(subjects_router)
app.include_router(api_router)

configure_openapi(app)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
