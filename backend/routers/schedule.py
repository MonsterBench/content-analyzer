"""Schedule management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from backend.models.database import Creator, get_session
from backend.services.scheduler import sync_schedules, scheduler

router = APIRouter(prefix="/api/schedule", tags=["scheduling"])


class ScheduleUpdate(BaseModel):
    frequency: str  # weekly | monthly | manual


class ScheduleOut(BaseModel):
    creator_id: int
    creator_name: str
    frequency: str
    last_scraped_at: str | None
    next_run: str | None


@router.put("/creators/{creator_id}")
def update_schedule(
    creator_id: int,
    data: ScheduleUpdate,
    db: Session = Depends(get_session),
):
    if data.frequency not in ("weekly", "monthly", "manual"):
        raise HTTPException(status_code=400, detail="Frequency must be weekly, monthly, or manual")

    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    creator.schedule_frequency = data.frequency
    db.add(creator)
    db.commit()

    # Resync all schedules
    sync_schedules()

    return {"status": "ok", "frequency": data.frequency}


@router.get("", response_model=list[ScheduleOut])
def list_schedules(db: Session = Depends(get_session)):
    from sqlmodel import select

    creators = db.exec(select(Creator)).all()
    result = []

    for creator in creators:
        job_id = f"creator_scrape_{creator.id}"
        next_run = None
        job = scheduler.get_job(job_id)
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

        result.append(ScheduleOut(
            creator_id=creator.id,
            creator_name=creator.name,
            frequency=creator.schedule_frequency,
            last_scraped_at=creator.last_scraped_at.isoformat() if creator.last_scraped_at else None,
            next_run=next_run,
        ))

    return result
