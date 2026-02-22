#!/bin/bash

cd "$(dirname "$0")"

echo "🛑 Stopping CAN Swarm Core Services..."

if [ -f "logs/pids.txt" ]; then
    # Read each PID and kill it
    while read pid; do
        if kill -0 $pid 2>/dev/null; then
            echo "Killing process $pid"
            kill $pid 2>/dev/null || true
        fi
    done < logs/pids.txt
    
    # Remove the pid tracking file
    rm logs/pids.txt
fi

echo "Cleaning up any stranded processes..."
pkill -f "nats-server" || true
pkill -f "src/dashboard.py" || true
pkill -f "src/coordinator.py" || true
pkill -f "src/planner.py" || true
pkill -f "src/worker.py" || true
pkill -f "src/verifier.py" || true

echo "✅ All services stopped."
