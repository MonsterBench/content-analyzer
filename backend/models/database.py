"""SQLModel database tables for the Content Analyzer."""

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship, create_engine, Session
from sqlalchemy import event

from backend.config import settings


# --- Models ---

class Creator(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    summary: Optional[str] = None
    summary_generated_at: Optional[datetime] = None
    schedule_frequency: str = Field(default="manual")  # weekly | monthly | manual
    last_scraped_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    platforms: list["Platform"] = Relationship(back_populates="creator")
    scrape_jobs: list["ScrapeJob"] = Relationship(back_populates="creator")
    chat_sessions: list["ChatSession"] = Relationship(back_populates="creator")
    knowledge: list["CreatorKnowledge"] = Relationship(back_populates="creator")


class Platform(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="creator.id", index=True)
    type: str  # instagram | youtube
    handle: str
    url: Optional[str] = None
    last_scraped_at: Optional[datetime] = None

    creator: Optional[Creator] = Relationship(back_populates="platforms")
    content_items: list["ContentItem"] = Relationship(back_populates="platform")


class ContentItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform_id: int = Field(foreign_key="platform.id", index=True)
    type: str  # instagram_reel | youtube_video
    external_id: str = Field(index=True)
    url: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    transcript: Optional[str] = None
    transcript_source: Optional[str] = None  # instagram_captions | whisper_api | youtube_captions | caption_fallback
    timestamp: Optional[datetime] = None
    likes: int = 0
    comments: int = 0
    views: int = 0
    duration: float = 0.0
    tags: Optional[str] = None  # JSON-encoded list
    is_embedded: bool = False
    summary: Optional[str] = None  # AI-generated 1-2 sentence summary

    platform: Optional[Platform] = Relationship(back_populates="content_items")


class ScrapeJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="creator.id", index=True)
    status: str = Field(default="pending")  # pending | running | completed | failed
    new_items_found: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    creator: Optional[Creator] = Relationship(back_populates="scrape_jobs")


class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="creator.id", index=True)
    title: str = Field(default="New Chat")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    creator: Optional[Creator] = Relationship(back_populates="chat_sessions")
    messages: list["ChatMessage"] = Relationship(back_populates="session")


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: str  # user | assistant
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    session: Optional[ChatSession] = Relationship(back_populates="messages")


class CreatorKnowledge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="creator.id", index=True)
    type: str  # profile | topics | style
    content: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=1)

    creator: Optional[Creator] = Relationship(back_populates="knowledge")


# --- Engine + Session ---

engine = create_engine(settings.database_url, echo=settings.debug)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
