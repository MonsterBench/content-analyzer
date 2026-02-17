"""Knowledge generation service for pre-computing comprehensive creator understanding."""

import asyncio
import json
import logging
from datetime import datetime, UTC
from typing import AsyncGenerator

from anthropic import AsyncAnthropic
from sqlmodel import Session, select, col, func

from backend.config import settings
from backend.models.database import (
    Creator, Platform, ContentItem, CreatorKnowledge,
)

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self):
        self.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_all(
        self, creator_id: int, db: Session
    ) -> AsyncGenerator[dict, None]:
        """Orchestrate full knowledge generation, yielding progress events."""
        creator = db.get(Creator, creator_id)
        if not creator:
            yield {"stage": "error", "message": "Creator not found"}
            return

        platform_ids = [p.id for p in creator.platforms]
        if not platform_ids:
            yield {"stage": "error", "message": "No platforms linked"}
            return

        items = db.exec(
            select(ContentItem)
            .where(col(ContentItem.platform_id).in_(platform_ids))
            .order_by(ContentItem.timestamp.desc())
        ).all()

        if not items:
            yield {"stage": "error", "message": "No content items found"}
            return

        total_steps = 4
        step = 0

        # Step 1: Video summaries
        step += 1
        yield {
            "stage": "summaries",
            "message": f"Generating video summaries ({len(items)} items)...",
            "progress": step / total_steps * 0.1,
        }
        async for event in self._generate_video_summaries(items, db):
            # Scale summary progress from 0 to 0.5 (it's the longest step)
            if "batch_progress" in event:
                yield {
                    "stage": "summaries",
                    "message": event["message"],
                    "progress": event["batch_progress"] * 0.5,
                }

        # Step 2: Topic clusters
        step += 1
        yield {
            "stage": "topics",
            "message": "Analyzing topic clusters...",
            "progress": 0.55,
        }
        # Refresh items to get summaries
        items = db.exec(
            select(ContentItem)
            .where(col(ContentItem.platform_id).in_(platform_ids))
            .order_by(ContentItem.timestamp.desc())
        ).all()
        clusters = await self._generate_topic_clusters(items, creator)
        self._save_knowledge(creator_id, "topics", clusters, db)
        yield {
            "stage": "topics",
            "message": "Topic clusters complete",
            "progress": 0.7,
        }

        # Step 3: Creator profile
        step += 1
        yield {
            "stage": "profile",
            "message": "Building creator profile...",
            "progress": 0.72,
        }
        profile = await self._generate_creator_profile(items, creator, clusters)
        self._save_knowledge(creator_id, "profile", profile, db)
        yield {
            "stage": "profile",
            "message": "Creator profile complete",
            "progress": 0.85,
        }

        # Step 4: Style analysis
        step += 1
        yield {
            "stage": "style",
            "message": "Analyzing content style...",
            "progress": 0.87,
        }
        style = await self._generate_style_analysis(items, creator)
        self._save_knowledge(creator_id, "style", style, db)
        yield {
            "stage": "style",
            "message": "Style analysis complete",
            "progress": 0.95,
        }

        # Update creator summary from profile
        creator.summary = profile[:2000] if len(profile) > 2000 else profile
        creator.summary_generated_at = datetime.now(UTC)
        db.add(creator)
        db.commit()

        yield {
            "stage": "done",
            "message": "Knowledge generation complete!",
            "progress": 1.0,
        }

    async def _generate_video_summaries(
        self, items: list[ContentItem], db: Session
    ) -> AsyncGenerator[dict, None]:
        """Batch-generate 1-2 sentence summaries for all videos."""
        unsummarized = [i for i in items if not i.summary]
        if not unsummarized:
            yield {
                "batch_progress": 1.0,
                "message": "All videos already summarized",
            }
            return

        batch_size = settings.knowledge_summary_batch_size
        total_batches = (len(unsummarized) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            batch = unsummarized[start : start + batch_size]

            # Build batch prompt
            video_texts = []
            for i, item in enumerate(batch):
                text = f"VIDEO {i+1} (ID: {item.id}):\n"
                if item.title:
                    text += f"Title: {item.title}\n"
                if item.caption:
                    text += f"Caption: {item.caption[:500]}\n"
                if item.transcript and item.transcript != item.caption:
                    text += f"Transcript: {item.transcript[:1500]}\n"
                text += f"Stats: {item.views} views, {item.likes} likes"
                video_texts.append(text)

            prompt = f"""Summarize each video in 1-2 sentences. Focus on the main topic and key takeaway.

{chr(10).join(video_texts)}

Respond with a JSON array of objects: [{{"id": <video_id>, "summary": "<1-2 sentence summary>"}}]
Return ONLY the JSON array, no other text."""

            try:
                response = await self.anthropic.messages.create(
                    model=settings.claude_model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                # Extract JSON from response (handle markdown code blocks)
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                summaries = json.loads(text)
                summary_map = {s["id"]: s["summary"] for s in summaries}

                for item in batch:
                    item.summary = summary_map.get(item.id, item.caption[:200] if item.caption else "No summary")
                    db.add(item)
                db.commit()
            except Exception as e:
                logger.warning(f"Summary batch {batch_idx} failed: {e}")
                # Fallback: use caption
                for item in batch:
                    if not item.summary:
                        item.summary = (item.caption or item.title or "")[:200]
                        db.add(item)
                db.commit()

            progress = (batch_idx + 1) / total_batches
            yield {
                "batch_progress": progress,
                "message": f"Summarized {min(start + batch_size, len(unsummarized))}/{len(unsummarized)} videos",
            }

            # Rate limiting
            if batch_idx < total_batches - 1:
                await asyncio.sleep(settings.knowledge_rate_limit_delay)

    async def _generate_topic_clusters(
        self, items: list[ContentItem], creator: Creator
    ) -> str:
        """Analyze all summaries to identify 5-10 themes."""
        summary_list = []
        for item in items:
            s = item.summary or item.caption or item.title or ""
            if s:
                views = f" ({item.views} views)" if item.views else ""
                summary_list.append(f"- {s[:200]}{views}")

        prompt = f"""Analyze the following {len(summary_list)} video summaries from creator "{creator.name}" and identify the 5-10 major topic clusters/themes.

Video summaries:
{chr(10).join(summary_list[:300])}

For each cluster, provide:
1. Theme name
2. Description (2-3 sentences)
3. Approximate number of videos in this theme
4. Example video topics

Format as a structured analysis. Be specific to this creator's actual content."""

        response = await self.anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def _generate_creator_profile(
        self, items: list[ContentItem], creator: Creator, clusters: str
    ) -> str:
        """Generate a deep creator profile."""
        # Get stats
        total = len(items)
        total_views = sum(i.views for i in items)
        avg_views = total_views // total if total else 0
        avg_likes = sum(i.likes for i in items) // total if total else 0

        # Sample some top content summaries
        top_items = sorted(items, key=lambda x: x.views, reverse=True)[:15]
        top_summaries = "\n".join(
            f"- [{i.views} views] {i.summary or i.title or i.external_id}"
            for i in top_items
        )

        prompt = f"""Create a comprehensive creator profile for "{creator.name}" based on their full content library.

Stats: {total} videos, {total_views:,} total views, {avg_views:,} avg views, {avg_likes:,} avg likes

Topic clusters already identified:
{clusters}

Top performing content:
{top_summaries}

Write a comprehensive profile covering:
1. **Brand Identity**: Who they are, what they stand for, their niche
2. **Content Strategy**: How they structure content, posting patterns, series/recurring formats
3. **Target Audience**: Who watches, what problems they solve, audience demographics/interests
4. **Key Strengths**: What makes their content effective, unique differentiators
5. **Growth Opportunities**: Gaps in content, underexplored themes, potential improvements

Be specific and reference actual content patterns. This profile will be used as context for an AI assistant answering questions about this creator."""

        response = await self.anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    async def _generate_style_analysis(
        self, items: list[ContentItem], creator: Creator
    ) -> str:
        """Sample transcripts and analyze style patterns."""
        # Pick 15 diverse transcripts: top 5, middle 5, recent 5
        by_views = sorted(items, key=lambda x: x.views, reverse=True)
        by_date = sorted(items, key=lambda x: x.timestamp or datetime.min, reverse=True)

        top5 = by_views[:5]
        mid_start = len(by_views) // 2 - 2
        middle5 = by_views[max(0, mid_start):mid_start + 5]
        recent5 = by_date[:5]

        # Deduplicate
        seen = set()
        samples = []
        for item in top5 + recent5 + middle5:
            if item.id not in seen and item.transcript:
                seen.add(item.id)
                samples.append(item)
            if len(samples) >= 15:
                break

        if not samples:
            return "Insufficient transcript data for style analysis."

        transcript_texts = []
        for item in samples:
            t = item.transcript[:2000] if item.transcript else ""
            transcript_texts.append(
                f"--- [{item.views} views, {item.timestamp.strftime('%Y-%m-%d') if item.timestamp else 'no date'}] ---\n{t}"
            )

        prompt = f"""Analyze the speaking/content style of creator "{creator.name}" based on these {len(samples)} transcript samples.

{chr(10).join(transcript_texts)}

Provide a detailed style analysis covering:
1. **Tone & Voice**: Formal/casual, authoritative/conversational, humor style
2. **Vocabulary**: Common phrases, catchphrases, jargon level, unique expressions
3. **Hook Patterns**: How they open videos, attention-grabbing techniques
4. **CTA Patterns**: How they end videos, calls to action, engagement prompts
5. **Format Structure**: Typical video structure (intro/body/outro patterns)
6. **Storytelling Techniques**: How they present information, use of examples/analogies
7. **Engagement Tactics**: Questions, challenges, community references

Be specific with examples from the transcripts. This will help an AI assistant match and understand this creator's style."""

        response = await self.anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _save_knowledge(
        self, creator_id: int, type: str, content: str, db: Session
    ):
        """Upsert a knowledge entry."""
        existing = db.exec(
            select(CreatorKnowledge).where(
                CreatorKnowledge.creator_id == creator_id,
                CreatorKnowledge.type == type,
            )
        ).first()

        if existing:
            existing.content = content
            existing.generated_at = datetime.now(UTC)
            existing.version += 1
            db.add(existing)
        else:
            entry = CreatorKnowledge(
                creator_id=creator_id,
                type=type,
                content=content,
            )
            db.add(entry)
        db.commit()

    async def generate_summaries_for_new_items(
        self, items: list[ContentItem], db: Session
    ):
        """Lightweight post-scrape hook: generate summaries for new items only."""
        unsummarized = [i for i in items if not i.summary]
        if not unsummarized:
            return

        batch_size = settings.knowledge_summary_batch_size
        total_batches = (len(unsummarized) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            batch = unsummarized[start : start + batch_size]

            video_texts = []
            for i, item in enumerate(batch):
                text = f"VIDEO {i+1} (ID: {item.id}):\n"
                if item.title:
                    text += f"Title: {item.title}\n"
                if item.caption:
                    text += f"Caption: {item.caption[:500]}\n"
                if item.transcript and item.transcript != item.caption:
                    text += f"Transcript: {item.transcript[:1500]}\n"
                video_texts.append(text)

            prompt = f"""Summarize each video in 1-2 sentences. Focus on the main topic and key takeaway.

{chr(10).join(video_texts)}

Respond with a JSON array: [{{"id": <video_id>, "summary": "<summary>"}}]
Return ONLY the JSON array."""

            try:
                response = await self.anthropic.messages.create(
                    model=settings.claude_model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                summaries = json.loads(text)
                summary_map = {s["id"]: s["summary"] for s in summaries}

                for item in batch:
                    item.summary = summary_map.get(item.id, (item.caption or "")[:200])
                    db.add(item)
                db.commit()
            except Exception as e:
                logger.warning(f"Post-scrape summary batch failed: {e}")
                for item in batch:
                    if not item.summary:
                        item.summary = (item.caption or item.title or "")[:200]
                        db.add(item)
                db.commit()

            if batch_idx < total_batches - 1:
                await asyncio.sleep(settings.knowledge_rate_limit_delay)

        logger.info(f"Generated summaries for {len(unsummarized)} new items")
