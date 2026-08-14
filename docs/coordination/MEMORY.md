# Current Status

Window 4 has implemented a Memory-owned, point-in-time
`ResearchContextBundle` boundary while retaining the existing L0–L4 hierarchy
and private FAISS Repository boundary. No Agent, Prompt, Provider, report,
Evaluation, `MODULE_STATUS.md`, or `DECISIONS.md` file was changed.

The bundle converts semantic candidates into explicit sections:

- `current_snapshot`
- `macro_events`
- `asset_events`
- `prior_research`
- `prior_risk`
- `historical_analogs`
- `regime_context`
- `retrieval_metadata`
- `missing_context`

Every returned item retains its original `SourceReference`, `effective_ts`,
importance, retrieval score, retrieval reason, Memory level/type, namespace,
asset, market and creator. Empty retrieval is represented by
`RetrievalStatus.EMPTY`, `no_relevant_memory = true`, and one explicit
`MissingContext` per requested empty section.

## Current Task

The Phase 3 Memory implementation now provides:

1. `MemoryService.retrieve_context(ResearchContextRequest)` as the structured
   retrieval entry point.
2. A mandatory timezone-aware `as_of`; eligibility requires
   `effective_ts <= as_of` before any result enters the bundle.
3. Exact namespace, asset, market and minimum-importance filtering.
4. `GLOBAL` context availability for a requested market without allowing
   another market's Memory.
5. L3 report-trace lookup by the same asset when
   `include_prior_reports = true`, with explicit `current_report_id` exclusion.
6. Deterministic relevance ordering by semantic score, then importance,
   effective time and Memory ID.
7. Provider-independent vector snapshot identity stable across Repository
   restart; no FAISS object or raw vector crosses the boundary.
8. Historical analog output only for stored L4 Memory whose explicit
   `memory_type` is `historical_analog` or `historical_analogue`. Similarity
   alone never creates an analog.
9. UTC-naive encoding for aware Memory timestamps written to DuckDB's
   timezone-naive `TIMESTAMP`, preventing host/session timezone drift during
   point-in-time comparison.

## API Changes

Implemented inside the Memory-owned package:

- `ResearchContextRequest`
- `ResearchContextMemory`
- `ResearchContextSection`
- `ResearchContextBundle`
- `RetrievalMetadata`
- `RetrievalStatus`
- `MissingContext`
- `MissingContextReason`
- `ResearchContextRetrievalError`
- `MemoryService.retrieve_context(request) -> ResearchContextBundle`
- `VectorRepository.snapshot_id(namespaces) -> str`

Requested from Main Agent before cross-module integration:

- Add `retrieve_context` to the shared Memory service Protocol or approve a
  separate Protocol owned by the integration layer.
- Replace raw `MemorySearchResult[]` consumption in `ResearchWorkflow` and
  Agent context projection with the approved `ResearchContextBundle` view.
- Supply report `as_of`, market, asset, namespaces and current report ID at the
  composition boundary. Do not derive `as_of` from wall-clock time.
- Decide whether FastAPI receives a new bundle route or keeps this as an
  internal research-pipeline contract.
- Reconcile `ResearchContextMemory.source` with the pending common
  `EvidenceItem` identity without creating a second evidence lineage family.
- Audit or migrate Memory rows written before UTC-naive normalization; their
  persisted naive timestamps may reflect the old DuckDB session timezone.
- Record the accepted point-in-time, snapshot-identity, historical-report and
  UTC timestamp policies in `docs/DECISIONS.md` if Main approves them.

## Files Changed

- `src/memory/contracts.py`
- `src/memory/retrieval.py`
- `src/memory/service.py`
- `src/memory/__init__.py`
- `src/repositories/memory.py`
- `src/repositories/vector.py`
- `tests/integration/memory/test_research_context_bundle.py`
- `docs/coordination/MEMORY.md`

## Tests

Memory-focused verification:

- `26 passed` across Memory integration, Memory Repository integration and
  vector Repository tests.
- Memory-scoped Ruff: passed.
- Memory-scoped strict mypy: passed (`9 source files`).
- Memory-scoped Black: passed.

Required Phase 3 cases implemented and passing:

- temporal leakage
- asset isolation
- market isolation
- explicit no-result state
- relevance ordering and importance filtering
- persistence/restart with stable snapshot identity
- rebuild
- historical report retrieval excluding future/current/other-asset reports
- L0–L4 section classification and no fabricated historical analogs

Full repository gates:

- pytest: `290 passed, 5 deselected`
- Ruff: passed
- Black: passed (`227 files unchanged`)
- `git diff --check`: passed
- full mypy: blocked by six existing non-Memory errors in
  `tests/unit/test_live_report.py` (object indexing, non-exported live smoke
  attributes, and one untyped function)

No live test or external service was invoked. No credential value was read,
printed, copied or persisted.

## Blockers

- No shared-interface blocker remains. Main integrated
  `ResearchContextBundle`, added `research_context_v1`, and resolved full
  mypy.
- Historical resolved blockers: Workflow migration, common citation policy
  and UTC timestamp policy were pending before ADR-0025.
- Existing pre-normalization rows are not rewritten automatically. A snapshot
  with uncertain timezone provenance must be audited or rebuilt before a
  point-in-time baseline.
- Real L0/L1/L2/L4 content coverage remains a data-population gap, not an
  interface blocker; empty sections continue to be explicit.

## Required Changes From Other Modules

- Resolved by Main: Protocol/composition migration, Agent projection,
  schema-version decision, citation policy and timestamp ADR.
- Future DATA writes must continue preserving UTC effective/release time and
  canonical asset/market lineage. No direct LLM Gateway dependency is needed.

## Ready For Integration

YES — integrated by Main under ADR-0025; historical concerns remain above.

---

# Report Completeness Evidence Eligibility — 2026-08-14

## Current Status

No Memory mechanism changed. Newly derived fundamental, valuation, technical,
macro snapshot, news, and aggregate sentiment Evidence is eligible for future
normal report/event Memory writes through the existing lineage path.

## Blockers

NONE. Historical Memory remains `EMPTY_VALID` when no attributable prior item
exists; no synthetic history was created.

## Ready For Integration

YES

---

# Final Enrichment Eligibility — 2026-08-14

## Current Status

FMP standardized metrics and FRED MacroSnapshot Claims retain canonical source
lineage and are eligible for normal future report/Memory writes. No Memory
layer or synthetic historical item was added.

## Blockers

NONE. The final run's historical retrieval remains `EMPTY_VALID`.

## Ready For Integration

YES
