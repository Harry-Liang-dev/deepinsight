# Research evaluation platform

Status: **INTERNAL_RESEARCH_ENGINEERING**. Live Provider authorization is false;
scientific effect is not demonstrated. Public release does not install Owner
grants, approve data access, sign W4/W5 receipts or update ResearchState/Quant.

## Portable offline entry points

Install Python 3.12 dependencies using `pip install -e '.[dev]'`. From the checkout:

```bash
python -m research_eval --help
QWEN_MODEL_NAME=qwen3.8-flash python -m research_eval demo run --output /tmp/research-demo-new
QWEN_MODEL_NAME=qwen3.8-flash python -m pytest tests/research_eval tests/unit/memory -q
```

The output path must not already exist. The demo compiles two Prompt variants
across three synthetic cases through the existing Qwen Responses SDK serializer,
then runs concurrent MockTransport calls, immutable capture, local evaluation and
paired comparison. It cannot establish financial correctness or real Provider
concurrency. No API key or historical worker path is needed.

## Adopted implementation

`research_eval` includes the compiler, versioned Prompt registry, current authority
adapter, per-campaign budgets, one-attempt ledger, bounded concurrent runner,
trace storage, scorer adapter and experience export. C01 recovery quarantines
unresolved prior reservations; C02 sets the in-memory stop before persistent
STOP I/O. Already in-flight work can finish, but queued dispatches stop.

The current twelve-receiver factory is included in `research_eval.receivers`. It
retains exact membership, original Claim, SourceSupport/F01, READ_HISTORY, TTL,
revocation and CAS checks through the existing Memory implementation. Installation
requires separately retained licensed intake and an operator-owned installation;
no populated instance or grant is distributed here. Old release Pins cannot
authorize the new source/runtime. Do not bypass missing artifacts with fixtures.

The W5 `financial_benchmark` source is included. Calibration 1.1's five protocol-
pinned implementation modules retain their exact original bytes. Its datasets,
Gold policy, references and independently signed protocol remain external inputs.
Eleven `w5cal_*` axes and UNKNOWN are retained. A schema or handle PASS is never
scientific admission. Two non-pinned Gold return annotations were clarified with
`cast` without changing runtime behavior.

The original Baseline/Causal/Evidence prompt cores are packaged byte-for-byte in
`research_eval/prompts`; `research_eval.bundled_prompts.prompt_cores()` verifies
their hashes. They grant no tool, source or network authority.

## Separately retained private regression inputs

`DEEPINSIGHT_W3_PROMPT_ROOT`, `DEEPINSIGHT_W5_BENCHMARK_ROOT` and
`DEEPINSIGHT_W5_CALIBRATION_ROOT` select operator-supplied published deliveries.
They do not override delivery/manifest hashes. `DEEPINSIGHT_PRIVATE_REGRESSION_ROOT`
enables historical immutable-output regression. Private receiver tests additionally
need the licensed intake at the checkout's ignored `artifacts` path. These data
are deliberately absent from a public clone; skipped private tests are reported
separately. Golden replay tests need separately retained historical bundles and
DBs. The assertions and original expected identities are unchanged.

## Public and runtime boundaries

The imported legacy modules form the existing trusted runtime dependency closure;
they are not a new parallel Sender. Historical experiment tools remain fail-closed
without their private freezes and genuine applicable Git Pins. This release does
not replay any old operation. Runtime hashes change on integration: the next live
campaign requires scoped W4 review and W5 exact binding against this Main source.

No formal Report, ResearchState or ResearchQuantHandoff schema is changed. Private
source archives remain local; GitHub is not their physical backup.
