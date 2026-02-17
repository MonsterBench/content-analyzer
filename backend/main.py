"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.models.database import create_db_and_tables, engine
from backend.routers import creators, scrape, chat, schedule, knowledge
from backend.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _run_migrations():
    """Add columns that SQLModel doesn't auto-create on existing tables."""
    from sqlmodel import Session as SqlSession, text
    with SqlSession(engine) as db:
        # Add summary column to contentitem if missing
        try:
            db.exec(text("SELECT summary FROM contentitem LIMIT 1"))
        except Exception:
            db.exec(text("ALTER TABLE contentitem ADD COLUMN summary TEXT"))
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    _run_migrations()
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(creators.router)
app.include_router(scrape.router)
app.include_router(chat.router)
app.include_router(schedule.router)
app.include_router(knowledge.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
