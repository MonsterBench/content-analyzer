"""Whisper transcription service with parallel processing."""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

import requests
from openai import OpenAI
from sqlmodel import Session

from backend.config import settings
from backend.models.database import ContentItem

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def transcribe_url(self, video_url: str) -> Optional[str]:
        """Transcribe a video from URL using Whisper API."""
        if not self.client:
            logger.warning("OpenAI client not configured, skipping transcription")
            return None

        try:
            # Download video to temp file
            response = await asyncio.to_thread(requests.get, video_url)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = Path(tmp.name)

            try:
                return await self.transcribe_file(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None

    async def transcribe_file(self, file_path: Path) -> Optional[str]:
        """Transcribe an audio/video file using Whisper API."""
        if not self.client:
            logger.warning("OpenAI client not configured, skipping transcription")
            return None

        try:
            with open(file_path, "rb") as audio_file:
                transcript = await asyncio.to_thread(
                    self.client.audio.transcriptions.create,
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                )
            return transcript
        except Exception as e:
            logger.error(f"Whisper transcription failed for {file_path}: {e}")
            return None

    async def transcribe_batch(
        self,
        items: list[tuple[ContentItem, str]],
        db: Session,
        progress_callback=None,
    ) -> int:
        """Transcribe multiple content items in parallel batches.

        Args:
            items: List of (ContentItem, video_url) tuples
            db: Database session
            progress_callback: Optional async callback for progress updates

        Returns:
            Number of successfully transcribed items
        """
        if not items:
            return 0

        batch_size = settings.whisper_batch_size
        transcribed = 0

        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start : batch_start + batch_size]

            tasks = [self.transcribe_url(url) for item, url in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (item, _url), result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.warning(f"Transcription failed for {item.external_id}: {result}")
                    continue
                if result:
                    item.transcript = result
                    item.transcript_source = "whisper_api"
                    db.add(item)
                    transcribed += 1

            db.commit()

            if progress_callback:
                done = min(batch_start + batch_size, len(items))
                await progress_callback({
                    "stage": "transcribing",
                    "message": f"Transcribed {done}/{len(items)} items",
                    "progress": done / len(items),
                })

        return transcribed
