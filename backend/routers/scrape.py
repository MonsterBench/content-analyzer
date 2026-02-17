"""Scrape trigger and WebSocket progress endpoints."""

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.models.database import Creator, Platform, ScrapeJob, get_session, engine
from backend.services.instagram_scraper import InstagramScraper
from backend.services.youtube_scraper import YouTubeScraper
from backend.services.transcriber import Transcriber
from backend.services.knowledge import KnowledgeService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["scraping"])

# Store active WebSocket connections for progress updates
_ws_connections: dict[int, list[WebSocket]] = {}

ig_scraper = InstagramScraper()
yt_scraper = YouTubeScraper()
transcriber = Transcriber()
knowledge_svc = KnowledgeService()


class ScrapeRequest(BaseModel):
    transcribe: bool = False
    max_items: int = 0  # 0 = all posts


class ScrapeJobOut(BaseModel):
    id: int
    creator_id: int
    status: str
    new_items_found: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


@router.post("/api/creators/{creator_id}/scrape", response_model=ScrapeJobOut)
async def trigger_scrape(
    creator_id: int,
    request: ScrapeRequest = ScrapeRequest(),
    db: Session = Depends(get_session),
):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    if not creator.platforms:
        raise HTTPException(status_code=400, detail="No platforms linked to this creator")

    # Check for already running jobs
    running = db.exec(
        select(ScrapeJob).where(
            ScrapeJob.creator_id == creator_id,
            ScrapeJob.status == "running",
        )
    ).first()
    if running:
        raise HTTPException(status_code=409, detail="Scrape already in progress")

    # Create job
    job = ScrapeJob(creator_id=creator_id, status="pending", started_at=datetime.utcnow())
    db.add(job)
    db.commit()
    db.refresh(job)

    # Launch background scrape task
    asyncio.create_task(_run_scrape(job.id, creator_id, request.transcribe, request.max_items))

    return ScrapeJobOut(
        id=job.id, creator_id=job.creator_id, status=job.status,
        new_items_found=0, error_message=None,
        started_at=job.started_at, completed_at=None,
    )


@router.get("/api/creators/{creator_id}/scrape/jobs", response_model=list[ScrapeJobOut])
def list_scrape_jobs(creator_id: int, db: Session = Depends(get_session)):
    jobs = db.exec(
        select(ScrapeJob)
        .where(ScrapeJob.creator_id == creator_id)
        .order_by(ScrapeJob.started_at.desc())
        .limit(20)
    ).all()
    return [
        ScrapeJobOut(
            id=j.id, creator_id=j.creator_id, status=j.status,
            new_items_found=j.new_items_found, error_message=j.error_message,
            started_at=j.started_at, completed_at=j.completed_at,
        )
        for j in jobs
    ]


@router.websocket("/ws/scrape/{job_id}")
async def scrape_progress_ws(websocket: WebSocket, job_id: int):
    await websocket.accept()

    if job_id not in _ws_connections:
        _ws_connections[job_id] = []
    _ws_connections[job_id].append(websocket)

    try:
        while True:
            # Keep connection alive, wait for disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_connections[job_id].remove(websocket)
        if not _ws_connections[job_id]:
            del _ws_connections[job_id]


async def _broadcast_progress(job_id: int, data: dict):
    """Send progress update to all connected WebSocket clients."""
    if job_id not in _ws_connections:
        return
    message = json.dumps(data)
    disconnected = []
    for ws in _ws_connections[job_id]:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_connections[job_id].remove(ws)


async def _run_scrape(job_id: int, creator_id: int, transcribe: bool, max_items: int):
    """Background scrape task."""
    from sqlmodel import Session as SqlSession

    with SqlSession(engine) as db:
        job = db.get(ScrapeJob, job_id)
        if not job:
            return

        job.status = "running"
        db.add(job)
        db.commit()

        creator = db.get(Creator, creator_id)
        if not creator:
            job.status = "failed"
            job.error_message = "Creator not found"
            db.add(job)
            db.commit()
            return

        total_new = 0

        try:
            async def progress_cb(data):
                data["job_id"] = job_id
                await _broadcast_progress(job_id, data)

            for platform in creator.platforms:
                await progress_cb({
                    "stage": "platform",
                    "message": f"Scraping {platform.type}: {platform.handle}",
                    "platform_type": platform.type,
                })

                if platform.type == "instagram":
                    new_items = await ig_scraper.scrape(
                        platform, db, max_reels=max_items, progress_callback=progress_cb,
                    )
                elif platform.type == "youtube":
                    new_items = await yt_scraper.scrape(
                        platform, db, max_videos=max_items, progress_callback=progress_cb,
                    )
                else:
                    continue

                total_new += len(new_items)

                # Transcribe if requested and items need it
                if transcribe and new_items:
                    needs_transcription = [
                        (item, item.url)
                        for item in new_items
                        if item.transcript_source == "caption_fallback"
                    ]
                    if needs_transcription:
                        await progress_cb({
                            "stage": "transcribing",
                            "message": f"Transcribing {len(needs_transcription)} items...",
                        })
                        await transcriber.transcribe_batch(
                            needs_transcription, db, progress_callback=progress_cb,
                        )

            # Auto-generate summaries for new unsummarized items
            if total_new > 0:
                try:
                    await progress_cb({
                        "stage": "processing",
                        "message": "Generating AI summaries for new items...",
                    })
                    all_items = []
                    for platform in creator.platforms:
                        from sqlmodel import col
                        from backend.models.database import ContentItem
                        items = db.exec(
                            select(ContentItem)
                            .where(
                                ContentItem.platform_id == platform.id,
                                ContentItem.summary.is_(None),
                            )
                        ).all()
                        all_items.extend(items)
                    if all_items:
                        await knowledge_svc.generate_summaries_for_new_items(all_items, db)
                except Exception as e:
                    logger.warning(f"Post-scrape summary generation failed: {e}")

            job.status = "completed"
            job.new_items_found = total_new
            job.completed_at = datetime.utcnow()

            creator.last_scraped_at = datetime.utcnow()
            db.add(creator)

        except Exception as e:
            logger.exception(f"Scrape job {job_id} failed")
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()

        db.add(job)
        db.commit()

        await _broadcast_progress(job_id, {
            "job_id": job_id,
            "stage": "done",
            "status": job.status,
            "new_items_found": total_new,
            "message": f"Scrape {'completed' if job.status == 'completed' else 'failed'}. {total_new} new items.",
        })
