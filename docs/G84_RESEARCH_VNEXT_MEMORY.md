# G84 Research vNext Memory foundation

Status: **DEVELOPMENT_ONLY_OPT_IN / INTERFACE_FOUNDATION**. No Provider/model
calls, no nine-role E2E claim, no production State/Quant permission change.
Owner: W1 architecture/contracts; W6 Memory implementation; W3 research policy
and specialist integration. Version: `g84_memory_foundation_v1`.

## Existing architecture and minimal delta

The repository already has MemoryService with DuckDB sidecars and FAISS retrieval
(`src/memory/service.py`, `retrieval.py`, `contracts.py`), L0–L4, orthogonal
Scope and LearningMemoryMetadata (`src/schemas/memory.py`). Phase4 has
MemoryRetrievalRecord, context attribution, ResearchStateSnapshot,
ResearchEpisode and ResearchQuantHandoffBundle. These remain authoritative.
G84 wraps their identities; it does not replace their stores or schemas.

SectorAnomalyRadar already produces deterministic candidates, and
SectorRadarMemoryService projects them into existing scopes. SectorResearchAgent
already validates and persists attributed research. Sector Radar becomes the
main discovery entry, with daily scanning, event triggers and manual selection:

| Priority | Research input | Boundary |
|---|---|---|
| P0 | Equity events, source-backed fund flows, relative value | No OHLCV-derived fictional flows; valuation needs existing numeric proof |
| P1 | Independently tested medium/low-frequency trends | No new factor computation or performance claims in Research |
| P2 | Commodity spreads reserve | Not in current equity execution |

Opportunity Cards should reference existing OpportunityCandidate/Radar events,
not create another opportunity registry. A card alone does not start research.
Human selection or a resolved preauthorized ResearchMandate is required.

Current ResearchCoordinator still uses eight roles and its historical Manager
placement. Its `run_collaboration` already delegates to the v2 bounded dispatcher,
StateReducer and ReferenceValidator. G84 does not replace that dispatcher or edit
the production AgentName enum. Future opt-in integration uses:

`four Analysts → Bull/Bear → Risk → Trader → final Research Manager`.

Bull/Bear are peers. Trader submits a non-executable thesis, risks and invalidation
conditions. Manager reviews it; approval is research-only. Coordinator owns
dependencies and working revisions, not specialist judgment. LLMGateway, Agent
Claim/Schema/Numeric/Parent validators and Report assembler remain unchanged.
No live route, budget, scheduler or prospective timer is activated.

## Memory dimensions and meanings

| Level | Meaning |
|---|---|
| L0 | Market Snapshot |
| L1 | Macro/Sector Event |
| L2 | Asset Event |
| L3 | Research/Debate/Risk/Decision |
| L4 | Regime/Strategy Performance references; no strategy engine here |

Scopes remain `GLOBAL:`, `MACRO:`, `SECTOR:`, `CHAIN:`, `ASSET:`, `EPISODE:` with
the existing ResearchScopeType enum. Namespace shape is not proof of membership;
existing temporal sector/asset memberships must resolve cross-scope propagation.
Episodic retains runs/events; Semantic retains explicit candidate/validated/retired
knowledge lifecycle; Performance retains future evaluation references separately.
FAISS similarity selects context, never establishes financial truth.

Fact is an existing ValidatedClaim reference, not text promoted by Memory.
Inference/Hypothesis/ResearchQuestion reuse v2 Statement/Question semantics and
remain distinct from Fact. TradeProposal is a new non-executable reference
envelope. Outcome is a later evaluation record, never backfilled into an earlier
State. G84's record-kind labels classify referenced payloads; they do not replace
existing statements, Claim validators or outcome schemas.

## Frozen shared interface

Executable schemas: `src/memory/vnext_contracts.py`; compatibility helpers:
`src/memory/vnext.py`. Machine freeze: `contracts/g84-memory-v1.json`.
Schema fields are exhaustive and extra fields are rejected. Required hash fields
are 64-digit SHA256; identities hash sorted canonical UTF-8 JSON. A digest binds
bytes but is not authentication or proof of independent authority.

