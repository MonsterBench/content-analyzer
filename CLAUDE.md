# Content Analyzer v2

## What

Full-stack app for analyzing social media creators across YouTube and Instagram. Scrapes channel content, transcribes videos, builds AI knowledge bases (creator profiles, topic clusters, style analysis), and provides a RAG-powered chat interface for querying across all of a creator's content.

## Tech Stack

- **Backend:** FastAPI (Python 3.12), SQLModel/SQLAlchemy, SQLite (WAL mode)
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4
- **AI:** Claude (Anthropic) for chat/analysis, OpenAI for embeddings + Whisper transcription
- **Scraping:** yt-dlp + youtube-transcript-api (YouTube), Apify (Instagram)
- **Scheduling:** APScheduler (async cron jobs)
- **Deployment:** Railway (two Docker services: backend + frontend)

## Project Structure

```
backend/
  config.py          -- Centralized settings via pydantic-settings
  main.py            -- FastAPI app entry point, lifespan, CORS, router registration
  models/database.py -- All SQLModel tables + engine + session factory
  routers/           -- API endpoints (creators, chat, scrape, schedule, knowledge)
  services/          -- Business logic (ai_chat, embeddings, youtube_scraper, instagram_scraper, knowledge, transcriber, scheduler)
frontend/
  src/lib/api.ts     -- Typed API client, all interfaces, SSE stream readers
  src/app/           -- Next.js pages (dashboard, creators, chat, compare)
  src/app/api/       -- Proxy routes forwarding to backend
```

## Data Model

```
Creator -> Platform(s) -> ContentItem(s)
Creator -> ScrapeJob(s)
Creator -> ChatSession(s) -> ChatMessage(s)
Creator -> CreatorKnowledge (profile | topics | style)
```

All models defined in `backend/models/database.py`.

## Key Commands

```bash
# Local development (starts both services)
./start.sh

# Backend only
python3 -m uvicorn backend.main:app --reload --port 8000

# Frontend only
cd frontend && npm run dev

# Install backend deps
pip install -r requirements.txt

# Install frontend deps
cd frontend && npm install
```

## Important Conventions

### Adding a New Feature or Fixing Bugs

**IMPORTANT**: When you work on a new feature or bug, create a git branch first.
Then work on changes in that branch for the remainder of the session.

1. Add SQLModel table(s) in `backend/models/database.py`
2. Create service class in `backend/services/`
3. Create router in `backend/routers/` with Pydantic request/response models
4. Register router in `backend/main.py`
5. Add TypeScript interfaces + fetch functions in `frontend/src/lib/api.ts`
6. Create page in `frontend/src/app/`

### Frontend-Backend Communication
All browser requests go through Next.js API routes (`frontend/src/app/api/[...path]/route.ts`), which proxy to the FastAPI backend. The browser never calls the backend directly. `BACKEND_URL` env var configures the proxy target (defaults to `http://localhost:8000`).

### Database Sessions
- Route handlers: use `db: Session = Depends(get_session)` -- `backend/models/database.py:122`
- Background tasks: create their own session with `Session(engine)` since they outlive requests
- Always `db.add()` + `db.commit()` + `db.refresh()` for writes

### Streaming Responses
- Chat and knowledge generation use SSE (`StreamingResponse` with `text/event-stream`)
- Scrape progress uses WebSocket (`/ws/scrape/{job_id}`) with polling fallback
- Frontend reads SSE via `ReadableStream` reader in `frontend/src/lib/api.ts`

### Vector Store
JSON-file-based (not ChromaDB) at `chroma_data/creator_{id}.json`. Uses OpenAI `text-embedding-3-small`. See `backend/services/embeddings.py`.

## Environment Variables

Required: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
Optional: `APIFY_API_TOKEN` (Instagram only), `DATABASE_URL`, `CHROMA_PERSIST_DIR`, `DEBUG`
Frontend: `BACKEND_URL` (deployment only)

## No Tests

There are no tests in this project. No test framework is configured.

## Additional Documentation

When working on tasks related to these topics, consult:

- **[Architectural Patterns](.claude/docs/architectural_patterns.md)** -- API design, service patterns, RAG pipeline, streaming, background tasks, state management
