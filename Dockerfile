# Backend Dockerfile (FastAPI)
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ backend/

# Create data directory for SQLite + vector store
RUN mkdir -p /data

ENV DATABASE_URL=sqlite:////data/content_analyzer.db
ENV CHROMA_PERSIST_DIR=/data/chroma_data
ENV DEBUG=false

ENV PORT=8000
EXPOSE 8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
