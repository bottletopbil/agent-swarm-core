# CAN Swarm: Production-Grade Ruggedness Testing Specification

**Version:** 1.0  
**Target:** AI Developer / Test Engineer  
**Philosophy:** "Assume the network is hostile, the hardware is failing, and the agents are lying."

> **MASTER INSTRUCTION FOR AI:** > When generating these tests:
> 1. Use `pytest` and `pytest-asyncio`.
> 2. Use `subprocess` to spawn distinct agent processes so they can be killed/isolated independently.
> 3. Use `tc` (Traffic Control) or generic proxy mocks to simulate network latency/partitions.
> 4. Use the actual project wrappers (e.g., `nats_bus.py`, `database.py`) rather than mocking the infrastructure, unless explicitly told otherwise.
> 5. Use the `hypothesis` library (specifically the `@given` and `strategies` modules) to perform property-based testing and generate diverse, fuzzy inputs for JSON envelopes.
> 6. Do not mock the *logic* being tested. Mock only external costs (like OpenAI API calls) to save money, unless the test is specifically about the API connection.

---

## Part 1 & 2: The Local Engine & Queues (Phases 1-6)
*Goal: Ensure the core state machine and local queues cannot be corrupted by abrupt termination, schema violations, or unexpected LLM behavior.*

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P3-1** | **Connection Exhaustion** | Spawn 100 concurrent asynchronous threads that attempt to write to the `tasks` SQLite table simultaneously. | The system gracefully queues the writes or uses connection pooling. It must NOT throw `sqlite3.OperationalError: database is locked`. |
| **P3-2** | **The Hard Crash** | Send a SIGKILL (`kill -9`) to the Coordinator process immediately after an LLM returns a result, but before the DB commit finishes. | Upon restart, the Coordinator detects the uncommitted state and re-verifies the task, rather than leaving it perpetually `WORKING`. |
| **P5-1** | **Dead-Letter Routing** | Inject a task payload that strictly violates the Pydantic schema (e.g., nested arrays where strings are expected). | The Worker rejects the task and routes it to a Dead Letter Queue (DLQ) or marks it `FAILED` without crashing the main `asyncio` listener loop. |
| **P6-1** | **Orphan Child Tasks** | A Planner creates 3 sub-tasks. Forcefully and permanently fail the 2nd sub-task. | The parent task transitions to `FAILED` or `RETRY`. The 1st and 3rd sub-tasks must be safely halted or their results discarded. |

---

## Part 3: The Distributed System (Phases 7-8)
*Goal: Ensure the communication layer is resilient to message loss, flooding, and corruption.*

### Phase 7: NATS Event Bus (The Nervous System)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P7-1** | **Idempotency (Double-Tap)** | Publish the exact same `TaskID` envelope twice to `tasks.worker` within 10ms. | Worker acknowledges both but executes the LLM call/DB write **exactly once**. |
| **P7-2** | **The Poison Pill** | Inject a payload of random binary bytes (non-JSON) into the `tasks.>` stream. | Consumer catches deserialization error, calls `msg.term()` to remove it from JetStream, and does not crash. |
| **P7-3** | **Slow Consumer** | Start a Worker that pulls a task but `sleeps` for longer than the NATS `AckWait`. | NATS JetStream detects the timeout and redelivers the message to a *different* available Worker. |
| **P7-4** | **Connection Storm** | Rapidly connect/disconnect the Worker from NATS (or restart `nats-server` abruptly) while it is processing. | Worker reconnects automatically with a backoff-retry loop; no partial state is written to DB; task is eventually finished. |
| **P7-5** | **The Flood (DoS)** | Publish 500 tasks in 1 second. | System does not crash. SQLite does not lock up (WAL mode check). Processing continues at a stable rate (Backpressure). |
| **P7-6** | **Property-Based Fuzzing** | Use `hypothesis` to generate 1,000 highly randomized, malformed JSON strings, pushing them to the `tasks.>` subject. | The `nats_bus.py` wrapper intercepts parser errors, calls `msg.term()`, and keeps the main consumer loop alive. |

### Phase 8: Immutable Audit Logging (The Memory)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P8-1** | **The Gap (Stream Replay)** | Kill the Audit Daemon for 15 seconds. Run 50 tasks. Restart Audit Daemon. | Daemon detects the gap in `stream_seq` and fetches missing messages from JetStream history. Zero missing logs. |
| **P8-2** | **Log Tampering Detection** | Manually modify a timestamp or hash in the saved `audit.jsonl` file. | The `verify_audit.py` script fails validation, identifying the exact line where the hash chain broke. |
| **P8-3** | **Disk Pressure** | Simulate a "Disk Full" error when writing the audit log. | Auditor crashes safely or alerts; does NOT silently drop messages. NATS retains messages until Auditor recovers. |

