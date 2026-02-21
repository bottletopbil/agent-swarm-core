**CAN Swarm - Protocol Plan (v0.2)**

**Goal (research):** Build an **orchestrator-free**, auditable, decentralized multi-agent protocol where small "minds" (tools, LLM-backed services, or hybrids) self-organize via a **shared plan log**, **market-style negotiation**, and **quorum verification**-with **binding policies**, **cost efficiency (local-first)**, and a path to an **open agent economy**.

**1) System Model & CAP Stance**

- **Partition tolerance is required.** We target **AP** for the _planning_ layer (system remains available and plans may diverge during netsplits), and **CA at finalization boundaries** via quorum (results considered globally consistent only when finalized).
- **Convergence guarantee:** After a partition heals, planning state **converges deterministically** using scoped consensus per slot (see §3.4) and merge rules (§3.5).

**2) Core Data Plane**

**2.1 Envelopes (immutable, signed)**

Every bus message uses a minimal envelope:

id, thread, sender{pubkey, agent_id}, capability, verb,

content_refs\[\], policy_capsule_hash, lamport, timestamp, sig

- **Ed25519 signatures** over the envelope sans sig.
- **Lamport clock** for deterministic causal ordering across peers.

**2.2 Artifact Store (CAS)**

- Content-addressed storage: PUT(bytes) → hXYZ, GET(hXYZ) → bytes.
- Messages carry **hash refs** only (no blobs) → dedupe, caching, tiny prompts.

**2.3 Policy Capsules (binding rules)**

- Signed, non-Turing-complete rules + budgets (default-deny).
- Evaluated at **three gates**: **preflight** (client), **ingress** (every agent), **commit-gate** (verifiers check actual telemetry).
- **Determinism & portability:** Policies ship as **bytecode/WASM module** with a content hash; **all nodes execute the exact same evaluator**.
- **Policy language:** Rego/CUE/Datalog-style (non-Turing); **gas-metered** evaluation to bound runtime. Capsule embeds:
  - policy_engine_hash (WASM/IR),
  - policy_schema_version,
  - optional **conformance vector** (passed test IDs).
- **ATTEST** messages include a **policy evaluation digest** (inputs→decision hash) to surface divergence immediately.

**3) Planning & State**

**3.1 Plan as Op-Log (CRDT discipline)**

Append-only **typed facts**; graph is **derived**, not edited:

- ADD_TASK(T, type, requires\[\], produces\[\])
- REQUIRES(T, artifactType)
- PRODUCES(T, artifactRef)
- STATE(T, DRAFT|VERIFIED|FINAL) (monotone forward only)
- LINK(parent, child) (dependency)
- ANNOTATE(T, key, val) (LWW with (lamport, actor_id))

**CRDT split:** nodes/edges are **G-Sets**; annotations are **LWW registers**; task state is monotone.

**3.2 Negotiation Verbs (Contract-Net lite)**

- NEED{slot_id, epoch, requires, produces, budget}
- PROPOSE{need_id, patch, ballot}
- CLAIM{task_id, lease_ttl, cost, eta}
- YIELD/RELEASE
- UPDATE_PLAN{facts\[\]}
- Time behavior: **leases** (expire unless renewed), **heartbeats** (progress beacons), **randomized backoff** to avoid herds, **bid windows** to limit auctions.

**3.3 Execution & Safety Verbs**

- COMMIT{task_id, outputs_refs\[\], verify_bounty, telemetry}
- ATTEST{task_id, verdict, policy_eval_digest}
- REJECT{task_id, reasons}
- FINALIZE{task_id} (emitted when result quorum holds after challenge window)

**3.4 Scoped Consensus per NEED (splits & netsplits)**

**Unit of exclusivity:** a **NEED slot**.

- **Plan-quorum:** Verifiers use ATTEST_PLAN{need_id, proposal_id} for proposals. First proposal to reach **K_plan** (e.g., 2-3) independent attestations produces DECIDE{need_id, proposal_id}.
- **Epochs & fencing:** NEED carries epoch. Updates must include a **fencing token** for the current epoch. After partition heal, **highest-epoch DECIDE with K_plan** wins; others are invalidated.
- **Determinism:** tie-breakers (epoch, lamport, proposer_id) are total.

**3.5 Merge Handlers (deterministic)**

For **structural conflicts**:

