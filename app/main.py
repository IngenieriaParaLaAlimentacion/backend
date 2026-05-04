import uvicorn
from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title="Ingenieria para la Alimentación", version="1.0.0")

if __name__ == "__main__":
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)