Every envelope has owner, record ID, revision, supersedes identity, Scope,
created_at, exact UTC research_as_of, source_refs and opt-in mode. Revision >1
requires its predecessor. Source refs carry original owner/version, content hash,
available/observed/ingested clocks. G84 uses conservative historical eligibility:
all three source clocks must be at/before research_as_of. Generated lineage such
as a retrieval bundle or proposal may be produced later, by created_at, without
pretending that it was available earlier. Existing live temporal semantics stay
unchanged; a future live adapter must explicitly reuse that contract.

| Interface | Producer → consumer | Specific binding / permission |
|---|---|---|
| MemoryDelta v1 | W6 retained data detector → Coordinator/W3 policy | before/after same subject hashes, L0–L4, change kind, detector identity, materiality rule; unchanged bytes cannot be material |
| MemoryReadSet v1 | W6 MemoryService adapter → Agent/Episode attribution | Actual delivered Memory IDs/versions/hashes, bundle digest, query/run/role, clocks; CONTEXT_ONLY |
| MemoryWriteProposal v1 | Agent → W6 checked intake | Existing MemoryWriteRequest payload hash, read-set identity, kind/action; always PENDING_EXISTING_VALIDATION |
| ResearchImpactPlan v1 | Coordinator pure planner → existing dispatcher (future) | Delta/Mandate/policy hashes, direct roles, dependency stages, reuse identity, blocked reason |
| ResearchMandate v1 | Human selection/preauthorized decision resolver → Coordinator | Opportunity identity, external authority reference, exact scopes/roles, expiry; RESEARCH_ONLY |
| TradeProposal v1 | Trader → final Manager | Mandate hash, thesis, risks/invalidation, exact risk-review reference; NON_EXECUTABLE_RESEARCH |
| ResearchReviewDecision v1 | final Manager → existing State builder (future) | Proposal + working State, approve/revise/reject/abstain and reasons; execution_authorized=false, production_admission=false |

MemoryReadSet records supplied context, not inferred LLM attention. Continue using
MemoryRetrievalRecord for candidate/selected population and existing attribution
for actually cited/used Claim links. `read_set_from_bundle` checks the actual
MemoryService bundle and exact member bytes; unknown clocks or missing retained
member identities block the new adapter rather than inventing lineage. A valid
empty bundle has an empty read set, not fabricated context.

ResearchPlan v2 already owns requested slots, budgets and source permissions.
ResearchMandate is its human/opportunity selection prerequisite, not a second
execution budget. Existing v2 Reference/Statement/Question remain integration
targets. G84 is deliberately not imported by production Coordinator: Trader is
not yet a registered ResearchPlan v2 role. W3 must implement that narrow adapter
later with explicit tests; G84 cannot dispatch by merely constructing a Plan.

## Agent Memory permission matrix

All entries mean controlled API permission, not direct repository access.
Caller identity/scopes originate at the trusted application composition root,
never the model's payload. `MemoryAccessContext` enforces this logical policy for
opt-in helpers; it is not a new credential system or a same-UID security boundary.

| Role | Read history | Cite verified facts | Propose hypothesis/question | Append own research event | Update working State | Final research review | Record later outcome |
|---|---|---|---|---|---|---|---|
| Fundamental | scoped | validator required | yes | proposal only | no | no | no |
| Technical | scoped | validator required | yes | proposal only | no | no | no |
| Sentiment | scoped | validator required | yes | proposal only | no | no | no |
| News/Event | scoped | validator required | yes | proposal only | no | no | no |
| Bull / Bear | scoped | validator required | yes | proposal only | no | no | no |
| Risk | scoped | validator required | yes | proposal only | no | no | no |
| Trader | scoped | validator required | yes | non-executing proposal | no | no | no |
| Research Manager | scoped | validator required | yes | review proposal | no | research-only decision | no |
| Coordinator | scoped | no new facts | no | no specialist judgment | new revision via existing builder | no | no |
| Outcome recorder | scoped at later cutoff | no new facts | no | no | no | no | separate later record |

