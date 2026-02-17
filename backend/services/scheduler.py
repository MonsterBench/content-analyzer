"""APScheduler integration for periodic creator scraping."""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from backend.config import settings
from backend.models.database import Creator, ScrapeJob, engine

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def scrape_creator_job(creator_id: int):
    """Scheduled job to scrape all platforms for a creator."""
    from backend.services.instagram_scraper import InstagramScraper
    from backend.services.youtube_scraper import YouTubeScraper
    from backend.services.embeddings import EmbeddingsService
    from backend.services.knowledge import KnowledgeService

    with Session(engine) as db:
        creator = db.get(Creator, creator_id)
        if not creator:
            logger.warning(f"Scheduled scrape: creator {creator_id} not found")
            return

        logger.info(f"Scheduled scrape starting for creator: {creator.name}")

        job = ScrapeJob(
            creator_id=creator_id,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        ig_scraper = InstagramScraper()
        yt_scraper = YouTubeScraper()
        embeddings = EmbeddingsService()

        total_new = 0

        try:
            for platform in creator.platforms:
                if platform.type == "instagram":
                    new_items = await ig_scraper.scrape(platform, db, max_reels=0)
                elif platform.type == "youtube":
                    new_items = await yt_scraper.scrape(platform, db, max_videos=0)
                else:
                    continue

                total_new += len(new_items)

                # Auto-embed new items
                if new_items:
                    embeddings.embed_content_items(new_items, creator_id, db)

            # Generate summaries for new items
            if total_new > 0:
                knowledge_svc = KnowledgeService()
                all_new = []
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
                    all_new.extend(items)
                if all_new:
                    await knowledge_svc.generate_summaries_for_new_items(all_new, db)

            job.status = "completed"
            job.new_items_found = total_new
            creator.last_scraped_at = datetime.utcnow()
            db.add(creator)

        except Exception as e:
            logger.exception(f"Scheduled scrape failed for creator {creator_id}")
            job.status = "failed"
            job.error_message = str(e)

        job.completed_at = datetime.utcnow()
        db.add(job)
        db.commit()

        logger.info(
            f"Scheduled scrape for {creator.name}: {job.status}, {total_new} new items"
        )


def sync_schedules():
    """Load all creator schedules from DB and register with APScheduler."""
    # Remove all existing creator jobs
    for job in scheduler.get_jobs():
        if job.id.startswith("creator_scrape_"):
            scheduler.remove_job(job.id)

    with Session(engine) as db:
        creators = db.exec(
            select(Creator).where(Creator.schedule_frequency != "manual")
        ).all()

        for creator in creators:
            job_id = f"creator_scrape_{creator.id}"

            if creator.schedule_frequency == "weekly":
                trigger = CronTrigger(day_of_week="mon", hour=6, minute=0)
            elif creator.schedule_frequency == "monthly":
                trigger = CronTrigger(day=1, hour=6, minute=0)
            else:
                continue

            scheduler.add_job(
                scrape_creator_job,
                trigger=trigger,
                id=job_id,
                args=[creator.id],
                replace_existing=True,
                name=f"Scrape: {creator.name} ({creator.schedule_frequency})",
            )
            logger.info(f"Scheduled {creator.schedule_frequency} scrape for {creator.name}")


def start_scheduler():
    """Start the scheduler and load existing schedules."""
    if not scheduler.running:
        scheduler.start()
        sync_schedules()
        logger.info("Scheduler started")


def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
