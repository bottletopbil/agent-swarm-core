#!/bin/bash

# Navigate to the correct directory
cd "$(dirname "$0")"

echo "🐝 Starting CAN Swarm Core Services..."

# Create a logs directory
mkdir -p logs

# Export PYTHONPATH so the scripts can find imports from src/
export PYTHONPATH=$PWD/src

# Function to start a python script in the background
start_service() {
    local script=$1
    local name=$2
    
    echo "Starting $name... (Logging to logs/$name.log)"
    .venv/bin/python3 "src/$script" > "logs/$name.log" 2>&1 &
    
    # Save the Process ID (PID)
    echo $! >> logs/pids.txt
}

# Clear old PIDs if any
> logs/pids.txt

# Start NATS with JetStream
echo "Starting nats-server (JetStream)... (Logging to logs/nats.log)"
mkdir -p nats_data
nats-server -js -sd nats_data > logs/nats.log 2>&1 &
echo $! >> logs/pids.txt
sleep 2 # Let NATS initialize before agents start

# Start all services
start_service "dashboard.py" "dashboard"
start_service "coordinator.py" "coordinator"
start_service "planner.py" "planner"
start_service "worker.py" "worker"
start_service "verifier.py" "verifier"

echo ""
echo "✅ All 5 services have been started in the background."
echo "🌍 Dashboard is running at http://localhost:8000"
echo ""
echo "To view logs for a specific service, run:"
echo "  tail -f logs/planner.log"
echo "  tail -f logs/coordinator.log"
echo ""
echo "To stop all services, run: ./stop_swarm.sh"
