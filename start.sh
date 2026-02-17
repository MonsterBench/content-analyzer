#!/bin/bash
# Start both backend and frontend for Content Analyzer v2

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Content Analyzer v2 ==="
echo ""

# Check if ports are in use
if lsof -i :8000 &>/dev/null; then
    echo "Warning: Port 8000 already in use. Kill existing process first."
fi
if lsof -i :3000 &>/dev/null; then
    echo "Warning: Port 3000 already in use. Kill existing process first."
fi

# Start backend
echo "Starting backend on :8000..."
cd "$DIR"
python3 -m uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend on :3000..."
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:  http://localhost:8000  (API docs: http://localhost:8000/docs)"
echo "Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."

# Trap Ctrl+C to kill both
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
