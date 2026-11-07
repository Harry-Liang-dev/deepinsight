"""Byte-pinned, read-only adapter to W5's existing benchmark and scorer."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_eval.models import DatasetCase, EvaluationResult, SourceRef, identity
from research_eval.storage import TraceRecorder

W5_DELIVERY = "c5ef145eb0feb8a20cb62b4e8af9fe5ccf19bc7a"
W5_MANIFEST = "4b6627e2da2d89b4c8135bfe0ba5ea11afd3e620e4c0710568a6607b1ba71f66"
W5_ROOT = Path(
    os.environ.get(
        "DEEPINSIGHT_W5_BENCHMARK_ROOT",
        str(Path.home() / ".local/share/deepinsight/benchmark-v1"),
    )
)


def sha(raw: bytes) -> str:
    """Hash exact bytes, without interpreting their financial meaning."""
    return hashlib.sha256(raw).hexdigest()


class W5Benchmark:
    """Adopt a genuine W5 Git delivery, not a caller-supplied evaluator plugin."""

    pinned_delivery = W5_DELIVERY
    pinned_manifest = W5_MANIFEST
    calibration_profile: str | None = None

    def __init__(self, root: Path = W5_ROOT) -> None:
        self.root = root.resolve()
        manifest_bytes = (root / "EVIDENCE_MANIFEST.json").read_bytes()
        if sha(manifest_bytes) != self.pinned_manifest:
            raise ValueError("W5_MANIFEST_DRIFT")
        if self.git("EVIDENCE_MANIFEST.json", self.pinned_delivery) != manifest_bytes:
            raise ValueError("W5_DELIVERY_BLOB_DRIFT")
        self.manifest = json.loads(manifest_bytes)
        self.pinned_files = {r["path"]: r for r in self.manifest["files"]}
        for relative, row in self.pinned_files.items():
            raw = self.read(relative)
            if (
                self.git(relative, self.manifest["source_commit"]) != raw
                or subprocess.check_output(
                    ["git", "-C", str(root), "hash-object", "--stdin"], input=raw
                )
                .decode()
                .strip()
                != row["git_blob"]
            ):
                raise ValueError("W5_SOURCE_BLOB_DRIFT")
        # Only this verified package may satisfy the external import.
        for name, module in tuple(sys.modules.items()):
            if name == "financial_benchmark" or name.startswith("financial_benchmark."):
                if not Path(module.__file__ or "").resolve().is_relative_to(self.root):
                    raise ValueError("W5_MODULE_SHADOWING")
        sys.path.insert(0, str(self.root))
        try:
            self.io = importlib.import_module("financial_benchmark.io")
            self.models = importlib.import_module("financial_benchmark.models")
            self.cli = importlib.import_module("financial_benchmark.cli")
            self.comparison = importlib.import_module("financial_benchmark.comparison")
            self.evaluator_module = importlib.import_module(
                "financial_benchmark.evaluator"
            )
            self.port = importlib.import_module(
                "financial_benchmark.w1_adapter"
            ).W1ScorerPort(
                root,
                **(
                    {"calibration_profile": self.calibration_profile}
                    if self.calibration_profile
                    else {}
                ),
            )
        finally:
            sys.path.remove(str(self.root))
        self.cases = self.port.cases
        self.traces = self.port.traces
        self.protocol_sha256: str = self.port.protocol_sha256
        self.evaluator_id: str = self.port.evaluator_id

    def git(self, relative: str, commit: str) -> bytes:
        """Read the actual specified Git object, never a PASS field."""
        return subprocess.check_output(
            ["git", "-C", str(self.root), "show", commit + ":" + relative]
        )

    def read(self, relative: str) -> bytes:
        """Check every consumed published artifact against the signed delivery bytes."""
        path = self.root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("W5_ARTIFACT_PATH")
        row = self.pinned_files.get(relative)
        raw = path.read_bytes()
        if row is None or sha(raw) != row["sha256"]:
            raise ValueError("W5_ARTIFACT_DRIFT")
        return raw

    def export(self, case_id: str) -> dict[str, Any]:
        """Use W5's public developer whitelist; no historical answers or labels."""
        own = self.cases[case_id]
        result: dict[str, Any] = self.cli.developer_export(self.root, own)
        for ref in [*own.source_snapshot_refs, own.evidence_catalog_ref]:
            self.read(ref.path)
        return result

    def project(self, case_id: str) -> DatasetCase:
        """Preserve Claims/source maps; reject unbound question contracts."""
        exported = self.export(case_id)
        own = self.cases[case_id]
        if own.original_complete_claim is None:
            raise ValueError("W5_QUESTION_CASE_REQUIRES_VERSIONED_QUESTION_CONTRACT")
        raw_hashes = own.provenance.get("source_document_hashes")
        if raw_hashes is None:
            raise ValueError("W5_SOURCE_DOCUMENT_MAPPING_NOT_PUBLISHED")
        refs = {ref.sha256: ref for ref in own.source_snapshot_refs}
        sources = []
        for source_id, digest in raw_hashes.items():
            ref = refs[digest]
            if ref.kind != "HISTORICAL_SOURCE:" + source_id:
                raise ValueError("W5_SOURCE_MEMBERSHIP")
            sources.append(
                SourceRef(
                    source_id=source_id,
                    path=str(self.root / ref.path),
                    sha256=digest,
                    available_at=self.io.clock(own.clocks[source_id]["available_at"]),
                    license="W5_DEVELOPER_EXPORT_READ_ONLY_HISTORICAL_EVALUATION_NOT_LIVE_GRANT",
                )
            )
        catalog = self.io.strict_json(self.read(own.evidence_catalog_ref.path))
        handles: dict[str, str] = {}
        metadata: dict[str, str] = {}
        for row in catalog:
            key = row.get("handle", row.get("fragment_id"))
            if key in handles or key in metadata or not isinstance(key, str):
                raise ValueError("W5_CATALOG_IDENTITY")
            if (
                row["source_id"] == "TRUSTED_HISTORICAL_CONTEXT"
                and row.get("authority_kind", row.get("kind")) == "SYSTEM_METADATA"
            ):
                metadata[key] = identity(row)
            elif row["source_id"] in raw_hashes:
                handles[key] = row["source_id"]
            else:
                raise ValueError("W5_CATALOG_IDENTITY")
        rights = sha(self.io.canonical(own.rights_and_access_profile))
        # Full exported source snapshots and catalog remain present; no compression.
        visible = dict(
            w5_task_identity=self.io.task_fingerprint(own),
            w5_source_context_fingerprint=self.io.case_fingerprint(own),
            w5_rights_fingerprint=rights,
            task=exported,
            evidence_catalog=catalog,
            archived_metadata_handles=metadata,
            reference_binding_scope=(
                "W1 SourceRef checks source spans only; archived SYSTEM_METADATA "
                "remains visible, never a current permission or economic source. "
                "W5 retains its full original catalog checks."
            ),
            source_documents=[
                self.visible_source(ref) for ref in own.source_snapshot_refs
            ],
        )
        return DatasetCase(
            case_id=case_id,
            task_kind=(
                "technical"
                if own.task_family == "TECHNICAL_SCHEMA_PROBE"
                else "financial"
            ),
            specialist_role=(
                "technical_schema_probe"
                if own.task_family == "TECHNICAL_SCHEMA_PROBE"
                else "fundamental_analyst"
            ),
            full_claim=own.original_complete_claim,
            research_as_of=self.io.clock(own.research_as_of),
            sources=tuple(sources),
            handles=handles,
            visible_input=visible,
            authority_binding=identity(
                ["W5_READONLY_EXPORT_NOT_CURRENT_AUTHORITY", case_id, rights]
            ),
            gold_status="NONE",
            holdout=False,
            local_export_allowed=False,
        )

    def visible_source(self, ref: Any) -> dict[str, Any]:
        """Keep normalized text and separate original HTTP byte references."""
        raw = self.read(ref.path)
        if raw.startswith(b"\x1f\x8b"):
            return dict(
                ref=ref.model_dump(),
                representation="ORIGINAL_GZIP_HTTP_BYTES_REFERENCE",
                text=None,
                meaning=(
                    "Raw hash verified; corresponding published normalized source "
                    "text included separately, no new extraction"
                ),
            )
        return dict(
            ref=ref.model_dump(),
            representation="EXACT_PUBLISHED_NORMALIZED_TEXT",
            text=raw.decode("utf-8"),
        )

    def validate_projection(self, case: DatasetCase) -> None:
        """Prevent task/rights/handle drift that the older port alone does not check."""
        if identity(case) != identity(self.project(case.case_id)):
            raise ValueError("W1_W5_EXACT_PROJECTION_DRIFT")

    def evaluate(
        self, case: DatasetCase, assistant: bytes, mechanical: EvaluationResult
    ) -> EvaluationResult:
        """Call the unchanged real W5 scorer; never manufacture independent status."""
        self.validate_projection(case)
        return EvaluationResult.model_validate_json(
            self.port.evaluate(case, assistant, mechanical).model_dump_json()
        )

    def baseline_prompt(self) -> tuple[str, dict[str, Any]]:
        """Reuse the published six-field baseline; no fictitious W3 candidate."""
        trace = next(t for t in self.traces if t.case_id == "HIST-MINIMAL2-PROBE-02")
        request = self.io.strict_json(self.read(trace.request.path))
        prefix, schema = request["instructions"].split("\nMINIMAL_OUTPUT_CONTRACT=")
        from tools.minimal_semantic_carrier import proposal_schema

        if self.io.strict_json(schema) != proposal_schema():
            raise ValueError("BASELINE_SCHEMA_DRIFT")
        return prefix, dict(
            request_ref=trace.request.model_dump(),
            instructions_sha256=sha(request["instructions"].encode()),
            extraction="Exact prefix; current compiler appends same six-field Schema",
            original_operation_reused=False,
        )

    def stage_evaluator(self, destination: Path, case_ids: list[str]) -> Any:
        """Stage exact scoring data bytes, without creating another registry."""
        paths = {
            "benchmark_data/EVALUATOR_PROTOCOL.json",
            "benchmark_data/APPROVED_DIAGNOSTIC_REVIEWS.json",
            "benchmark_data/GOLD_AUTHORITY_POLICY.json",
        }
        for key in case_ids:
            own = self.cases[key]
            paths.update(
                r.path for r in [*own.source_snapshot_refs, own.evidence_catalog_ref]
            )
            if own.evaluation_reference:
                paths.add(own.evaluation_reference.path)
        recorder = TraceRecorder(destination)
        for path in sorted(paths):
            recorder.write(path, self.read(path))
        recorder.record(
            "UPSTREAM_PIN.json",
            dict(
                delivery=W5_DELIVERY,
                manifest=W5_MANIFEST,
                copied_paths=sorted(paths),
                purpose="Read-only scoring data cache; no separate benchmark or Gold",
            ),
        )
        return self.evaluator_module.Evaluator(destination)
