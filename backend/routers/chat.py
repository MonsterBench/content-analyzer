"""Chat endpoints with SSE streaming."""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from backend.config import settings
from backend.models.database import ChatSession, ChatMessage, get_session
from backend.services.ai_chat import AIChatService

router = APIRouter(prefix="/api", tags=["chat"])

chat_service = AIChatService()


class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Chat"


class ChatSessionOut(BaseModel):
    id: int
    creator_id: int
    title: str
    created_at: str
    message_count: int = 0


class ChatMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


class SendMessageRequest(BaseModel):
    content: str = Field(..., max_length=settings.max_message_length)


@router.post("/creators/{creator_id}/chat", response_model=ChatSessionOut)
def create_chat_session(
    creator_id: int,
    data: ChatSessionCreate = ChatSessionCreate(),
    db: Session = Depends(get_session),
):
    session = chat_service.create_session(creator_id, db, title=data.title or "New Chat")
    return ChatSessionOut(
        id=session.id,
        creator_id=session.creator_id,
        title=session.title,
        created_at=session.created_at.isoformat(),
    )


@router.get("/creators/{creator_id}/chat/sessions", response_model=list[ChatSessionOut])
def list_chat_sessions(creator_id: int, db: Session = Depends(get_session)):
    sessions = chat_service.get_sessions(creator_id, db)
    result = []
    for s in sessions:
        msg_count = len(s.messages) if s.messages else 0
        result.append(ChatSessionOut(
            id=s.id, creator_id=s.creator_id, title=s.title,
            created_at=s.created_at.isoformat(), message_count=msg_count,
        ))
    return result


@router.get("/chat/{session_id}/messages", response_model=list[ChatMessageOut])
def get_chat_messages(session_id: int, db: Session = Depends(get_session)):
    messages = chat_service.get_messages(session_id, db)
    return [
        ChatMessageOut(
            id=m.id, session_id=m.session_id, role=m.role,
            content=m.content, created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


@router.post("/chat/{session_id}/messages")
async def send_message(
    session_id: int,
    data: SendMessageRequest,
    db: Session = Depends(get_session),
):
    """Send a message and get a streaming SSE response."""
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    async def event_stream():
        # Send immediate heartbeat so proxies (Next.js rewrite) don't timeout
        # while context is being built. SSE comment lines are ignored by clients.
        yield ": heartbeat\n\n"
        try:
            async for chunk in chat_service.send_message_streaming(
                session_id, data.content, db,
            ):
                # SSE format
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/{session_id}/messages/upload")
async def send_message_with_files(
    session_id: int,
    content: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_session),
):
    """Send a message with optional file attachments and get a streaming SSE response."""
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Validate message length
    if len(content) > settings.max_message_length:
        raise HTTPException(
            status_code=422,
            detail=f"Message too long (max {settings.max_message_length:,} characters)",
        )

    # Validate file count
    if len(files) > settings.max_files_per_message:
        raise HTTPException(
            status_code=422,
            detail=f"Too many files (max {settings.max_files_per_message})",
        )

    # Process file attachments
    file_attachments = []
    for f in files:
        if not f.filename:
            continue

        # Validate extension
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in settings.allowed_file_extensions:
            raise HTTPException(
                status_code=422,
                detail=f"File type '{ext}' not allowed. Allowed: {', '.join(settings.allowed_file_extensions)}",
            )

        # Read and validate size
        file_bytes = await f.read()
        if len(file_bytes) > settings.max_file_size:
            raise HTTPException(
                status_code=422,
                detail=f"File '{f.filename}' exceeds max size ({settings.max_file_size // 1000}KB)",
            )

        try:
            file_content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=422,
                detail=f"File '{f.filename}' is not valid UTF-8 text",
            )

        file_attachments.append({"filename": f.filename, "content": file_content})

    async def event_stream():
        yield ": heartbeat\n\n"
        try:
            async for chunk in chat_service.send_message_streaming(
                session_id, content, db, file_attachments=file_attachments or None,
            ):
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/chat/{session_id}", status_code=204)
def delete_chat_session(session_id: int, db: Session = Depends(get_session)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    for msg in session.messages:
        db.delete(msg)
    db.delete(session)
    db.commit()


@router.get("/compare")
def compare_creators(
    creator_ids: str,
    db: Session = Depends(get_session),
):
    """Compare multiple creators side-by-side."""
    from sqlmodel import select, func, col
    from backend.models.database import Creator, Platform, ContentItem

    ids = [int(x.strip()) for x in creator_ids.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 creator IDs")

    results = []
    for cid in ids:
        creator = db.get(Creator, cid)
        if not creator:
            continue

        platform_ids = [p.id for p in creator.platforms]
        if not platform_ids:
            results.append({
                "creator_id": cid,
                "name": creator.name,
                "platforms": [],
                "total_content": 0,
                "avg_views": 0,
                "avg_likes": 0,
                "avg_comments": 0,
                "total_views": 0,
            })
            continue

        total = db.exec(
            select(func.count(ContentItem.id))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one()
        avg_views = db.exec(
            select(func.avg(ContentItem.views))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one() or 0
        avg_likes = db.exec(
            select(func.avg(ContentItem.likes))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one() or 0
        avg_comments = db.exec(
            select(func.avg(ContentItem.comments))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one() or 0
        total_views = db.exec(
            select(func.sum(ContentItem.views))
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).one() or 0

        results.append({
            "creator_id": cid,
            "name": creator.name,
            "platforms": [{"type": p.type, "handle": p.handle} for p in creator.platforms],
            "total_content": total,
            "avg_views": int(avg_views),
            "avg_likes": int(avg_likes),
            "avg_comments": int(avg_comments),
            "total_views": int(total_views),
            "summary": creator.summary,
        })

    return results
