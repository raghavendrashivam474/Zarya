#!/bin/bash
# ZARYA — Start Script (Linux)
# Ensure we're in the project root (parent of scripts/)
cd "/.." || exit 1

# Kill any ghost background processes holding ports
pkill -f "uvicorn agent.server:app" 2>/dev/null || true

echo "Starting ZARYA..."
echo "=========================================================="

# 1. Start Python Agent Background Process
echo ">>> Starting Python Core Agent on Port 8765..."
if [ -f "./venv/bin/python" ]; then
    ./venv/bin/python scripts/run_agent.py &
elif [ -f "./.venv/bin/python" ]; then
    ./.venv/bin/python scripts/run_agent.py &
else
    python3 scripts/run_agent.py &
fi
PYTHON_PID=$!

sleep 2

# 2. Start Node server (and Vite Dev frontend)
echo ">>> Starting Node WebSocket Server & Vite Frontend..."
npm run dev &
NODE_PID=$!

echo ""
echo "=========================================================="
echo "ZARYA is running!"
echo "Open your browser at: http://localhost:3000"
echo "Press Ctrl+C to stop everything."
echo "=========================================================="

trap "echo 'Stopping ZARYA...'; kill   2>/dev/null; exit" SIGINT SIGTERM

wait
