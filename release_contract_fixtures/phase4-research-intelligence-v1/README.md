# Phase 4 ResearchQuantHandoff golden contract fixture

This directory is a release supplement for the frozen DeepInsight Research
product release:

- product tag: `phase4-research-intelligence-v1`
- product commit: `be7590bd6f07c120350bbc122f878009ebf7fb6e`
- annotated tag object: `3fd7f1cd84b186270a6e7f1376aaab13233dffa9`

The product release remains unchanged. This supplement contains the exact
serialized `ResearchQuantHandoffBundle` emitted by the accepted AAPL Phase 4
live run. It is not a regenerated Research result and does not change any
Research schema, semantics, or product logic.

## Authoritative fixture

`research_quant_handoff_c325aedcb141007a2bda4bd0.json` is an exact-byte copy
of the original local acceptance artifact. It was copied without parsing,
normalization, pretty-printing, or reserialization. Verify it with:

```bash
sha256sum -c SHA256SUMS
```

The authoritative checksum, origin, frozen-release cross-checks, and contract
validation results are recorded in `provenance_manifest.json`.

## Scope

The fixture exists solely to bind the producer-side Phase 4 Research contract
to DeepInsight-Quant Q0 consumer tests. It contains the compact handoff payload,
including versioned Selection and Timing descriptors and provenance IDs. It
does not contain raw Provider payloads, runtime databases, vector stores,
credentials, OAuth state, or other live-run artifacts.

The proposed independent annotated supplement tag is:

`phase4-research-intelligence-v1-handoff-fixtures-v1`

That tag is intentionally not created by fixture preparation.
