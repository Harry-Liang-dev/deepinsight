# OpportunityCandidate v1

## Definition

An `OpportunityCandidate` is a deterministic Research qualification artifact:
the asset has at least one structured reason to merit further Research or
future Quant consideration. It is not a ranked security, recommendation,
target price, position, order, or statement of expected return.

```text
ResearchState / ResearchEpisode
  → Selection SatelliteAlphaObservation[]
  → transparent eligibility rules
  → OpportunityCandidate
```

## Eligibility

Qualification is rule-based and has no weighted or opaque score. At least one
of these structured bases must exist:

- an explicit meaningful Sector/Chain alignment state;
- an explicit expectation change;
- an explicit non-rumor logic stage or accepted material Asset event;
- an accepted Research Manager thesis;
- accepted structured Bull/Bear disagreement;
- accepted structured Risk review.

Evidence Strength alone, the presence of a ResearchState, or the presence of
Sector context does not qualify an asset. When no rule is satisfied, the
artifact records `INSUFFICIENT_RESEARCH` and no opportunity type.

The classification vocabulary is `SECTOR_CHAIN`, `EXPECTATION_CHANGE`,
`MATERIAL_EVENT`, `MATERIAL_THESIS`, `RESEARCH_DEBATE`, and `RISK_RESEARCH`.
These are Research coverage reasons, not Quant signals.

## Identity, coverage, and provenance

`candidate_id` is a SHA-256 semantic identity over the asset, cutoff, source
State/Episode, Selection Observation IDs, opportunity semantics, lineage,
coverage, and contract version. `created_at` is excluded.

Candidate coverage may be `AVAILABLE`, `PARTIAL`, `MISSING_INPUT`,
`NOT_AVAILABLE_AT_SOURCE_RUN`, or `NOT_APPLICABLE`. A qualified Candidate may
remain PARTIAL when some Satellite families lack source data. Missing is never
zero and does not become a score.

Reference-only lineage is:

```text
Candidate → Satellite Observation → ResearchState / Episode
          → accepted Claim / Sector Claim / Event → Evidence
```

The Candidate stores IDs rather than copied Evidence or report prose. Its
`available_at` is the latest source Observation availability and is enforced
through Unified Temporal Contract v1.

## Selection relationship and future Quant boundary

The Day46 builder consumes only definitions with usage `SELECTION` or `BOTH`.
It performs zero LLM and Provider calls, does not parse the final report, and
does not compare or rank assets. A three-asset deterministic fixture proves
that the same definition/version/cutoff can produce structurally comparable
descriptors; it is contract validation only, not real Alpha.

Future `deepinsight-quant` may independently join these artifacts to its full
PIT universe and perform Quant processing. This repository does not emit
rank, Top-K, z-score, IC, Factor exposure, trade action, or portfolio fields.
