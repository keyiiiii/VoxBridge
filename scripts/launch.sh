#!/bin/bash
# Launch VoxBridge (background, with log)
# Usage: ./scripts/launch.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Use project venv if available, otherwise use Application Support runtime
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
    RUNTIME_DIR="$PROJECT_DIR"
elif [ -x "$HOME/Library/Application Support/VoxBridge/venv/bin/python" ]; then
    VENV_PYTHON="$HOME/Library/Application Support/VoxBridge/venv/bin/python"
    RUNTIME_DIR="$HOME/Library/Application Support/VoxBridge"
else
    echo "Error: No Python venv found. Run: python3 -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

LOG_FILE="$HOME/Library/Logs/VoxBridge.log"

# Kill any existing VoxBridge process
pkill -f "python.*voxbridge" 2>/dev/null

echo "Starting VoxBridge..."
echo "  Runtime: $RUNTIME_DIR"
echo "  Log: $LOG_FILE"

export PYTHONUNBUFFERED=1
cd "$RUNTIME_DIR"
nohup "$VENV_PYTHON" -m voxbridge --preload > "$LOG_FILE" 2>&1 &
PID=$!
echo "  PID: $PID"
echo "$PID" > /tmp/voxbridge.pid

# Wait a moment and check if it started
sleep 2
if kill -0 "$PID" 2>/dev/null; then
    echo "VoxBridge is running. Check menu bar for 'VB'."
    echo "Stop with: kill \$(cat /tmp/voxbridge.pid)"
else
    echo "Error: VoxBridge failed to start. Check log:"
    tail -10 "$LOG_FILE"
fi