- Keep **decided** branch for the slot (has DECIDE).
- Keep unrelated branches unchanged.
- Tag losing/parallel branches as **orphaned_by_epoch**; allow **salvage** (reattach compatible artifacts as alternates).

**3.6 Partition Recovery & Reconciliation**

- **Speculative branches** can be **retro-validated**; useful work is salvaged (if artifacts have valid ATTESTs).
- New verb: **RECONCILE{thread, summary}** to mark partition heal and attach negotiation metadata (which branches merged, which were orphaned, what was salvaged).

**4) Finality & Challenges**

**4.1 Result Quorum (separate from plan quorum)**

A COMMIT for a task becomes **FINAL** when ≥ **K_result** independent verifiers post ATTEST{pass} and the **challenge window T_challenge** elapses without a valid challenge.

- **Diversity constraint:** Verifiers must come from **distinct providers/orgs/ASNs/regions**. Router enforces this; payouts require diversity-valid committees.

**4.2 Challenge Protocol**

- Any party may post CHALLENGE{task_id, proof} during T_challenge.
- **Proof schema (bounded):** typed classes with fixed/known verification costs (e.g., schema_violation, missing_citation_hash, semantic_contradiction via small model). **Max size** and **gas meter** bound verifier workload.
- **Verification bond:** challenger posts a bond proportional to claimed complexity; slashed for malformed/abusive proofs.
- If upheld: offending **verifiers slashed**, bounty reallocated (challenger + honest verifiers + burn), result **reopened**; router **escalates K_result**.

New verbs: CHALLENGE, INVALIDATE (to mark a result invalid post-challenge).

**5) Economics & Incentives**

**5.1 Credits (fungible) First; Barter Optional**

- **Primary medium:** fungible **credits** (buyable or earnable). Barter (compute-for-compute) is optional and mostly intra-org.
- Every COMMIT carries a **verify_bounty** (escrowed) paid to the committee after finalization (post challenge window ×2).

**5.2 Verifier Pools (stake, diversity, selection)**

- To join verifier pools, a node must **stake** credits (bond).
- **Selection weight:** w = sqrt(stake) × reputation × recency_factor, capped per entity; **delegation limits** prevent pooled capture.
- **Diversity constraints** enforced at selection time; also **hard caps on per-entity share** in any single committee.

**5.3 Anti-Gaming (bounties & self-challenges)**

- **Bounty caps** by task class/complexity (policy-enforced).
- **Escrow bounties** for ≥ 2 × T_challenge.
- **Related-party checks:** payouts blocked if challenger or verifiers are linked (same org/ASN/identity graph).
- **Pattern analysis** (excessive self-challenge, bounty spikes) feeds reputation and routing penalties.

**6) Routing at Scale**

**Filter → Shortlist → Canary → Bandit**

- **Filter**: capability, policy (zones, budget), tags, constraints.
- **Shortlist**: score = f(reputation, price, P95 latency, domain fit, recency, stake weight).
- **Canary**: micro-task on top 2; verifiers score; pick winner.
- **Contextual bandit** learns per domain; **exploration budget** guarantees newcomers get traffic.

**7) Cross-Shard Coordination (no classical 2PC)**

Avoid blocking 2PC. Use **commit-by-reference with escrow/TTL**:

- Each shard decides its own **NEED** via DECIDE (K_plan). The decision produces a **commitment artifact** (hash).
- Dependent shards **treat commitment artifacts as inputs** and run their own slots.
- For truly coupled steps:
  - Use **prepared DECIDE** with short TTL (optimistic); if all commitments appear before TTL, each shard **finalizes**; else **rollback** by rule.
  - Or use **escrow artifacts** (published commitments that finalize only after all linked commitments are visible).

Add field: shard_dependencies\[\] in PROPOSE to make cross-shard needs explicit.

**8) Liveness & Back-Pressure**

- **Leases:** CLAIM(ttl) + **heartbeats**; missing heartbeats → **scavenge** lease.
- **Randomized backoff** to prevent herds.
- **Retry & message budgets** in policy capsule; agents must **stop** when exceeding.
- **Bid windows**: finite auction periods for NEEDs.

**9) Security & Trust**

