"""AI chat service with hybrid retrieval, conversation memory, and streaming."""

import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import AsyncGenerator, Optional

from anthropic import AsyncAnthropic
from sqlmodel import Session, select, func, col

from backend.config import settings
from backend.models.database import (
    Creator, Platform, ContentItem, ChatSession, ChatMessage, CreatorKnowledge,
)
from backend.services.embeddings import EmbeddingsService

logger = logging.getLogger(__name__)


class AIChatService:
    def __init__(self):
        self.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.embeddings = EmbeddingsService()

    def create_session(self, creator_id: int, db: Session, title: str = "New Chat") -> ChatSession:
        session = ChatSession(creator_id=creator_id, title=title)
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get_sessions(self, creator_id: int, db: Session) -> list[ChatSession]:
        return db.exec(
            select(ChatSession)
            .where(ChatSession.creator_id == creator_id)
            .order_by(ChatSession.created_at.desc())
        ).all()

    def get_messages(self, session_id: int, db: Session) -> list[ChatMessage]:
        return db.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        ).all()

    async def send_message_streaming(
        self,
        session_id: int,
        user_message: str,
        db: Session,
        file_attachments: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Send a message and stream the response."""
        session = db.get(ChatSession, session_id)
        if not session:
            yield "Error: Chat session not found"
            return

        creator = db.get(Creator, session.creator_id)
        if not creator:
            yield "Error: Creator not found"
            return

        # Get conversation history BEFORE saving user message to avoid duplication
        history = self._get_history(session_id, db)

        # Save user message (full content preserved in DB)
        user_msg = ChatMessage(session_id=session_id, role="user", content=user_message)
        db.add(user_msg)
        db.commit()

        # Build context — only use first N chars for retrieval queries
        query_text = user_message[:settings.max_keyword_extract_chars]
        context = self._build_context(creator, query_text, db)

        # Build messages for Claude: history + current user message (truncated)
        messages = []
        for msg in history:
            content = msg.content
            if len(content) > 3000:
                content = content[:3000] + "\n[...truncated]"
            messages.append({"role": msg.role, "content": content})

        # Truncate user message sent to Claude to avoid token overflow
        user_msg_for_claude = user_message
        if len(user_msg_for_claude) > settings.max_user_msg_to_claude:
            user_msg_for_claude = (
                user_msg_for_claude[:settings.max_user_msg_to_claude]
                + "\n\n[Message truncated — full message was saved]"
            )
        messages.append({"role": "user", "content": user_msg_for_claude})

        system_prompt = self._build_system_prompt(creator, context, db, file_attachments=file_attachments)

        # Stream response from Claude (async)
        full_response = ""
        try:
            async with self.anthropic.messages.stream(
                model=settings.claude_model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    yield text
        except Exception as e:
            error_msg = f"Error communicating with Claude: {e}"
            logger.error(error_msg)
            yield error_msg
            full_response = error_msg

        # Save assistant message
        assistant_msg = ChatMessage(
            session_id=session_id, role="assistant", content=full_response,
        )
        db.add(assistant_msg)
        db.commit()

        # Auto-title on first message
        if len(history) == 0:
            session.title = user_message[:80]
            db.add(session)
            db.commit()

    def _build_system_prompt(
        self,
        creator: Creator,
        context: str,
        db: Session,
        file_attachments: list[dict] | None = None,
    ) -> str:
        """Build system prompt with Tier 1 knowledge + content catalog + Tier 2 context."""
        # Get platform info
        platforms_info = []
        for p in creator.platforms:
            count = db.exec(
                select(func.count(ContentItem.id)).where(ContentItem.platform_id == p.id)
            ).one()
            platforms_info.append(f"  - {p.type.title()}: @{p.handle} ({count} items)")

        platforms_str = "\n".join(platforms_info) if platforms_info else "  No platforms linked"

        # --- Tier 1: Pre-computed knowledge (always included) ---
        knowledge_entries = db.exec(
            select(CreatorKnowledge).where(CreatorKnowledge.creator_id == creator.id)
        ).all()
        knowledge_map = {k.type: k.content for k in knowledge_entries}

        tier1_sections = []

        if "profile" in knowledge_map:
            tier1_sections.append(f"## Creator Profile\n{knowledge_map['profile']}")
        elif creator.summary:
            tier1_sections.append(f"## Creator Summary\n{creator.summary}")

        if "topics" in knowledge_map:
            tier1_sections.append(f"## Topic Clusters\n{knowledge_map['topics']}")

        if "style" in knowledge_map:
            tier1_sections.append(f"## Style Analysis\n{knowledge_map['style']}")

        tier1_str = "\n\n".join(tier1_sections) if tier1_sections else ""

        # --- Tier 1: Content catalog (ALL videos with summaries) ---
        catalog = self._build_content_catalog(creator, db)

        # --- Tier 3: Aggregate stats ---
        platform_ids = [p.id for p in creator.platforms]
        total = avg_views = avg_likes = 0
        if platform_ids:
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

        stats_str = (
            f"Total content items: {total} | "
            f"Average views: {int(avg_views):,} | "
            f"Average likes: {int(avg_likes):,}"
        )

        # Budget guard: truncate catalog and context if too large
        max_catalog = 40_000
        if len(catalog) > max_catalog:
            catalog = catalog[:max_catalog] + "\n\n[...catalog truncated to fit token limits]"

        max_context = 60_000
        if len(context) > max_context:
            context = context[:max_context] + "\n\n[...transcripts truncated to fit token limits]"

        # Optional file attachments section
        files_section = ""
        if file_attachments:
            file_parts = []
            for att in file_attachments:
                file_parts.append(f"### {att['filename']}\n```\n{att['content']}\n```")
            files_section = (
                "\n\n## User-Provided Reference Material\n"
                "The user attached the following files with their message:\n\n"
                + "\n\n".join(file_parts)
            )

        prompt = f"""You are an expert content analyst with deep knowledge of creator "{creator.name}".

## Creator: {creator.name}
Platforms:
{platforms_str}
Stats: {stats_str}

{tier1_str}

## Complete Content Catalog
Every video/reel from this creator with summaries:

{catalog}

## Relevant Full Transcripts
The following full transcripts were retrieved based on the user's current question:

{context}
{files_section}

## Instructions
- You have comprehensive knowledge about this creator from the profile, topic clusters, and style analysis above
- The content catalog lists EVERY video — use it to reference specific content, identify patterns, and provide complete answers
- Full transcripts below are the primary source for detailed quotes and specific content analysis
- Reference specific posts/videos when relevant (include URLs if available)
- Provide data-backed insights (engagement numbers, trends, patterns)
- Be specific and actionable in your recommendations
- If the transcripts don't contain enough detail for a specific question, note what you know from the catalog/profile and suggest which videos might have more info
"""
        # Hard cap on total system prompt size
        if len(prompt) > settings.max_system_prompt_chars:
            prompt = prompt[:settings.max_system_prompt_chars] + "\n\n[System prompt truncated to fit token limits]"

        return prompt

    def _build_content_catalog(self, creator: Creator, db: Session) -> str:
        """Build compact catalog of ALL videos with summaries (Tier 1)."""
        platform_ids = [p.id for p in creator.platforms]
        if not platform_ids:
            return "No content available."

        items = db.exec(
            select(ContentItem)
            .where(col(ContentItem.platform_id).in_(platform_ids))
            .order_by(ContentItem.timestamp.desc())
        ).all()

        if not items:
            return "No content available."

        lines = []
        for item in items:
            platform = db.get(Platform, item.platform_id)
            p_label = f"{platform.type}:{platform.handle}" if platform else item.type
            date_str = item.timestamp.strftime('%Y-%m-%d') if item.timestamp else "?"
            summary = item.summary or item.title or item.external_id
            url_str = f" | {item.url}" if item.url else ""
            lines.append(
                f"- [{p_label}] [{date_str}] {summary} "
                f"({item.views:,} views, {item.likes:,} likes{url_str})"
            )

        return "\n".join(lines)

    def _build_context(self, creator: Creator, question: str, db: Session) -> str:
        """Tier 2: Retrieve full transcripts of 5-10 most relevant videos."""
        MAX_CONTEXT_CHARS = 60000
        MAX_TRANSCRIPT_PER_ITEM = 8000
        parts = []

        platform_ids = [p.id for p in creator.platforms]
        if not platform_ids:
            return "No content data available yet."

        seen_ids: set[int] = set()

        # 1. Keyword search for relevant transcripts
        keyword_results = self._keyword_search(question, platform_ids, db, max_results=5)
        if keyword_results:
            parts.append("### Keyword-Matched Transcripts")
            for item, score, platform in keyword_results:
                parts.append(self._format_item_full(item, platform, MAX_TRANSCRIPT_PER_ITEM))
                parts.append("---")
                seen_ids.add(item.id)

        # 2. Semantic search for additional relevant content (cap query length)
        try:
            semantic_query = question[:settings.max_keyword_extract_chars]
            search_results = self.embeddings.search(creator.id, semantic_query, n_results=5)
            if search_results:
                semantic_new = []
                for r in search_results:
                    content_id = r["metadata"].get("content_id")
                    if content_id and content_id not in seen_ids:
                        semantic_new.append(content_id)
                        seen_ids.add(content_id)

                if semantic_new:
                    parts.append("\n### Semantically Relevant Transcripts")
                    for cid in semantic_new:
                        item = db.get(ContentItem, cid)
                        if item:
                            platform = db.get(Platform, item.platform_id)
                            parts.append(self._format_item_full(item, platform, MAX_TRANSCRIPT_PER_ITEM))
                            parts.append("---")
        except Exception as e:
            logger.debug(f"Embedding search skipped: {e}")

        if not parts:
            parts.append("No specific transcripts matched this query. Refer to the content catalog and creator knowledge above.")

        context = "\n".join(parts)
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS] + "\n\n[Transcripts truncated to fit token limits]"
        return context

    def _keyword_search(
        self,
        question: str,
        platform_ids: list[int],
        db: Session,
        max_results: int = 8,
    ) -> list[tuple[ContentItem, float, Platform]]:
        """Search transcripts and captions by keywords from the question."""
        # Extract meaningful keywords (skip very short/common words)
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "about", "between",
            "through", "after", "before", "during", "without", "this", "that",
            "these", "those", "it", "its", "he", "she", "they", "them", "his",
            "her", "their", "my", "your", "our", "what", "which", "who", "whom",
            "how", "when", "where", "why", "not", "no", "nor", "but", "or",
            "and", "if", "then", "so", "than", "too", "very", "just", "more",
            "most", "some", "any", "all", "each", "every", "both", "few", "many",
            "much", "such", "own", "other", "i", "me", "we", "you", "up", "out",
            "get", "got", "like", "also", "tell", "think", "know", "say", "said",
            "does", "make", "go", "going", "want", "really", "right",
        }

        # Only extract keywords from the first N chars to avoid O(n) explosion
        extract_text = question[:settings.max_keyword_extract_chars].lower()
        words = re.findall(r'\b[a-zA-Z]{3,}\b', extract_text)
        keywords = [w for w in words if w not in stop_words]

        if not keywords:
            keywords = words[:5]

        if not keywords:
            return []

        # Limit to top N most frequent keywords
        keyword_counts = Counter(keywords)
        keywords = [w for w, _ in keyword_counts.most_common(settings.max_keywords)]

        # Search all content items for keyword matches
        all_items = db.exec(
            select(ContentItem)
            .where(col(ContentItem.platform_id).in_(platform_ids))
        ).all()

        scored_items = []
        for item in all_items:
            # Build searchable text from transcript + caption + title
            searchable = " ".join([
                (item.transcript or "").lower(),
                (item.caption or "").lower(),
                (item.title or "").lower(),
            ])

            # Score by keyword frequency
            score = 0
            for kw in keywords:
                count = searchable.count(kw)
                if count > 0:
                    score += count

            if score > 0:
                platform = db.get(Platform, item.platform_id)
                scored_items.append((item, score, platform))

        # Sort by score descending
        scored_items.sort(key=lambda x: x[1], reverse=True)
        return scored_items[:max_results]

    def _format_item_full(self, item: ContentItem, platform: Optional[Platform], transcript_limit: int = 8000) -> str:
        """Format a content item with FULL transcript for the AI context."""
        platform_label = f"{platform.type}:{platform.handle}" if platform else item.type
        parts = [f"[{platform_label}] {item.title or item.external_id}"]
        if item.url:
            parts.append(f"URL: {item.url}")
        parts.append(f"Stats: {item.views} views, {item.likes} likes, {item.comments} comments")
        if item.timestamp:
            parts.append(f"Date: {item.timestamp.strftime('%Y-%m-%d')}")
        if item.caption:
            parts.append(f"Caption: {item.caption[:1000]}")
        if item.transcript and item.transcript != item.caption:
            transcript = item.transcript[:transcript_limit]
            parts.append(f"Full Transcript: {transcript}")
        return "\n".join(parts)

    def _format_item_summary(self, item: ContentItem, platform: Optional[Platform]) -> str:
        """Format a content item as a brief summary."""
        platform_label = f"{platform.type}:{platform.handle}" if platform else item.type
        parts = [f"[{platform_label}] {item.title or item.external_id}"]
        if item.url:
            parts.append(f"URL: {item.url}")
        parts.append(f"Stats: {item.views} views, {item.likes} likes, {item.comments} comments")
        if item.timestamp:
            parts.append(f"Date: {item.timestamp.strftime('%Y-%m-%d')}")
        if item.caption:
            parts.append(f"Caption: {item.caption[:500]}")
        if item.transcript and item.transcript != item.caption:
            parts.append(f"Transcript excerpt: {item.transcript[:2000]}")
        return "\n".join(parts)

    def _get_history(self, session_id: int, db: Session) -> list[ChatMessage]:
        """Get recent conversation history."""
        messages = db.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(settings.chat_history_limit)
        ).all()
        return list(reversed(messages))

    async def generate_creator_summary(self, creator_id: int, db: Session) -> str:
        """Auto-generate a creator summary after scraping."""
        creator = db.get(Creator, creator_id)
        if not creator:
            return ""

        # Get sample content across all platforms
        platform_ids = [p.id for p in creator.platforms]
        if not platform_ids:
            return ""

        items = db.exec(
            select(ContentItem)
            .where(col(ContentItem.platform_id).in_(platform_ids))
            .order_by(ContentItem.views.desc())
            .limit(20)
        ).all()

        if not items:
            return ""

        context_parts = []
        for item in items:
            platform = db.get(Platform, item.platform_id)
            context_parts.append(
                f"[{platform.type if platform else 'unknown'}] {item.title or item.external_id}\n"
                f"Caption: {(item.caption or '')[:300]}\n"
                f"Transcript: {(item.transcript or '')[:300]}\n"
                f"Stats: {item.views} views, {item.likes} likes\n---"
            )

        prompt = f"""Analyze the following content from creator "{creator.name}" and write a concise summary (3-5 paragraphs) covering:
1. Main themes and topics
2. Content style and format patterns
3. Engagement patterns (what performs well)
4. Platform-specific observations
5. Key takeaways

Content sample (top 20 by views):
{chr(10).join(context_parts)}"""

        response = await self.anthropic.messages.create(
            model=settings.claude_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        summary = response.content[0].text

        creator.summary = summary
        creator.summary_generated_at = datetime.utcnow()
        db.add(creator)
        db.commit()

        return summary
