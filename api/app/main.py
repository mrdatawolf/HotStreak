from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import sheet_sync
from .config import settings
from .routers import (
    auth, clients, deals, flags, items, periods, reports, reps, settings as settings_router, sheet, users,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Pull the client's Google Sheet on a timer, when it's set up in .env.
    stop = sheet_sync.start_timer()
    yield
    if stop:
        stop.set()


app = FastAPI(title="HotStreak API", version="0.1.0", lifespan=lifespan)

# The web app normally reaches the API through the Vite dev proxy; this covers direct calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


for module in (auth, periods, deals, reports, reps, clients, items, flags, users, settings_router, sheet):
    api.include_router(module.router)
app.include_router(api)
