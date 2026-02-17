#!/bin/bash
# Start Content Analyzer with a Cloudflare Tunnel for remote access
# Your wife can access the app from anywhere via the tunnel URL

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Content Analyzer v2 (with Tunnel) ==="
echo ""

# Kill anything on our ports
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
lsof -ti :3000 | xargs kill -9 2>/dev/null || true
sleep 1

# Start backend
echo "Starting backend..."
cd "$DIR"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend..."
cd "$DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Wait for servers to be ready
echo "Waiting for servers..."
sleep 5

# Start Cloudflare Tunnel pointing to the frontend
# The frontend already proxies /api/* to the backend
echo ""
echo "Starting Cloudflare Tunnel..."
echo "============================================"
cloudflared tunnel --url http://localhost:3000 2>&1 &
TUNNEL_PID=$!

# Wait a moment for the tunnel URL to appear
sleep 4
echo "============================================"
echo ""
echo "Share the https://*.trycloudflare.com URL above with your wife!"
echo ""
echo "Local access:"
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop everything."

# Trap Ctrl+C to kill all
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $TUNNEL_PID $FRONTEND_PID $BACKEND_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM
wait
