#!/bin/bash

# Exit on errors
set -e

# Run both the frontend and backend concurrently
echo "🚀 Starting frontend (pnpm dev) and backend (python core/compiler.py)..."

# Start the frontend
pnpm dev &
FRONTEND_PID=$!

# Start the backend
python3 core/compiler.py &
BACKEND_PID=$!

# Trap Ctrl+C (SIGINT) and terminate both processes gracefully
trap "echo '🛑 Stopping both processes...'; kill $FRONTEND_PID $BACKEND_PID; exit 0" SIGINT

# Wait for both processes to complete
wait
