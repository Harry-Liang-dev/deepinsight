"""Retained source to advisory task and reopened Memory; zero external calls."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.memory.hybrid import consume_observation
from src.memory.vnext_contracts import ArtifactRef, ResearchMandate
from src.schemas.research_v2_shared import canonical
from src.services.research_vnext.exploratory_view import exploratory_task_view
from src.services.research_vnext.g97_sources import AVGOSources
from src.services.research_vnext.products import ResearchProduct
from src.services.research_vnext.radar_pilot import encoded
from tools.g100_hybrid_memory import OfflineSession


def inputs(root: Path) -> tuple[ResearchMandate, dict[str, Any]]:
    """Load exact previously selected mandate and its retained artifacts."""
    directory = root / "artifacts/g96/delivery"
    return (
        ResearchMandate.model_validate_json(
            (directory / "research-mandate.json").read_bytes()
        ),
        {
            **json.loads(
                (
                    root / "artifacts/g95/delivery-v2/resolved-artifacts.json"
                ).read_bytes()
            ),
            **json.loads((directory / "resolved-artifacts.json").read_bytes()),
        },
    )


def run(root: Path, output: Path) -> dict[str, Any]:
    """Run an isolated source-observation slice; no scientific research success."""
    output.mkdir(parents=True, exist_ok=False)
    at = datetime.now(UTC)
    sources = AVGOSources(root, at)
    session = OfflineSession(output / "store", sources, at)
    proposal = session.proposal("A07")
    admitted = session.admit(proposal)
    assert session.admit(proposal) == admitted
    # Original database operations use short-lived connections. Drop all service,
    # repository and index instances before rebuilding them from durable files.
    del session.service, session.vector, session.journal, session.db
    session.at = datetime.now(UTC)
    session.open()
    delivery = session.retrieve()
    mandate, artifacts = inputs(root)

    def reader(reference: ArtifactRef) -> bytes:
        return encoded(artifacts[reference.artifact_id])

    view = exploratory_task_view(
        objective="SOURCE_ORGANIZATION",
        questions=(
            "Which contract identity remains unproved by the supplied disclosure?",
        ),
        mandate=mandate,
        reader=reader,
        delivery=delivery,
        resolver=session.resolver,
        journal=session.journal,
        access=session.access,
        at=session.at,
        enabled=True,
    )
    receipt = delivery.supplied_records[0]
    mid = receipt.result.memory_id
    text = (
        receipt.record.publisher
        + " stated: "
        + receipt.record.proposal.statement
        + " [memory:"
        + mid
        + "]"
    )
    used = consume_observation(
        delivery,
        memory_id=mid,
        model_text=text,
        use="ATTRIBUTED_SOURCE",
        access=session.access,
        journal=session.journal,
        at=session.at,
        resolver=session.resolver,
    )
    # Original G86 product, explicitly synthetic and never a validated Claim.
    product = ResearchProduct(
        kind="RESEARCH_QUESTION",
        text="Whether the arrangements share legal obligations remains unresolved.",
        supporting_input_ids=(mid,),
        counter_input_ids=(),
        missing_evidence=("Executed agreements identifying each obligation",),
        falsification_conditions=(
            "An explicit official contract cross-reference "
            "establishes the relationship",
        ),
    )
    completion = {
        "origin": "SYNTHETIC_ENGINEERING_FIXTURE",
        "completion_status": "INDETERMINATE",
        "findings": [],
        "source_references": [mid],
        "research_hypotheses": [product.model_dump(mode="json")],
        "uncertainties": ["Contract identity UNKNOWN"],
        "evidence_requirements": product.missing_evidence,
        "next_actions": ["W3 may design an independently preregistered investigation"],
        "scientific_acceptance": False,
        "incremental_value": "NOT_MEASURED",
    }
    result = {
        "origin": "REAL_RETAINED_SOURCE_WITH_SYNTHETIC_ENGINEERING_CONSUMER",
        "g100_review_not_used_to_grant_new_authority": True,
        "source_verification": sources.verification,
        "selected_opportunity": mandate.opportunity.artifact_id,
        "selection_preserved": True,
        "first_episode": session.first.episode_id,
        "next_episode": session.next.episode_id,
        "memory_id": mid,
        "durable_reopen": True,
        "idempotent_admission": True,
        "retrieved": len(delivery.retrieved_ids),
        "supplied": len(delivery.supplied_records),
        "synthetic_consumption": used,
        "actual_new_agent_dispatches": 0,
        "scientific_claims_created": 0,
        "formal_quant_eligibility": "BLOCKED",
        "formal_full_role_impact_not_overridden": True,
        "context_measurement": view["measurement"],
        "task_view_bytes": len(canonical(view)),
        "model_calls": 0,
        "provider_calls": 0,
    }
    for name, value in {
        "ADMISSION.json": admitted.model_dump(mode="json"),
        "DELIVERY.json": delivery.model_dump(mode="json"),
        "TASK_VIEW.json": view,
        "ENGINEERING_COMPLETION.json": completion,
        "RECEIPT.json": result,
    }.items():
        (output / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(Path.cwd(), args.output), indent=2))