- **Identity:** Ed25519 keys; signed manifests; optional **attested runtimes** for pro nodes.
- **Sandboxing:** untrusted jobs run with process jails/Firecracker; **outbound-only relays** (no open ports).
- **Policy enforcement:** preflight + ingress + commit-gate (default-deny). Data/instructions separation; **cite-then-write** flows; strict JSON schemas.

**10) Observability, Replay & Debugging**

- **Signed per-thread traces** (append-only JSONL) are the source of truth: model_used, tokens, cost, zone, refs, policy digest.
- **Observability plane (optional, federated):** nodes may stream signed logs to build global causal views; **authority remains with signed traces**.
- **Deterministic simulator:** replays traces in a single process; injects partitions, clock skew, message loss; property tests (e.g., "never two DECIDE for same NEED").
- **Chaos harness:** lease drops, verifier collusion, back-pressure drills.

**11) Garbage Collection & Fast Sync**

- **Epoch checkpoints**: periodic **CHECKPOINT{epoch, merkle_root}** with verifier quorum. Once a checkpoint is stable, nodes may **prune** pre-checkpoint ops.
- **Hot/cold tiers**: recent ops hot-stored; old ops archived (lower replication).
- **Deterministic compression**: final states summarized; proofs retained via Merkle roots.
- **Fast sync**: newcomers bootstrap from **signed checkpoints** (registry advertises latest roots).

New verb: CHECKPOINT.

**12) Bootstrap Mode (Progressive Quorums)**

- Networks start with **bootstrap=true**:
  - **K_result_min = 1**, **K_plan_min = 1** (self-attestation allowed) **only** when active_staked_verifiers < threshold.
  - Diversity rules relaxed but **stake + bounty + challenge window mandatory**.
  - **Challenge rewards boosted** during bootstrap to counter low K.
- Exit bootstrap when active_staked_verifiers ≥ M for D consecutive hours or after N finalized jobs; raise K toward policy targets using:
- K = min(K_target, floor(active_verifiers \* alpha))

(e.g., alpha=0.3).

**13) Cost Model (Local-First)**

- **Tool-first** (scrape/parse/check) → no tokens.
- **Small local LLMs** (quantized) for outline/patches/semantic checks.
- **Cloud finalizer** only when policy allows & verifiers still fail.
- **Delta prompts & artifact refs** keep contexts tiny.
- **Budgets** (tokens/\$/msgs/TTL) in policy capsule; enforced at gates.

**14) Minds & Manifests (Open Ecosystem)**

A mind publishes a **capability manifest** (I/O schema, tags, constraints, price, pubkey, version). Registry discovery + routing (§6). Verifier pools require **stake** + **conformance tests** (policy engine, schema, trace emission).

**15) Evaluation (Research)**

Compare to (a) single-LLM baseline, (b) orchestrated MAS:

- **Correctness:** verifier pass rate; contradiction rate; citation coverage.
- **Cost:** tokens and \$ per finalized result (quality-matched).
- **Time-to-final:** median, P95.
- **Reproducibility:** exact replay from traces.
- **Resilience:** success under chaos (killed workers, partition, skew).
- **Policy adherence:** violations caught at each gate.
- **Routing quality:** canary win-rate; bandit regret.

**16) New / Updated Verbs & Fields (v0.2)**

- **Planning:** ATTEST_PLAN, DECIDE, RECONCILE
- **Results:** CHALLENGE, INVALIDATE, CHECKPOINT
- **Envelopes:** add policy_engine_hash, policy_eval_digest
- **Proposals:** add shard_dependencies\[\]
- **Economics:** verify_bounty, stake_info (in verifier manifests)
- **Committees:** diversity constraints (org/ASN/region caps) enforced at selection and payout

**17) Risks & Mitigations (Quick Map)**

- **Split-brain:** scoped consensus per NEED + epochs/fencing + deterministic merges.
- **Verifier apathy/collusion:** stake + bounties + slashing + challenge rewards + diversity + caps + √stake weighting.
- **Policy divergence:** WASM/IR evaluator + engine hash + conformance + eval digest.
- **DoS via challenges:** typed proofs + size/gas bounds + challenger bonds.
- **Cross-shard deadlocks:** commit-by-reference with escrow/TTL; no classical 2PC.
- **GC bloat:** checkpointing with Merkle roots + fast sync + deterministic compression.
- **Bootstrap fragility:** progressive K with strict timebox & juiced challenge rewards.