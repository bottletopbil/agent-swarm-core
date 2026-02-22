# CAN Swarm Core

An orchestrator-free, auditable, decentralized multi-agent protocol.

## Overview
This repository contains the `agent-swarm-core` minimal viable product (v2). It serves as the local-first engine proving the foundational multi-agent mechanics for the CAN Swarm protocol before scaling out to a fully distributed, partition-tolerant network.

The ultimate research goal of the CAN Swarm protocol (v0.2) is to build an orchestrator-free ecosystem where small "minds" (tools, LLM-backed services, or hybrids) self-organize via a shared plan log, market-style negotiation, and quorum verification—with binding policies, cost efficiency, and a path to an open agent economy.

## Current Architecture
Currently, the system is in **Phase 8**. It operates as a fully asynchronous, distributed framework orchestrating agents over a NATS JetStream event bus, dropping legacy local queues while writing to a persistent SQLite State Tracker and an Immutable Audit Log.

It consists of 5 decoupled services communicating via NATS:
*   **Coordinator**: The orchestrator that routes `PENDING` and `LOCKED` tasks to the appropriate NATS subject, managing DAG dependency resolution.
*   **Planner Agent**: Breaks down complex tasks into granular sub-tasks, organizing them into a Directed Acyclic Graph (DAG) for optimized parallel and sequential execution.
*   **Worker Agent**: Executes specific prompts against the LLM (currently OpenAI gpt-5-nano).
*   **Verifier Agent**: A pragmatic reviewer that analyzes Worker outputs against the core objective, returning a Pass/Fail verdict.
*   **Observation Dashboard**: A live FastAPI/HTML dashboard at `localhost:8000` to visualize the NATS event bus traffic and inspect the DAG.

## Setup & Usage
Ensure you have an `OPENAI_API_KEY` in your `.env` file.

```bash
# Set up environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start all 5 CAN Swarm services in the background
./start_swarm.sh

# Open the dashboard
open http://localhost:8000

# Stop the services
./stop_swarm.sh

# Wipe the database and restart fresh
./reset_swarm.sh
```

## Protocol Roadmap (SwarmPlan02)
This Minimal Viable Product proves the core LLM execution loop. In upcoming phases, the central Coordinator and SQLite database will be deprecated in favor of:

1.  **NATS Event Bus**: Replacing local queues with JetStream pub/sub. (Complete)
2.  **Immutable Audit Logging**: Append-only traces of every Envelope and Action. (Complete)
3.  **Cryptographic Signatures**: Ed25519 keys for every Agent, moving to a Trustless network.
4.  **Consensus & Conflict Resolution**: Scoped consensus per NEED, Lamport Clocks, and deterministic merge rules for Partition Tolerance (AP planning layer, CA finalization).
5.  **Result Quorum & Challenge Protocol**: Verification bounds where results are only finalized after a challenge window elapses without dispute.
6.  **Distributed Economics**: Staked Verifier Pools, credits, and gas-metered execution to prevent DoS.
