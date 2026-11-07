"""Actual calibration data, exact Prompt/SDK binding and forward-only safety tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from research_eval.claim_campaign import (
    VARIANTS,
    adopt_prompts,
    compile_candidate,
    dry_run,
)
from research_eval.compiler import RequestCompiler
from research_eval.evaluation import MechanicalEvaluator
from research_eval.models import FrozenExperiment, encoded, identity
from research_eval.runner import OfflineScenario, TrustedExperimentRunner
from research_eval.security import (
    CampaignReleaseGate,
    CurrentAuthorityAdapter,
    OfflineAuthority,
)
from research_eval.source_text import verify_source_text
from research_eval.w5_calibrated import (
    CASES,
    PROFILE,
    CalibratedBenchmark,
    CalibratedComparator,
)

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("DEEPINSIGHT_PRIVATE_REGRESSION_ROOT"),
    reason="Requires independently retained W5 licensed dataset",
)


@pytest.fixture(scope="module")
def benchmark() -> CalibratedBenchmark:
    return CalibratedBenchmark()


@pytest.fixture(scope="module")
def campaign(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, FrozenExperiment, dict[str, Any]]:
    root = tmp_path_factory.mktemp("claim-campaign")
    f = compile_candidate(ROOT, root / "freeze")
    receipt = dry_run(ROOT, root / "freeze/freeze.json", root / "dry-run")
    return root, f, receipt


def proposal(**changes: Any) -> bytes:
    body = dict(
        verdict="UNDETERMINED",
        evidence_handles=["H0005"],
        reasoning="The source coefficient is 27,778.",
        missing_premises=["No new semantic prediction."],
        counterevidence_handles=[],
        uncertainty="Economic meaning remains unevaluated.",
    )
    return encoded({**body, **changes})


def test_calibrated_case_and_prompt_population(benchmark: CalibratedBenchmark) -> None:
    assert tuple(benchmark.population["case_ids"]) == CASES
    rows, proof = adopt_prompts(benchmark)
    assert tuple(r["variant_id"] for r in rows) == VARIANTS
    assert proof["model_config"]["temperature"] == "UNSET"
    for c in CASES:
        case = benchmark.project(c)
        assert case.full_claim == benchmark.cases[c].original_complete_claim
        assert len(case.sources) == 3 and len(case.handles) == 9
        assert benchmark.cases[c].dataset_split == "REGRESSION"
        assert (
            "possible_correct_judgement_range"
            not in encoded(case.visible_input).decode()
        )
        assert "approved_independent_gold" not in encoded(case.visible_input).decode()


def test_twelve_real_sdk_bytes_and_equal_arms(
    campaign: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, f, r = campaign
    assert len(f.requests) == 12 and len({x.request_sha256 for x in f.requests}) == 12
    RequestCompiler().verify(f)
    for req in f.requests:
        wire = json.loads(req.raw_body)
        assert wire["text"]["format"]["strict"] is True
        assert set(wire["text"]["format"]["schema"]["required"]) == {
            "verdict",
            "evidence_handles",
            "reasoning",
            "missing_premises",
            "counterevidence_handles",
            "uncertainty",
        }
        assert wire["model"] == "qwen3.8-flash" and wire["store"] is False
        assert wire["max_output_tokens"] == 1024
        assert "temperature" not in wire and "top_p" not in wire
    for case in f.dataset.cases:
        reqs = [x for x in f.requests if x.case_id == case.case_id]
        assert len({identity(x.input_payload) for x in reqs}) == 1
        assert len({x.schema_identity for x in reqs}) == 1
    assert r["mock_attempts"] == 12 and r["complete_responses"] == 12
    assert r["peak_inflight"] == 2 and r["real_provider_attempts"] == 0
    assert r["content_failures"] >= 2 and r["request_bytes_equal"]


def test_w5cal_axes_unknown_and_full_pair_denominator(
    campaign: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    root, _, receipt = campaign
    summary = json.loads((root / "dry-run/paired-comparison.json").read_bytes())
    assert summary["planned"] == 12 and len(summary["pairs"]) == 4
    assert summary["calibration_axes"] and all(
        a.startswith("w5cal_") for a in summary["calibration_axes"]
    )
    assert summary["calibration_profile"] == PROFILE
    assert all(len(p["cells"]) == 3 for p in summary["pairs"])
    assert any(
        "UNKNOWN" in row["counts"]
        for group in summary["variants"].values()
        for row in group.values()
    )
    assert receipt["unknown_preserved"]


def test_gzip_raw_and_normalized_distinct_numeric_grounding(
    benchmark: CalibratedBenchmark,
) -> None:
    case = benchmark.project(CASES[0])
    binding = case.visible_input["source_read_bindings"]["G105-GET-09"]
    source = next(s for s in case.sources if s.source_id == "G105-GET-09")
    assert binding["raw_content_encoding"] == "gzip"
    assert binding["normalized_sha256"] != source.sha256
    assert "27,778" in verify_source_text(source, binding)
    result = MechanicalEvaluator(benchmark.protocol_sha256).evaluate(
        case, proposal(), identity("numeric-positive")
    )
    assert result.metrics["numeric_consistency"].status == "PASS"
    bad = MechanicalEvaluator(benchmark.protocol_sha256).evaluate(
        case, proposal(reasoning="USD 999999999 million."), identity("numeric-negative")
    )
    assert bad.metrics["numeric_consistency"].status == "FAIL"


@pytest.mark.parametrize(
    "field",
    [
        "raw_sha256",
        "normalized_sha256",
        "registry_sha256",
        "raw_content_encoding",
        "case_id",
    ],
)
def test_source_binding_drift_fails_closed(
    benchmark: CalibratedBenchmark, field: str
) -> None:
    case = benchmark.project(CASES[0])
    source = case.sources[0]
    b = dict(case.visible_input["source_read_bindings"][source.source_id])
    b[field] = "INVALID"
    with pytest.raises(ValueError):
        verify_source_text(source, b)


def test_normalized_byte_corruption_rejected(
    benchmark: CalibratedBenchmark, tmp_path: Path
) -> None:
    case = benchmark.project(CASES[0])
    source = case.sources[0]
    b = dict(case.visible_input["source_read_bindings"][source.source_id])
    p = tmp_path / "changed.txt"
    p.write_text("changed")
    b["normalized_path"] = str(p)
    with pytest.raises(ValueError, match="HASH_DRIFT"):
        verify_source_text(source, b)


@pytest.mark.parametrize("field", ["task", "rights", "asof", "claim"])
def test_projection_and_temporal_drift(
    benchmark: CalibratedBenchmark, field: str
) -> None:
    case = benchmark.project(CASES[0])
    if field in ("task", "rights"):
        visible = dict(case.visible_input)
        visible["w5_task_identity" if field == "task" else "w5_rights_fingerprint"] = (
            "0" * 64
        )
        case = case.model_copy(update={"visible_input": visible})
    elif field == "claim":
        case = case.model_copy(update={"full_claim": "Weakened claim"})
    else:
        case = case.model_copy(
            update={"research_as_of": case.research_as_of.replace(year=2025)}
        )
    with pytest.raises(ValueError, match="PROJECTION_DRIFT"):
        benchmark.validate_projection(case)


def test_old_protocol_cannot_score_new_response(benchmark: CalibratedBenchmark) -> None:
    c = benchmark.project(CASES[0])
    raw = proposal()
    m = MechanicalEvaluator("0" * 64).evaluate(c, raw, identity("test"))
    with pytest.raises(ValueError, match="PROTOCOL_DRIFT"):
        benchmark.evaluate(c, raw, m)


def test_release_and_receiver_missing_no_live_send(
    campaign: tuple[Path, FrozenExperiment, dict[str, Any]], tmp_path: Path
) -> None:
    _, f, _ = campaign
    with pytest.raises(ValueError, match="INDEPENDENT_RELEASES_REQUIRED"):
        CampaignReleaseGate(ROOT).check(f.campaign)
    with pytest.raises(ValueError, match="RECEIVER_NOT_INSTALLED"):
        CurrentAuthorityAdapter({}).check(f.dataset.cases[0], f.requests[0])
    with pytest.raises(ValueError, match="INDEPENDENT_RELEASES_REQUIRED"):
        TrustedExperimentRunner(
            Path(f.campaign.ledger_root),
            CurrentAuthorityAdapter({}),
            CampaignReleaseGate(ROOT),
        ).run(f)
    assert not Path(f.campaign.ledger_root).exists()


def test_duplicate_mock_population_no_resend(
    campaign: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    root, _, _ = campaign
    f = FrozenExperiment.model_validate_json(
        (root / "dry-run/freeze.json").read_bytes()
    )
    scenario = OfflineScenario(
        json.loads((root / "dry-run/scenario.json").read_bytes())["outcomes"]
    )
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        TrustedExperimentRunner(
            root / "dry-run/runs",
            OfflineAuthority(expires_at=f.campaign.expires_at),
            CampaignReleaseGate(ROOT),
        ).run(f, scenario=scenario)


def test_comparator_rejects_missing_population(
    campaign: tuple[Path, FrozenExperiment, dict[str, Any]],
) -> None:
    _, f, _ = campaign
    with pytest.raises(ValueError, match="POPULATION"):
        CalibratedComparator().compare(f, [])


def test_actual_w5_registered_units_and_period(benchmark: CalibratedBenchmark) -> None:
    checker = benchmark.port.calibration
    good = dict(
        metric_id="M365_total",
        value="27778",
        unit="USD_MILLION",
        currency="USD",
        scale="MILLION",
        period="FY2027Q1",
        scope="M365_TOTAL_INCLUDING_CONSUMER",
        handle="H0005",
    )
    assert checker.numeric_check(CASES[0], good)["status"] == "PASS"
    for key, value in [
        ("value", "27779"),
        ("period", "FY2026Q1"),
        ("scope", "COMMERCIAL_ONLY"),
        ("handle", "H0006"),
        ("scale", "BILLION"),
    ]:
        assert checker.numeric_check(CASES[0], {**good, key: value})["status"] == "FAIL"
