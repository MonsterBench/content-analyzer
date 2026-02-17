"""Instagram scraping service using Apify with retry logic and incremental scraping."""

import asyncio
import time
import logging
from typing import Optional
from datetime import datetime

from apify_client import ApifyClient
from sqlmodel import Session, select

from backend.config import settings
from backend.models.database import Platform, ContentItem

logger = logging.getLogger(__name__)


class InstagramScraper:
    def __init__(self):
        self.client = ApifyClient(settings.apify_api_token)

    def _extract_username(self, handle_or_url: str) -> str:
        """Extract username from handle or URL."""
        if "instagram.com/" in handle_or_url:
            return handle_or_url.rstrip("/").split("/")[-1]
        return handle_or_url.lstrip("@").strip()

    async def scrape(
        self,
        platform: Platform,
        db: Session,
        max_reels: int = 0,  # 0 = all
        progress_callback=None,
    ) -> list[ContentItem]:
        """Scrape Instagram reels for a platform with retry and incremental logic."""
        username = self._extract_username(platform.handle)
        logger.info(f"Scraping Instagram reels for @{username}")

        if progress_callback:
            await progress_callback({"stage": "scraping", "message": f"Scraping @{username} reels..."})

        # Get existing external IDs for incremental scraping
        existing_ids = set()
        stmt = select(ContentItem.external_id).where(ContentItem.platform_id == platform.id)
        for row in db.exec(stmt):
            existing_ids.add(row)

        # Scrape with retry
        raw_reels = await self._scrape_with_retry(username, max_reels)

        if progress_callback:
            await progress_callback({
                "stage": "processing",
                "message": f"Processing {len(raw_reels)} reels...",
            })

        # Process into ContentItems, skipping existing
        new_items = []
        for i, reel in enumerate(raw_reels):
            ext_id = reel.get("shortCode") or reel.get("id", "")
            if str(ext_id) in existing_ids:
                continue

            item = ContentItem(
                platform_id=platform.id,
                type="instagram_reel",
                external_id=str(ext_id),
                url=reel.get("url", ""),
                title=None,
                caption=reel.get("caption", ""),
                transcript=reel.get("transcript") or reel.get("caption", ""),
                transcript_source="instagram_captions" if reel.get("transcript") else "caption_fallback",
                timestamp=_parse_timestamp(reel.get("timestamp")),
                likes=reel.get("likesCount", 0) or 0,
                comments=reel.get("commentsCount", 0) or 0,
                views=reel.get("videoPlayCount", 0) or 0,
                duration=reel.get("videoDuration", 0) or 0.0,
                tags=str(reel.get("hashtags", [])),
            )
            # Store video URL temporarily for transcription
            item._video_url = reel.get("videoUrl")
            new_items.append(item)

            if progress_callback and i % 5 == 0:
                await progress_callback({
                    "stage": "processing",
                    "message": f"Processed {i + 1}/{len(raw_reels)} reels",
                    "progress": (i + 1) / len(raw_reels),
                })

        # Save to DB
        for item in new_items:
            if hasattr(item, "_video_url"):
                delattr(item, "_video_url")
            db.add(item)
        db.commit()

        # Refresh to get IDs
        for item in new_items:
            db.refresh(item)

        platform.last_scraped_at = datetime.utcnow()
        db.add(platform)
        db.commit()

        logger.info(f"Scraped {len(new_items)} new reels for @{username}")
        return new_items

    async def _scrape_with_retry(self, username: str, max_reels: int) -> list[dict]:
        """Run Apify scraper with exponential backoff retry."""
        run_input = {
            "username": [username],
            "resultsType": "reels",
            "addParentData": False,
        }
        if max_reels > 0:
            run_input["resultsLimit"] = max_reels

        for attempt in range(settings.apify_max_retries):
            try:
                run = await asyncio.to_thread(
                    self.client.actor("apify/instagram-reel-scraper").call,
                    run_input=run_input,
                )
                reels = []
                for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
                    reels.append(item)
                return reels

            except Exception as e:
                delay = settings.apify_retry_delay * (2 ** attempt)
                logger.warning(f"Apify attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                if attempt == settings.apify_max_retries - 1:
                    raise
                await asyncio.sleep(delay)

        return []


def _parse_timestamp(ts) -> Optional[datetime]:
    """Parse various timestamp formats."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts)
        except (OSError, ValueError):
            pass
    return None