W6 must resolve MemoryWriteProposal payloads/read sets, validate source IDs and
Claim authority using original validators, then append through MemoryService.
The implemented `validate_write_proposal` only checks permission, payload binding,
owner, Scope and metadata; it never persists or emits an accepted Claim. A pending
FACT citation still needs independent accepted-Claim resolution. Revisions never
authorize replacing another actor's artifact or Raw Evidence. Administrative
MemoryService delete/rebuild methods are not exposed to Agents. New unaudited
proposals cannot be mixed with validated historical Memory.

## Memory Delta → Impact → Selective Agent Execution

1. W6 compares retained source versions and records a MemoryDelta. No detected
   change is not evidence of freshness: the detector must retain the complete
   checked population. Corrections/revisions remain new records, including
   prior hashes. No network acquisition or actual materiality detector is added
   in G84.
2. W3 freezes a Scope/change-kind ImpactRule and its specialist roots. Materiality
   rules cannot be selected post-result. Mapping GLOBAL/SECTOR/CHAIN changes to
   assets needs existing dated membership evidence and a plan for each scope;
   this foundation's pure helper intentionally handles one exact scope at a time.
3. `plan_impact` validates the opt-in contract and Mandate bounds, then closes
   dependencies in role order. For example a material Technical change reruns
   Technical → Bull/Bear → Risk → Trader → Manager, not the other Analysts.
4. Nonmaterial daily prices can reuse a State only when exact dependency digest,
   source-policy version, strategy version and validity interval match.
   Missing/incompatible evidence returns BLOCKED_REUSE, not REUSE and not an
   automatic all-role run. An absent impact mapping also blocks. Dependencies
   cover prompts/validators/model versions in addition to read-set inputs.
5. Existing dispatcher must later resolve real Mandate authority, reread immutable
   policy/dependencies, verify all upstream Claim gates (including unchanged
   Analyst reuse), enforce existing budget and no-retry controls, and freeze
   actual request bytes. G84 plan/schema construction cannot authorize dispatch.
6. Existing State/Episode builders append a new revision. Manager review cannot
   promote unvalidated text or bypass original Claim minimums, numeric/PIT checks,
   Quant risk/cost/portfolio gates or the production Handoff validator.

## W3 / W6 delivery and ownership

The shared baseline is a scoped local commit on `g84/shared-memory-foundation-v1`
parented by the existing repository HEAD. Main's unrelated dirty work and index
are retained. Core shared modules import only preexisting tracked Phase4 types;
they do not require uncommitted G65–G83 code. Documentation addenda are committed
against the old tracked documents, leaving unrelated Main documentation changes
in place. AGENTS includes the current preserved mandatory protections.

W6 is a new same-repository worktree at `/home/harry/deepinsight-memory-w6`, branch
`feature/g84-memory-w6`, based on that commit. No separate repository, account or
environment is created. W6 owns retained-delta detection, permission-checked
MemoryService intake and reuse resolution, and must consume this exact contract.

`/home/harry/deepinsight-w3` currently has no Git identity. Do not initialize it,
overwrite its code or treat it as an existing worktree. W3 can first read the
versioned contract/docs in W6 read-only and verify the manifest SHA256 and file
inventory. To obtain code, export the exact commit's listed shared files into a
new versioned staging directory (or create a separate feature worktree after
checking the destination). Never overlay its working tree or apply a blind
cherry-pick. W3 owns the frozen impact policy, Analyst/debate/Trader/Manager
adapter and retained-read provenance; it does not rewrite Memory storage.

## Acceptance limits and remaining integration

Implemented here: typed contract validation, role/scope permission checks for
pending writes, exact read-set adaptation, deterministic single-scope impact
closure and conservative reuse qualification. Tests exercise actual existing
DuckDB/FAISS/MemoryService with Fake embeddings plus existing State/Episode/
Handoff/Radar regressions. No production path is switched to vNext.

Remaining: retained detector/materiality policy implementations, authenticated
composition-root wiring, accepted-Claim resolution and durable proposal intake,
multi-scope impact/membership resolution, actual selective execution, Trader
prompt/validator integration, final Manager dependency adapter and revision
storage/attribution integration. These are not nine-role E2E successes. No
G65–G83 experiment bytes, timers or prospective observation services are edited.
W4 independence rules remain in force; this is W1 engineering foundation only.
