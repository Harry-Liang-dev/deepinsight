# DeepInsight Phase 4 — Research Intelligence v1

Release status: **ACCEPTED / READY FOR FREEZE**  
Recommended tag: `phase4-research-intelligence-v1`

## Release summary

Phase 4 establishes DeepInsight as a point-in-time Research Intelligence and
Opportunity Discovery system whose final external boundary is the versioned
`ResearchQuantHandoffBundle v1`. Full AAPL live acceptance with real Providers
and Qwen passed, and the final independent audit passed.

This repository remains Research-only. It does not implement Planetary Alpha,
a Quant universe, Factor exposure or processing, IC/RankIC, Selection Top-K,
trading timing, Holdings ranking or decay, Regime/MoE routing, portfolio
construction, positions, orders, or execution. Those responsibilities belong
to a future independent `deepinsight-quant` repository.

## Accepted scope

### Phase 4A — Sector Intelligence

- Macro and Sector state
- Sector Radar and Event lineage
- Industry Chain ontology and context
- Sector Research Agent
- PIT-aligned Sector Context projected into all eight asset Research Agents
- Human-facing Macro, Sector, Industry Chain, and Radar surfacing

### Phase 4B — Structured Research Intelligence

- Unified Temporal Contract
- `ResearchStateSnapshot`
- `ResearchEpisode`
- Learning Memory lifecycle and PIT retrieval semantics
- Research Attribution
- PIT Research Dataset samples
- deterministic Golden Replay with zero Provider and LLM calls

### Phase 4C — Research-to-Quant boundary

- versioned Satellite Alpha research descriptors
- `OpportunityCandidate`
- `ResearchStateTransition`
- Selection and Timing descriptor contracts
- deterministic, PIT-safe `ResearchQuantHandoffBundle v1`
- compact JSON/JSONL external-consumer contract

## Prompt freeze

- Active Sector Research Prompt: `sector_research_prompt_v4`
- Active Research Manager Prompt: `v7`
- Sector Prompt v1, v2, and v3 and Research Manager v6 remain archived and are
  not selected by the production runtime.

## Acceptance status

- Phase 4 full live acceptance: **PASS**
- Phase 4 final independent audit: **PASS**
- Fake Provider use in live acceptance: **0**
- Point-in-time leakage: **0**
- Invalid accepted citations: **0**
- Accepted numeric grounding: **PASS**

The accepted AAPL run produced the human-facing Report, ResearchState,
ResearchEpisode, Attribution, Satellite observations, OpportunityCandidate,
ResearchStateTransition, and ResearchQuantHandoff. The handoff is a Research
artifact and is not a Quant signal or recommendation.

## Known research limitations

- Research Memory retrieval was `EMPTY_VALID` in the accepted AAPL live run.
- Memory predictive usefulness is `NOT_VALIDATED`.
- Satellite Alpha is `NOT_QUANT_VALIDATED`; incremental IC and predictive
  Alpha are not validated.
- Multiple Selection Satellite families remain `PARTIAL`.
- `EXPECTATION_REVISION` and `LOGIC_CERTAINTY` were `MISSING_INPUT` in the
  accepted live run.
- Timing semantic coverage remains limited; current live Timing observations
  are `MISSING_INPUT` where the required structured transition semantics do
  not exist.
- `PEER_GROUP` comparison is `UNSUPPORTED` without a versioned PIT peer model.
- The NVDA stress test was `NOT_EXECUTED` to conserve the live Provider request
  budget after the release-blocking AAPL run passed.
- `deepinsight-quant` has not been implemented.

## Non-blocking product backlog

### Human-report Macro repetition

The human-facing Report can repeat some Macro facts across Macro, News, and
synthesis sections. A future renderer should surface each material implication
once and reference its underlying Evidence instead of repeating macro-data
dumps. This is a presentation backlog, not an Evidence or PIT defect.

### Human-report numeric rendering

Research artifacts intentionally retain full machine precision. Human-facing
Report text can therefore show values such as `0.486529...` or `37.824200...`.
A future presentation renderer should format values for readers while
preserving original precision in Evidence, Claims, and ResearchState. Examples
include percentage display for margins, `x`-multiple display for P/E and P/B,
and compact currency display for market capitalization.

## Research Intelligence v2 depth backlog

Industry Chain contract and Report surfacing passed Phase 4. Current depth is
primarily ontology, membership, chain context, and accepted-Claim propagation.
Research Intelligence v2 may deepen supplier/customer edges, revenue exposure,
business binding depth, capacity, pricing power, earnings elasticity, catalyst
propagation, and risk propagation. These are future research-depth extensions,
not defects in the Phase 4 contract.

## Artifact policy

Commit deterministic regression artifacts and their JSON manifests under:

- `data/golden_replay/day43/`
- `data/golden_replay/day49/`
- `data/research_state/day38/`
- `data/research_episode/day39/`
- `data/research_attribution/day41/`
- `data/research_dataset/day42/`

Do not commit runtime DuckDB files, locks, raw Provider payloads, credentials,
OAuth stores, live Provider dumps, `data/live_acceptance/`, or
`data/live_qwen_embedding/`. Live acceptance artifacts remain locally retained
for operational audit.