---

## Part 4: The Trustless Network (Phases 9-11)
*Goal: Ensure cryptographic integrity and deterministic state regardless of agent lies or duplicate claims.*

### Phase 9: Cryptographic Signatures (The Identity)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P9-1** | **The Impersonator** | Capture a valid message. Change the `sender_id` in the JSON. Keep the original signature. | Coordinator rejects message: "Signature verification failed." |
| **P9-2** | **Malleability Attack** | Intercept a valid envelope. Alter the whitespace/formatting of the JSON payload without changing keys/values, then republish. | Coordinator rejects the message, proving signatures cover strict byte-representation. |
| **P9-3** | **The Replay Attack** | Capture a valid, signed "Task Done" message. Wait 10 minutes. Send it again. | Rejected based on an expired Lamport clock, a duplicated Nonce, or an expired timestamp window. |
| **P9-4** | **Signature Flooding** | Send 1,000 messages with garbage signatures to the Verifier. | Verifier drops them cheaply (CPU usage check). Valid messages in the queue are still processed. |

### Phase 10: Consensus & Locking (The Traffic Cop)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P10-1** | **The Race Condition** | 5 Agents attempt to claim the same `TaskID` via Redis/NATS lock at the exact same millisecond. | Only **one** acquires the lock. The others receive "Lock Failed" and back off. |
| **P10-2** | **The Zombie Lock** | Worker A successfully acquires the lock, then its process is `kill -9`'d immediately. | The lock automatically expires after TTL (e.g., 30s). Worker B can eventually claim the task. |
| **P10-3** | **The Fencing Token** | Worker A pauses for 31s (lock expires). Worker B claims task. Worker A wakes up and tries to write result. | Database rejects Worker A's write because the "Lock Generation ID" (Fencing Token) has changed. |
| **P10-4** | **Clock Skew** | Manually set Worker A's system clock 10 minutes into the future. | Lamport Clocks preserve causal ordering of the distributed plan log. Protocol does not rely solely on `system_time`. |

### Phase 11: Content-Addressable Storage (The Library)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P11-1** | **The Missing Link** | Send a NATS message pointing to a Hash that does not exist in the CAS. | Verifier flags "Artifact Missing" error immediately; does not hang waiting for download. |
| **P11-2** | **Corrupted Blob** | Manually change 1 byte of a file in the CAS storage. | When Worker B fetches it, the SHA-256 check fails. Worker B refuses to use the file. |
| **P11-3** | **Oversized Artifact** | Worker tries to upload a 5GB file to CAS (exceeding limit). | Upload is rejected *before* network bandwidth is wasted. Error returned to Agent. |

---

## Part 5: Production Readiness (Phases 12-13)
*Goal: Validate that the financial and sandbox boundaries cannot be breached.*

### Phase 12: Distributed Economics (The Wallet)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P12-1** | **The Sybil** | An Agent attempts to verify a task generated by another Agent with the exact same `OwnerID`, `ASN`, or `IP`. | Consensus rejects the Verifier assignment due to Diversity Policy and slashes the Verifier's stake for attempted collusion. |
| **P12-2** | **Insufficient Funds** | Agent with 0 Credits tries to bid on a task requiring a Stake. | Bid rejected immediately. |
| **P12-3** | **Double Spend** | Agent tries to send its Credits to two different wallets in the same block/cycle. | Ledger records only the first transaction; second fails. |

### Phase 13: Sandboxing (The Jail)

| Test ID | Name | Scenario | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **P13-1** | **The Jailbreak** | Task code attempts to read `/etc/passwd` or access `os.environ`. | Sandbox (Docker/WASM) blocks the syscall. Task fails with "Security Violation". |
| **P13-2** | **The Infinite Loop** | Submit a Policy Capsule with `while(true) {}`. | WASM runtime tracks instruction count ("gas") and forcibly terminates execution. Main agent process must *not* lock up. |
| **P13-3** | **Memory Bomb** | Task code attempts to allocate 10GB of RAM. | Container OOM-kills the task instantly. System remains stable. |
| **P13-4** | **Network Exfiltration** | Task code tries to `curl` a private IP (e.g., AWS Metadata `169.254...`). | Network namespace prevents outbound connections (except explicit allowlist). |