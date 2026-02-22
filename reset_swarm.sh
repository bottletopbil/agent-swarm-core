#!/bin/bash

cd "$(dirname "$0")"

echo "🧹 Resetting CAN Swarm Core..."

# Stop existing services
./stop_swarm.sh

# Remove the database to start completely fresh
if [ -f "swarm_state.db" ]; then
    echo "🗑️  Deleting old database (swarm_state.db)..."
    rm swarm_state.db
fi

# Clear old logs for a fresh start
if [ -d "logs" ]; then
    echo "🗑️  Clearing old logs..."
    rm -rf logs/*
fi

if [ -d "nats_data" ]; then
    echo "🗑️  Clearing NATS Event Bus data..."
    rm -rf nats_data
fi

echo "✨ Reset complete. Restarting services..."

# Start services again
./start_swarm.sh
