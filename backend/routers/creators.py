"""Creator CRUD and platform management endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select, col, func

from backend.models.database import (
    Creator, Platform, ContentItem, ScrapeJob, get_session,
)

router = APIRouter(prefix="/api/creators", tags=["creators"])


# --- Request/Response schemas ---

class PlatformCreate(BaseModel):
    type: str  # instagram | youtube
    handle: str
    url: Optional[str] = None


class CreatorCreate(BaseModel):
    name: str
    schedule_frequency: str = "manual"
    platforms: list[PlatformCreate] = []


class CreatorUpdate(BaseModel):
    name: Optional[str] = None
    schedule_frequency: Optional[str] = None


class PlatformOut(BaseModel):
    id: int
    type: str
    handle: str
    url: Optional[str]
    last_scraped_at: Optional[datetime]
    content_count: int = 0


class CreatorOut(BaseModel):
    id: int
    name: str
    summary: Optional[str]
    schedule_frequency: str
    last_scraped_at: Optional[datetime]
    created_at: datetime
    platforms: list[PlatformOut] = []
    total_content: int = 0


class ContentItemOut(BaseModel):
    id: int
    platform_id: int
    type: str
    external_id: str
    url: Optional[str]
    title: Optional[str]
    caption: Optional[str]
    transcript: Optional[str]
    transcript_source: Optional[str]
    timestamp: Optional[datetime]
    likes: int
    comments: int
    views: int
    duration: float
    tags: Optional[str]
    platform_type: str = ""
    platform_handle: str = ""


# --- Endpoints ---

@router.get("", response_model=list[CreatorOut])
def list_creators(db: Session = Depends(get_session)):
    creators = db.exec(select(Creator).order_by(Creator.created_at.desc())).all()
    result = []
    for creator in creators:
        platforms_out = []
        total = 0
        for p in creator.platforms:
            count = db.exec(
                select(func.count(ContentItem.id)).where(ContentItem.platform_id == p.id)
            ).one()
            platforms_out.append(PlatformOut(
                id=p.id, type=p.type, handle=p.handle, url=p.url,
                last_scraped_at=p.last_scraped_at, content_count=count,
            ))
            total += count
        result.append(CreatorOut(
            id=creator.id, name=creator.name, summary=creator.summary,
            schedule_frequency=creator.schedule_frequency,
            last_scraped_at=creator.last_scraped_at, created_at=creator.created_at,
            platforms=platforms_out, total_content=total,
        ))
    return result


@router.post("", response_model=CreatorOut, status_code=201)
def create_creator(data: CreatorCreate, db: Session = Depends(get_session)):
    creator = Creator(name=data.name, schedule_frequency=data.schedule_frequency)
    db.add(creator)
    db.commit()
    db.refresh(creator)

    platforms_out = []
    for p in data.platforms:
        platform = Platform(
            creator_id=creator.id, type=p.type, handle=p.handle, url=p.url,
        )
        db.add(platform)
        db.commit()
        db.refresh(platform)
        platforms_out.append(PlatformOut(
            id=platform.id, type=platform.type, handle=platform.handle,
            url=platform.url, last_scraped_at=None, content_count=0,
        ))

    return CreatorOut(
        id=creator.id, name=creator.name, summary=creator.summary,
        schedule_frequency=creator.schedule_frequency,
        last_scraped_at=creator.last_scraped_at, created_at=creator.created_at,
        platforms=platforms_out, total_content=0,
    )


@router.get("/{creator_id}", response_model=CreatorOut)
def get_creator(creator_id: int, db: Session = Depends(get_session)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    platforms_out = []
    total = 0
    for p in creator.platforms:
        count = db.exec(
            select(func.count(ContentItem.id)).where(ContentItem.platform_id == p.id)
        ).one()
        platforms_out.append(PlatformOut(
            id=p.id, type=p.type, handle=p.handle, url=p.url,
            last_scraped_at=p.last_scraped_at, content_count=count,
        ))
        total += count

    return CreatorOut(
        id=creator.id, name=creator.name, summary=creator.summary,
        schedule_frequency=creator.schedule_frequency,
        last_scraped_at=creator.last_scraped_at, created_at=creator.created_at,
        platforms=platforms_out, total_content=total,
    )


@router.put("/{creator_id}", response_model=CreatorOut)
def update_creator(creator_id: int, data: CreatorUpdate, db: Session = Depends(get_session)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    if data.name is not None:
        creator.name = data.name
    if data.schedule_frequency is not None:
        creator.schedule_frequency = data.schedule_frequency

    db.add(creator)
    db.commit()
    db.refresh(creator)
    return get_creator(creator_id, db)


@router.delete("/{creator_id}", status_code=204)
def delete_creator(creator_id: int, db: Session = Depends(get_session)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    # Delete all related data
    for p in creator.platforms:
        items = db.exec(select(ContentItem).where(ContentItem.platform_id == p.id)).all()
        for item in items:
            db.delete(item)
        db.delete(p)

    for job in creator.scrape_jobs:
        db.delete(job)

    for session in creator.chat_sessions:
        msgs = db.exec(
            select(ChatMessage).where(ChatMessage.session_id == session.id)
        ).all()
        for msg in msgs:
            db.delete(msg)
        db.delete(session)

    db.delete(creator)
    db.commit()


@router.post("/{creator_id}/platforms", response_model=PlatformOut, status_code=201)
def add_platform(creator_id: int, data: PlatformCreate, db: Session = Depends(get_session)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    if data.type not in ("instagram", "youtube"):
        raise HTTPException(status_code=400, detail="Type must be 'instagram' or 'youtube'")

    platform = Platform(
        creator_id=creator_id, type=data.type, handle=data.handle, url=data.url,
    )
    db.add(platform)
    db.commit()
    db.refresh(platform)

    return PlatformOut(
        id=platform.id, type=platform.type, handle=platform.handle,
        url=platform.url, last_scraped_at=None, content_count=0,
    )


@router.delete("/{creator_id}/platforms/{platform_id}", status_code=204)
def remove_platform(creator_id: int, platform_id: int, db: Session = Depends(get_session)):
    platform = db.get(Platform, platform_id)
    if not platform or platform.creator_id != creator_id:
        raise HTTPException(status_code=404, detail="Platform not found")

    items = db.exec(select(ContentItem).where(ContentItem.platform_id == platform.id)).all()
    for item in items:
        db.delete(item)
    db.delete(platform)
    db.commit()


@router.get("/{creator_id}/content", response_model=list[ContentItemOut])
def list_content(
    creator_id: int,
    platform_type: Optional[str] = None,
    sort_by: str = Query(default="timestamp", pattern="^(timestamp|likes|views|comments|duration)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=500, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    platform_ids = [p.id for p in creator.platforms]
    platform_map = {p.id: p for p in creator.platforms}

    if platform_type:
        platform_ids = [p.id for p in creator.platforms if p.type == platform_type]

    if not platform_ids:
        return []

    stmt = select(ContentItem).where(col(ContentItem.platform_id).in_(platform_ids))

    sort_col = getattr(ContentItem, sort_by)
    if sort_order == "desc":
        stmt = stmt.order_by(sort_col.desc())
    else:
        stmt = stmt.order_by(sort_col.asc())

    stmt = stmt.offset(offset).limit(limit)
    items = db.exec(stmt).all()

    return [
        ContentItemOut(
            id=item.id, platform_id=item.platform_id, type=item.type,
            external_id=item.external_id, url=item.url, title=item.title,
            caption=item.caption, transcript=item.transcript,
            transcript_source=item.transcript_source, timestamp=item.timestamp,
            likes=item.likes, comments=item.comments, views=item.views,
            duration=item.duration, tags=item.tags,
            platform_type=platform_map[item.platform_id].type if item.platform_id in platform_map else "",
            platform_handle=platform_map[item.platform_id].handle if item.platform_id in platform_map else "",
        )
        for item in items
    ]


# Import ChatMessage for delete cascade
from backend.models.database import ChatMessage
