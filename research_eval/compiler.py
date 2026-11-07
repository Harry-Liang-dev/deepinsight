"""Actual Qwen SDK serialization with local MockTransport only."""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import cast

from research_eval.models import (
    Dataset,
    ExperimentSpec,
    FrozenExperiment,
    FrozenRequest,
    PromptVariant,
    TrustedExperimentCampaign,
    encoded,
    identity,
)
from src.models.types import JsonObject
from src.services.development_model_profile import (
    MINIMAL2_EVIDENCE_PROFILE,
    MINIMAL2_SCHEMA_PROFILE,
    ModelExecutionProfile,
)
from src.services.llm_provider import LLMProviderCall
from src.services.pilot_model_readiness import request_audit
from tools.minimal_semantic_carrier import proposal_schema


def profile(cap: int) -> ModelExecutionProfile:
    """Use existing code-owned Qwen native-schema profiles, not caller tariffs."""
    if cap not in (512, 1024):
        raise ValueError("UNAPPROVED_OUTPUT_CAP")
    return MINIMAL2_SCHEMA_PROFILE if cap == 512 else MINIMAL2_EVIDENCE_PROFILE


class RequestCompiler:
    """Compile Cases × Variants; labels and authority metadata stay outside wire."""

    def compile(
        self,
        spec: ExperimentSpec,
        campaign: TrustedExperimentCampaign,
        dataset: Dataset,
        variants: tuple[PromptVariant, ...],
        *,
        workers: int = 1,
    ) -> FrozenExperiment:
        """Freeze exact SDK bytes with a campaign-constrained finite denominator."""
        if spec.mode != campaign.execution_mode:
            raise ValueError("CAMPAIGN_EXECUTION_MODE")
        if (
            spec.campaign_identity != identity(campaign)
            or spec.dataset_identity != identity(dataset)
            or campaign.dataset_identity != identity(dataset)
        ):
            raise ValueError("CAMPAIGN_DATASET_BINDING")
        if (
            spec.variant_identities != tuple(identity(v) for v in variants)
            or len({v.variant_id for v in variants}) != len(variants)
            or not variants
        ):
            raise ValueError("VARIANT_BINDING")
        pairs = [(v, c) for v in variants for c in dataset.cases]
        if len(pairs) > min(campaign.budget.max_samples, campaign.budget.max_attempts):
            raise ValueError("POPULATION_BUDGET")
        for v, c in pairs:
            if c.holdout:
                raise ValueError("HOLDOUT_AUTHORITY_NOT_INSTALLED")
            if (
                v.dataset_identity != identity(dataset)
                or v.immutable_boundary_identity != identity(campaign)
                or v.output_cap != campaign.output_cap
                or v.model != campaign.model
                or c.task_kind not in v.task_types
            ):
                raise ValueError("PROMPT_CANNOT_CHANGE_BOUNDARY")
            if c.authority_binding not in campaign.authority_bindings or any(
                s.sha256 not in campaign.permitted_source_hashes for s in c.sources
            ):
                raise ValueError("SOURCE_OR_AUTHORITY_OUT_OF_SCOPE")
        schema = json.loads(encoded(proposal_schema()))

        def build(pair: tuple[PromptVariant, object]) -> FrozenRequest:
            variant, candidate = pair
            # The typed population supplies cases; workers never see evaluator labels.
            from research_eval.models import DatasetCase

            assert isinstance(candidate, DatasetCase)
            payload = dict(
                candidate.visible_input, original_complete_claim=candidate.full_claim
            )
            prompt = (
                variant.content
                + "\nMINIMAL_OUTPUT_CONTRACT="
                + encoded(schema).decode()
            )
            call = LLMProviderCall(
                campaign.model,
                prompt,
                cast(JsonObject, payload),
                cast(JsonObject, schema),
            )
            audit = request_audit(
                call,
                output_cap=campaign.output_cap,
                model_profile=profile(campaign.output_cap),
            )
            return FrozenRequest(
                run_id=identity(
                    [
                        spec.experiment_id,
                        identity(campaign),
                        identity(candidate),
                        identity(variant),
                    ]
                ),
                case_id=candidate.case_id,
                variant_id=variant.variant_id,
                task_identity=identity(candidate),
                prompt_identity=identity(variant),
                schema_identity=identity(schema),
                request_sha256=audit["http_body_sha256"],
                raw_body=audit["serialized_http_body"],
                system_prompt=prompt,
                input_payload=payload,
                response_schema=schema,
            )

        with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as pool:
            requests = tuple(pool.map(build, pairs))
        if len({r.request_sha256 for r in requests}) != len(requests):
            raise ValueError("DUPLICATE_REQUEST_IN_POPULATION")
        return FrozenExperiment(
            spec=spec,
            campaign=campaign,
            dataset=dataset,
            variants=variants,
            requests=requests,
        )

    def verify(self, frozen: FrozenExperiment) -> None:
        """Recompile and compare every SDK byte before any run or evaluation."""
        rebuilt = self.compile(
            frozen.spec, frozen.campaign, frozen.dataset, frozen.variants
        )
        if encoded(rebuilt) != encoded(frozen):
            raise ValueError("FROZEN_REQUEST_DRIFT")
