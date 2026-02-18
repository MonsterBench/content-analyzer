# Architectural Patterns

## 1. Router + Service + Model Pattern

Every feature follows a three-layer architecture:

- **Model** (`backend/models/database.py`) -- SQLModel table with relationships
- **Service** (`backend/services/`) -- Stateless class with business logic, receives `db: Session` as parameter
- **Router** (`backend/routers/`) -- Thin HTTP layer with Pydantic request/response schemas defined inline

Services are instantiated as **module-level singletons** in routers:
- `backend/routers/chat.py:16` -- `chat_service = AIChatService()`
- `backend/routers/scrape.py:24-27` -- `ig_scraper`, `yt_scraper`, `transcriber`, `knowledge_svc`

Services do NOT use FastAPI dependency injection. They are plain classes; only the DB session uses `Depends(get_session)`.

## 2. Router Prefix Conventions

Routers use inconsistent prefix strategies (be aware when adding new ones):
- `backend/routers/creators.py:14` -- `prefix="/api/creators"` with relative paths in decorators
- `backend/routers/chat.py:14` -- `prefix="/api"` with relative paths
- `backend/routers/schedule.py` -- `prefix="/api/schedule"`
- `backend/routers/knowledge.py` -- No prefix, full paths in each decorator (`"/api/creators/{creator_id}/knowledge"`)

## 3. Pydantic Schema Pattern

Request/response models are defined as inner classes in each router file, NOT shared:
- `backend/routers/creators.py:17-36` -- `CreatorCreate`, `PlatformCreate`, `CreatorOut`
- `backend/routers/scrape.py:30-43` -- `ScrapeRequest`, `ScrapeJobOut`
- `backend/routers/chat.py:17-47` -- `ChatSessionOut`, `ChatMessageRequest`, etc.

When a model needs to be exposed via API, create a separate Pydantic `BaseModel` rather than returning the SQLModel directly.

## 4. Background Task Pattern

Two mechanisms are used for different purposes:

**On-demand tasks** (`asyncio.create_task`):
- `backend/routers/scrape.py:75` -- Fire-and-forget scrape jobs
- The task function creates its own `Session(engine)` context
- Progress is broadcast via WebSocket or SSE
- State is tracked in a DB row (`ScrapeJob.status`)

**Scheduled tasks** (APScheduler):
- `backend/services/scheduler.py:134-138` -- Cron-triggered scrapes
- `AsyncIOScheduler` with `CronTrigger` for weekly/monthly
- Schedules loaded from DB at startup via `sync_schedules()`

## 5. SSE Streaming Pattern

Used for chat responses and knowledge generation. The pattern repeats across files:

**Backend** (`backend/routers/chat.py:88-110`, `backend/routers/knowledge.py`):
```
1. Define async generator that yields SSE-formatted strings
2. Yield heartbeat comment first (": heartbeat\n\n")
3. Yield data lines: f"data: {json.dumps(payload)}\n\n"
4. Yield final "done" event
5. Return StreamingResponse(generator, media_type="text/event-stream")
```

**Frontend** (`frontend/src/lib/api.ts:216-262`):
```
1. Call fetch() normally
2. Get ReadableStream reader from res.body
3. Decode chunks, split on newlines
4. Parse lines starting with "data: " as JSON
5. Call onChunk callback with content
```

Headers always include: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`

## 6. RAG Chat Pipeline (3-Tier Context)

The chat system in `backend/services/ai_chat.py` builds context in three tiers:

**Tier 1 -- Pre-computed knowledge** (`ai_chat.py:_build_context`):
- CreatorKnowledge entries (profile, topics, style)
- Full content catalog (all videos with summaries)
- Budget: ~40K chars for catalog

**Tier 2 -- Hybrid retrieval** (`ai_chat.py:_keyword_search`, `_semantic_search`):
- Keyword: stop-word-filtered, frequency-scored across transcripts, top 5
- Semantic: OpenAI embeddings via `EmbeddingsService`, cosine similarity, top 5
- Results are deduplicated and full transcripts included
- Budget: ~60K chars for transcripts

**Tier 3 -- Aggregate stats**:
- Total items, average views/likes/comments

System prompt is assembled with hard character budget guards (120K total) and truncation.

## 7. Frontend State Pattern

No state management library. Every page uses the same imperative pattern:

```
1. useState for data, loading, error states
2. useEffect on mount -> call api function -> setState
3. useCallback for data-loading functions that depend on filter/sort state
4. Direct api.ts calls in event handlers -> setState with response
```

Streaming state uses `useRef` for the accumulating buffer (avoids stale closure issues) + `useState` for display:
- `frontend/src/app/chat/page.tsx` -- `streamingTextRef` (ref) + `streamingDisplay` (state)

## 8. Incremental Scraping Pattern

Both scrapers follow the same deduplication approach:

1. Query existing `ContentItem.external_id` for the platform
2. Fetch remote content list
3. Filter out already-existing IDs
4. Process only new items
5. Save each item to DB immediately (incremental commits)
6. Update `platform.last_scraped_at`

See: `backend/services/youtube_scraper.py:48-51`, `backend/services/instagram_scraper.py`

## 9. Knowledge Generation Pipeline

Four sequential stages, each using Claude (`backend/services/knowledge.py`):

1. **Batch summaries** -- Process unsummarized videos 10 at a time, generate 1-2 sentence summaries
2. **Topic clusters** -- Analyze all summaries to identify 5-10 recurring themes
3. **Creator profile** -- Synthesize clusters + top content + stats into a profile
4. **Style analysis** -- Sample 15 diverse transcripts, analyze communication patterns

Each stage upserts a versioned `CreatorKnowledge` row. Progress is streamed via SSE.

## 10. Proxy Architecture

The frontend never exposes the backend URL to the browser:

```
Browser -> Next.js (/api/*) -> FastAPI (BACKEND_URL/api/*)
```

Three proxy routes handle this:
- `frontend/src/app/api/[...path]/route.ts` -- Catch-all for all methods, detects and streams SSE
- `frontend/src/app/api/chat/[sessionId]/messages/route.ts` -- Dedicated chat SSE proxy
- `frontend/src/app/api/chat/[sessionId]/messages/upload/route.ts` -- Dedicated multipart upload proxy

The dedicated routes exist because they were created before the catch-all and handle SSE headers explicitly. The catch-all also handles SSE, so the dedicated routes are redundant but harmless.

## 11. Manual Migration Pattern

No migration tool (no Alembic). Schema changes are handled at startup:

`backend/main.py:20-29` -- `_run_migrations()` checks for column existence via `SELECT`, catches the exception, then runs `ALTER TABLE ADD COLUMN`. This runs on every startup and is idempotent.
