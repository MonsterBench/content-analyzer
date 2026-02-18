"""YouTube scraping service using yt-dlp and youtube-transcript-api."""

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from sqlmodel import Session, select

from backend.config import settings
from backend.models.database import Platform, ContentItem
from backend.services.transcriber import Transcriber

logger = logging.getLogger(__name__)


class YouTubeScraper:

    def _extract_channel_url(self, handle_or_url: str) -> str:
        """Normalize a YouTube channel URL or handle."""
        handle = handle_or_url.strip()
        if handle.startswith("http"):
            return handle.rstrip("/")
        if handle.startswith("@"):
            return f"https://www.youtube.com/{handle}"
        if handle.startswith("/"):
            return f"https://www.youtube.com{handle}"
        return f"https://www.youtube.com/@{handle}"

    async def scrape(
        self,
        platform: Platform,
        db: Session,
        max_videos: int = 0,  # 0 = all
        progress_callback=None,
    ) -> list[ContentItem]:
        """Scrape YouTube channel videos with metadata and transcripts.

        Videos are saved to the DB incrementally as they're processed,
        so results appear in real-time rather than waiting for the full scrape.
        """
        channel_url = self._extract_channel_url(platform.handle)
        logger.info(f"Scraping YouTube channel: {channel_url}")

        if progress_callback:
            await progress_callback({"stage": "scraping", "message": f"Fetching video list from {channel_url}..."})

        # Get existing external IDs
        existing_ids = set()
        stmt = select(ContentItem.external_id).where(ContentItem.platform_id == platform.id)
        for row in db.exec(stmt):
            existing_ids.add(row)

        # Extract flat video list (fast — single yt-dlp call)
        flat_videos = await self._extract_flat_video_list(channel_url, max_videos)

        # Filter out already-scraped videos
        new_video_entries = [v for v in flat_videos if v.get("id", "") not in existing_ids]
        total = len(new_video_entries)
        skipped = len(flat_videos) - total

        if progress_callback:
            await progress_callback({
                "stage": "processing",
                "message": f"Found {len(flat_videos)} videos ({skipped} already scraped, {total} new to process)",
            })

        if total == 0:
            logger.info(f"No new videos to scrape from {channel_url}")
            return []

        new_items = []
        for i, entry in enumerate(new_video_entries):
            video_id = entry.get("id", "")
            if not video_id:
                continue

            # Get transcript (free YouTube captions first, Whisper fallback)
            transcript, transcript_source = await self._get_transcript(video_id)

            item = ContentItem(
                platform_id=platform.id,
                type="youtube_video",
                external_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=entry.get("title", ""),
                caption=entry.get("description", "") or "",
                transcript=transcript or entry.get("description", "") or "",
                transcript_source=transcript_source,
                timestamp=_parse_upload_date(entry.get("upload_date")),
                likes=entry.get("like_count", 0) or 0,
                comments=entry.get("comment_count", 0) or 0,
                views=entry.get("view_count", 0) or 0,
                duration=entry.get("duration", 0) or 0.0,
                tags=str(entry.get("tags", [])),
            )

            # Save immediately to DB
            db.add(item)
            db.commit()
            db.refresh(item)
            new_items.append(item)

            if progress_callback and (i % 3 == 0 or i == total - 1):
                await progress_callback({
                    "stage": "processing",
                    "message": f"Processed {i + 1}/{total} new videos ({item.title[:50]}...)" if item.title and len(item.title) > 50 else f"Processed {i + 1}/{total} new videos",
                    "progress": (i + 1) / total,
                    "new_items_found": len(new_items),
                })

        platform.last_scraped_at = datetime.utcnow()
        db.add(platform)
        db.commit()

        logger.info(f"Scraped {len(new_items)} new videos from {channel_url}")
        return new_items

    async def _extract_flat_video_list(self, channel_url: str, max_videos: int) -> list[dict]:
        """Use yt-dlp to get video list with metadata in a single pass.

        Uses extract_flat=False to get full metadata (title, views, likes, etc.)
        but skip_download=True to avoid downloading any video/audio content.
        """
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        if max_videos > 0:
            ydl_opts["playlistend"] = max_videos

        videos_url = f"{channel_url}/videos"
        entries = await asyncio.to_thread(self._extract_info, videos_url, ydl_opts)

        if not entries or "entries" not in entries:
            return []

        flat_entries = list(entries["entries"])
        if max_videos > 0:
            flat_entries = flat_entries[:max_videos]

        return flat_entries

    async def scrape_single_video(
        self,
        video_url: str,
        platform: Platform,
        db: Session,
    ) -> Optional[ContentItem]:
        """Scrape a single YouTube video by URL."""
        import yt_dlp

        video_id = self._extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"Could not extract video ID from: {video_url}")

        # Check if already exists
        stmt = select(ContentItem).where(
            ContentItem.platform_id == platform.id,
            ContentItem.external_id == video_id,
        )
        existing = db.exec(stmt).first()
        if existing:
            return existing

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
        }

        info = await asyncio.to_thread(self._extract_info, video_url, ydl_opts)
        if not info:
            return None

        transcript, transcript_source = await self._get_transcript(video_id)

        item = ContentItem(
            platform_id=platform.id,
            type="youtube_video",
            external_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=info.get("title", ""),
            caption=info.get("description", ""),
            transcript=transcript or info.get("description", ""),
            transcript_source=transcript_source,
            timestamp=_parse_upload_date(info.get("upload_date")),
            likes=info.get("like_count", 0) or 0,
            comments=info.get("comment_count", 0) or 0,
            views=info.get("view_count", 0) or 0,
            duration=info.get("duration", 0) or 0.0,
            tags=str(info.get("tags", [])),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def _extract_info(self, url: str, ydl_opts: dict) -> Optional[dict]:
        """Extract info using yt-dlp (sync, meant to be run in thread)."""
        import yt_dlp

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f"yt-dlp extraction failed for {url}: {e}")
            return None

    async def _get_transcript(self, video_id: str) -> tuple[Optional[str], str]:
        """Get transcript: try YouTube captions first, then Whisper fallback."""
        # 1. Try free YouTube captions
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt = YouTubeTranscriptApi()
            result = await asyncio.to_thread(ytt.fetch, video_id)
            text = " ".join(s.text for s in result.snippets)
            if text.strip():
                return text, "youtube_captions"
        except Exception as e:
            logger.debug(f"No YouTube transcript for {video_id}: {e}")

        # 2. Whisper fallback — download audio with yt-dlp, send to Whisper
        try:
            transcriber = Transcriber()
            if not transcriber.client:
                logger.debug(f"Whisper not configured, skipping fallback for {video_id}")
                return None, "caption_fallback"

            logger.info(f"Using Whisper fallback for {video_id}")
            audio_path = await self._download_audio(video_id)
            if audio_path:
                try:
                    text = await transcriber.transcribe_file(audio_path)
                    if text:
                        return text, "whisper_api"
                finally:
                    audio_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Whisper fallback failed for {video_id}: {e}")

        return None, "caption_fallback"

    async def _download_audio(self, video_id: str) -> Optional[Path]:
        """Download audio from a YouTube video using yt-dlp."""
        import yt_dlp

        tmp_dir = tempfile.mkdtemp()
        output_path = Path(tmp_dir) / f"{video_id}.%(ext)s"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(output_path),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }],
        }

        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            await asyncio.to_thread(self._run_ytdlp_download, url, ydl_opts)
            # Find the downloaded file
            for f in Path(tmp_dir).iterdir():
                if f.suffix in (".mp3", ".m4a", ".webm", ".opus"):
                    return f
            return None
        except Exception as e:
            logger.error(f"Audio download failed for {video_id}: {e}")
            return None

    def _run_ytdlp_download(self, url: str, ydl_opts: dict):
        """Run yt-dlp download (sync, for use in thread)."""
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"(?:embed/)([a-zA-Z0-9_-]{11})",
            r"(?:shorts/)([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None


def _parse_upload_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse yt-dlp upload_date format (YYYYMMDD)."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d")
    except (ValueError, TypeError):
        return None
