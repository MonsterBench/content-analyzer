"""Embeddings service using OpenAI embeddings with JSON-file-based vector store.

Uses cosine similarity for search. Avoids ChromaDB which has Python 3.14 compatibility issues.
"""

import json
import logging
import math
from pathlib import Path
from typing import Optional

from openai import OpenAI
from sqlmodel import Session, select

from backend.config import settings
from backend.models.database import ContentItem, Platform, Creator

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingsService:
    def __init__(self):
        self.openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.store_dir = Path(settings.chroma_persist_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _store_path(self, creator_id: int) -> Path:
        return self.store_dir / f"creator_{creator_id}.json"

    def _load_store(self, creator_id: int) -> dict:
        path = self._store_path(creator_id)
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return {"items": []}

    def _save_store(self, creator_id: int, store: dict):
        path = self._store_path(creator_id)
        with open(path, "w") as f:
            json.dump(store, f)

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings from OpenAI."""
        if not self.openai_client:
            raise ValueError("OpenAI API key required for embeddings")

        results = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch = [t[:8000] for t in batch]
            response = self.openai_client.embeddings.create(
                model=settings.embedding_model,
                input=batch,
            )
            results.extend([d.embedding for d in response.data])
        return results

    def embed_content_items(self, items: list[ContentItem], creator_id: int, db: Session):
        """Embed content items into the vector store for a creator."""
        if not items:
            return

        store = self._load_store(creator_id)
        existing_ids = {entry["id"] for entry in store["items"]}

        docs = []
        new_entries = []

        for item in items:
            if item.is_embedded:
                continue
            entry_id = f"content_{item.id}"
            if entry_id in existing_ids:
                continue

            text = _build_document_text(item, db)
            if not text.strip():
                continue

            docs.append(text)
            new_entries.append({
                "id": entry_id,
                "document": text,
                "metadata": {
                    "content_id": item.id,
                    "type": item.type,
                    "platform_id": item.platform_id,
                    "external_id": item.external_id,
                    "likes": item.likes,
                    "views": item.views,
                    "comments": item.comments,
                    "duration": item.duration,
                    "timestamp": item.timestamp.isoformat() if item.timestamp else "",
                },
            })

        if not docs:
            return

        embeddings = self._embed_texts(docs)

        for entry, embedding in zip(new_entries, embeddings):
            entry["embedding"] = embedding
            store["items"].append(entry)

        self._save_store(creator_id, store)

        for item in items:
            item.is_embedded = True
            db.add(item)
        db.commit()

        logger.info(f"Embedded {len(docs)} items for creator {creator_id}")

    def search(
        self,
        creator_id: int,
        query: str,
        n_results: int = 10,
    ) -> list[dict]:
        """Semantic search across a creator's content."""
        store = self._load_store(creator_id)
        if not store["items"]:
            return []

        query_embedding = self._embed_texts([query])[0]

        scored = []
        for entry in store["items"]:
            if "embedding" not in entry:
                continue
            sim = _cosine_similarity(query_embedding, entry["embedding"])
            scored.append((sim, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, entry in scored[:n_results]:
            results.append({
                "id": entry["id"],
                "document": entry["document"],
                "metadata": entry["metadata"],
                "distance": 1.0 - sim,
            })

        return results

    def delete_creator_collection(self, creator_id: int):
        """Delete all embeddings for a creator."""
        path = self._store_path(creator_id)
        if path.exists():
            path.unlink()


def _build_document_text(item: ContentItem, db: Session) -> str:
    """Build a rich text document for embedding."""
    platform = db.get(Platform, item.platform_id)
    platform_label = f"{platform.type}:{platform.handle}" if platform else item.type

    parts = [f"[{platform_label}]"]

    if item.title:
        parts.append(f"Title: {item.title}")
    if item.caption:
        parts.append(f"Caption: {item.caption[:2000]}")
    if item.transcript and item.transcript != item.caption:
        parts.append(f"Transcript: {item.transcript[:4000]}")

    parts.append(
        f"Stats: {item.views} views, {item.likes} likes, {item.comments} comments, {item.duration}s"
    )

    if item.timestamp:
        parts.append(f"Date: {item.timestamp.strftime('%Y-%m-%d')}")

    return "\n".join(parts)
