"""Knowledge generation and retrieval endpoints."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select, col, func

from backend.models.database import (
    Creator, Platform, ContentItem, CreatorKnowledge, get_session,
)
from backend.services.knowledge import KnowledgeService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["knowledge"])

knowledge_svc = KnowledgeService()


class KnowledgeEntryOut(BaseModel):
    id: int
    type: str
    generated_at: datetime
    version: int
    content_preview: str


class KnowledgeStatusOut(BaseModel):
    has_knowledge: bool
    total_items: int
    summarized_items: int
    entries: list[KnowledgeEntryOut]


class KnowledgeDetailOut(BaseModel):
    id: int
    type: str
    content: str
    generated_at: datetime
    version: int


@router.get("/api/creators/{creator_id}/knowledge", response_model=KnowledgeStatusOut)
def get_knowledge_status(creator_id: int, db: Session = Depends(get_session)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    platform_ids = [p.id for p in creator.platforms]

    total_items = 0
    summarized_items = 0
    if platform_ids:
        total_items = db.exec(
            select(func.count(ContentItem.id))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one()
        summarized_items = db.exec(
            select(func.count(ContentItem.id))
            .where(
                col(ContentItem.platform_id).in_(platform_ids),
                ContentItem.summary.isnot(None),
            )
        ).one()

    knowledge_entries = db.exec(
        select(CreatorKnowledge)
        .where(CreatorKnowledge.creator_id == creator_id)
        .order_by(CreatorKnowledge.type)
    ).all()

    entries = [
        KnowledgeEntryOut(
            id=k.id,
            type=k.type,
            generated_at=k.generated_at,
            version=k.version,
            content_preview=k.content[:200] + "..." if len(k.content) > 200 else k.content,
        )
        for k in knowledge_entries
    ]

    return KnowledgeStatusOut(
        has_knowledge=len(knowledge_entries) > 0,
        total_items=total_items,
        summarized_items=summarized_items,
        entries=entries,
    )


@router.post("/api/creators/{creator_id}/knowledge/generate")
async def generate_knowledge(creator_id: int, db: Session = Depends(get_session)):
    """Trigger full knowledge generation with SSE progress stream."""
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    async def event_stream():
        async for event in knowledge_svc.generate_all(creator_id, db):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/api/creators/{creator_id}/knowledge/{knowledge_type}",
    response_model=KnowledgeDetailOut,
)
def get_knowledge_detail(
    creator_id: int, knowledge_type: str, db: Session = Depends(get_session)
):
    entry = db.exec(
        select(CreatorKnowledge).where(
            CreatorKnowledge.creator_id == creator_id,
            CreatorKnowledge.type == knowledge_type,
        )
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail=f"No {knowledge_type} knowledge found")

    return KnowledgeDetailOut(
        id=entry.id,
        type=entry.type,
        content=entry.content,
        generated_at=entry.generated_at,
        version=entry.version,
    )
