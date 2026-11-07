"""Durable source-native acquisition, never a publication/PIT authority.

An opt-in ingestion session persists bytes and an AcquisitionReceipt before the
caller may decode or normalize. Legacy data cannot acquire this lineage later.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field

from src.schemas.phase5d_evidence import AcquisitionReceipt, ClockModel
from src.schemas.research_data_quality import quality_hash
from src.schemas.research_v2_shared import Reference
from src.schemas.temporal import require_utc_aware


def blob_hash(raw: bytes) -> str:
    """Hash unmodified bytes, not normalized data."""
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    """Serialize local sidecars deterministically, rejecting nonfinite values."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def durable_blob(path: Path, raw: bytes) -> None:
    """Fsync and exclusively link a complete file; never overwrite history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("NATIVE_SYMLINK_DENIED")
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("NATIVE_IMMUTABLE_CONFLICT")
        # Existing bytes can be a surviving link from a failed commit. Reassert
        # both durability barriers; equality alone is never an acknowledgement.
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return
    fd, name = tempfile.mkstemp(prefix=".native-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path, follow_symlinks=False)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("NATIVE_IMMUTABLE_CONFLICT") from None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


class NativeManifest(ClockModel):
    """Wrapper around the existing Phase5D acquisition schema, not new eligibility."""

    schema_version: Literal["source_native_preservation_v1"] = (
        "source_native_preservation_v1"
    )
    acquisition: AcquisitionReceipt
    request_parameters: dict[str, str]
    response_metadata: dict[str, str]
    status_code: int
    representation: Literal["HTTP_ENTITY_BYTES", "MCP_SDK_RESULT_JSON"]
    transport_endpoint: str | None = None
    ingested_at: datetime
    retention_authority: str = Field(min_length=1)
    normalization_version: str = Field(min_length=1)
    source_publication_at: None = None
    publication_semantics: Literal["NOT_ASSERTED_RAW_FIELDS_RETAINED"] = (
        "NOT_ASSERTED_RAW_FIELDS_RETAINED"
    )
    pit_eligible: Literal[False] = False


class NativePreserver:
    """One explicitly authorized provider/asset/run; no data acquisition itself."""

    def __init__(
        self,
        directory: Path,
        *,
        provider: str,
        owner: str,
        run_id: str,
        retention_authority: str,
        allowed_endpoints: tuple[str, ...],
        normalization_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind a new run and reviewed retention scope, never infer source rights."""
        if (
            not all(
                (provider, owner, run_id, retention_authority, normalization_version)
            )
            or not allowed_endpoints
        ):
            raise ValueError("NATIVE_EXPLICIT_SCOPE_REQUIRED")
        self.directory = directory
        self.provider, self.owner, self.run_id = provider, owner, run_id
        self.retention_authority = retention_authority
        self.allowed_endpoints = allowed_endpoints
        self.normalization_version = normalization_version
        self.clock = clock or (lambda: datetime.now(UTC))
        self.receipts: list[str] = []
        # Process-local acknowledgements, never reconstructed from file existence.
        # A new process explicitly recovers pinned transactions before consumption.
        self._completed_manifests: set[str] = set()
        self._completed_lineages: set[str] = set()
        self.directory.mkdir(parents=True, exist_ok=True)
        for parent in (self.directory, self.directory.parent):
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        durable_blob(
            directory / "session.json",
            canonical_bytes(
                dict(
                    provider=provider,
                    owner=owner,
                    run_id=run_id,
                    retention_authority=retention_authority,
                    endpoints=allowed_endpoints,
                    normalization_version=normalization_version,
                )
            ),
        )

    def request(self, url: str) -> tuple[str, dict[str, str]]:
        """Check exact host/path prefixes and allowlisted nonsecret query keys."""
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "mcp"}
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("NATIVE_ENDPOINT_DENIED")
        endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if not any(
            endpoint == p or endpoint.startswith(p.rstrip("/") + "/")
            for p in self.allowed_endpoints
        ):
            raise ValueError("NATIVE_ENDPOINT_DENIED")
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        allowed = {
            "symbols",
            "symbol",
            "start",
            "end",
            "timeframe",
            "adjustment",
            "feed",
            "limit",
            "sort",
            "page_token",
            "include_content",
            "zoom",
            "max",
        }
        if len(dict(pairs)) != len(pairs) or any(k not in allowed for k, _ in pairs):
            raise ValueError("NATIVE_REQUEST_PARAMETER_DENIED")
        params = dict(pairs)
        symbol = params.get("symbols", params.get("symbol"))
        if symbol is not None and symbol != self.owner.removeprefix("US:"):
            raise ValueError("NATIVE_REQUEST_OWNER")
        return endpoint, params

    def preserve(
        self,
        url: str,
        raw: bytes,
        *,
        status: int,
        headers: Mapping[str, str],
        representation: Literal[
            "HTTP_ENTITY_BYTES", "MCP_SDK_RESULT_JSON"
        ] = "HTTP_ENTITY_BYTES",
        transport_endpoint: str | None = None,
    ) -> str:
        """Commit raw bytes, receipt and manifest, then return their verified pin."""
        endpoint, params = self.request(url)
        if representation == "MCP_SDK_RESULT_JSON" and transport_endpoint is None:
            raise ValueError("NATIVE_TRANSPORT_ENDPOINT_REQUIRED")
        if transport_endpoint is not None:
            self.request(transport_endpoint)
        observed = require_utc_aware(self.clock())
        safe = {
            k.lower(): v
            for k, v in headers.items()
            if k.lower()
            in {
                "content-type",
                "content-encoding",
                "etag",
                "last-modified",
                "date",
                "x-request-id",
            }
        }
        encoding = safe.get("content-encoding", "identity").lower()
        if encoding not in {"identity", "gzip", "deflate"}:
            raise ValueError("NATIVE_ENCODING_UNSUPPORTED")
        body_hash = blob_hash(raw)
        revision = safe.get("etag") or "body-sha256:" + body_hash
        receipt = AcquisitionReceipt.model_validate(
            dict(
                artifact_id="source_" + body_hash,
                provider=self.provider,
                endpoint=endpoint,
                owner=self.owner,
                source_run_id=self.run_id,
                revision_id=revision,
                body_base64=base64.b64encode(raw).decode(),
                body_sha256=body_hash,
                size_bytes=len(raw),
                content_encoding=encoding,
                observed_at=observed,
            )
        )
        # Lock only the local manifest transaction; never hold it over network IO.
        with (self.directory / "commit.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            durable_blob(self.directory / (body_hash + ".raw"), raw)
            revision_key = quality_hash(
                dict(endpoint=endpoint, parameters=params, revision=revision)
            )
            durable_blob(
                self.directory / (revision_key + ".revision"), body_hash.encode()
            )
            durable_blob(
                self.directory / (receipt.content_identity + ".acquisition.json"),
                receipt.model_dump_json().encode(),
            )
            ingested = require_utc_aware(self.clock())
            if ingested < observed:
                raise ValueError("NATIVE_ACQUISITION_CHRONOLOGY")
            manifest = NativeManifest(
                acquisition=receipt,
                request_parameters=params,
                response_metadata=safe,
                status_code=status,
                representation=representation,
                transport_endpoint=transport_endpoint,
                ingested_at=ingested,
                retention_authority=self.retention_authority,
                normalization_version=self.normalization_version,
            )
            identity = manifest.content_identity
            durable_blob(
                self.directory / (identity + ".manifest.json"),
                manifest.model_dump_json().encode(),
            )
            self._verify_members(identity)
            self._completed_manifests.add(identity)
            if identity not in self.receipts:
                self.receipts.append(identity)
            return identity

    def verify(self, identity: str) -> NativeManifest:
        """Read-only check; uncertain/restarted transactions require recovery."""
        manifest = self._verify_members(identity)
        if identity not in self._completed_manifests:
            raise ValueError("NATIVE_RECOVERY_REQUIRED")
        return manifest

    def recover(self, identity: str) -> NativeManifest:
        """Explicitly reverify and sync every member without reacquiring data."""
        with (self.directory / "commit.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._completed_manifests.discard(identity)
            manifest = self._verify_members(identity)
            r = manifest.acquisition
            revision = quality_hash(
                dict(
                    endpoint=r.endpoint,
                    parameters=manifest.request_parameters,
                    revision=r.revision_id,
                )
            )
            for name in (
                "session.json",
                r.body_sha256 + ".raw",
                revision + ".revision",
                r.content_identity + ".acquisition.json",
                identity + ".manifest.json",
            ):
                path = self.directory / name
                durable_blob(path, path.read_bytes())
            self._verify_members(identity)
            self._completed_manifests.add(identity)
            return manifest

    def _verify_members(self, identity: str) -> NativeManifest:
        """Check content integrity only; this does not certify durable completion."""
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("NATIVE_MANIFEST_ID")
        manifest = NativeManifest.model_validate_json(
            (self.directory / (identity + ".manifest.json")).read_bytes()
        )
        if manifest.content_identity != identity:
            raise ValueError("NATIVE_MANIFEST_HASH")
        r = manifest.acquisition
        if (r.provider, r.owner, r.source_run_id) != (
            self.provider,
            self.owner,
            self.run_id,
        ):
            raise ValueError("NATIVE_SESSION_BINDING")
        if (
            manifest.retention_authority != self.retention_authority
            or manifest.normalization_version != self.normalization_version
        ):
            raise ValueError("NATIVE_SESSION_POLICY")
        self.request(r.endpoint)
        if (
            manifest.representation == "MCP_SDK_RESULT_JSON"
            and manifest.transport_endpoint is None
        ):
            raise ValueError("NATIVE_TRANSPORT_ENDPOINT_REQUIRED")
        if manifest.transport_endpoint is not None:
            self.request(manifest.transport_endpoint)
        raw = (self.directory / (r.body_sha256 + ".raw")).read_bytes()
        if (
            blob_hash(raw) != r.body_sha256
            or len(raw) != r.size_bytes
            or base64.b64decode(r.body_base64, validate=True) != raw
        ):
            raise ValueError("NATIVE_RAW_HASH")
        if (
            self.directory / (r.content_identity + ".acquisition.json")
        ).read_bytes() != r.model_dump_json().encode():
            raise ValueError("NATIVE_ACQUISITION_HASH")
        if r.observed_at > manifest.ingested_at:
            raise ValueError("NATIVE_ACQUISITION_CHRONOLOGY")
        revision_key = quality_hash(
            dict(
                endpoint=r.endpoint,
                parameters=manifest.request_parameters,
                revision=r.revision_id,
            )
        )
        if (
            self.directory / (revision_key + ".revision")
        ).read_bytes() != r.body_sha256.encode():
            raise ValueError("NATIVE_REVISION_BINDING")
        return manifest

    def bind(
        self,
        normalized: Mapping[str, Any],
        *,
        references: tuple[str, ...] | None = None,
    ) -> str:
        """Durably link a normalized record before publication, never grant facts."""
        refs = references if references is not None else tuple(self.receipts)
        if not refs:
            raise ValueError("NATIVE_SOURCE_UNAVAILABLE")
        for ref in refs:
            if not 200 <= self.verify(ref).status_code < 300:
                raise ValueError("NATIVE_FAILED_SOURCE")
        materialized = require_utc_aware(self.clock())
        row = dict(
            schema_version="native_normalization_lineage_v1",
            provider=self.provider,
            owner=self.owner,
            source_run=self.run_id,
            native_manifests=refs,
            normalization_version=self.normalization_version,
            normalized=dict(normalized),
            normalized_sha256=blob_hash(canonical_bytes(normalized)),
            materialized_at=materialized.isoformat(),
            pit_eligible=False,
        )
        if any(materialized < self.verify(ref).ingested_at for ref in refs):
            raise ValueError("NATIVE_NORMALIZATION_CHRONOLOGY")
        identity = quality_hash(row)
        durable_blob(
            self.directory / (identity + ".lineage.json"), canonical_bytes(row)
        )
        self._completed_lineages.add(identity)
        return identity

    def recover_lineage(self, identity: str) -> None:
        """Recover an exact pinned lineage and its complete native dependencies."""
        self._completed_lineages.discard(identity)
        row = self._lineage_members(identity)
        for ref in row["native_manifests"]:
            self.recover(ref)
        path = self.directory / (identity + ".lineage.json")
        durable_blob(path, canonical_bytes(row))
        self._completed_lineages.add(identity)

    def _lineage_members(self, identity: str) -> dict[str, Any]:
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("NATIVE_LINEAGE_ID")
        row = json.loads((self.directory / (identity + ".lineage.json")).read_bytes())
        if quality_hash(row) != identity:
            raise ValueError("NATIVE_LINEAGE_HASH")
        if (
            row["provider"],
            row["owner"],
            row["source_run"],
            row["normalization_version"],
        ) != (self.provider, self.owner, self.run_id, self.normalization_version):
            raise ValueError("NATIVE_SESSION_BINDING")
        return dict(row)

    def link_evidence(
        self, *, lineage: str, evidence: Mapping[str, Any], bundle_id: str
    ) -> str:
        """Bind canonical Evidence/Bundle identity without changing either schema."""
        row = self._lineage_members(lineage)
        if not bundle_id:
            raise ValueError("NATIVE_LINEAGE_HASH")
        if lineage not in self._completed_lineages:
            raise ValueError("NATIVE_RECOVERY_REQUIRED")
        for ref in row["native_manifests"]:
            self.verify(ref)
        # The canonical identity itself is still verified by the existing resolver.
        ref = Reference.model_validate_json(canonical_bytes(evidence))
        ref.require("EVIDENCE")
        body = dict(
            lineage=lineage,
            evidence=dict(evidence),
            bundle_id=bundle_id,
            pit_eligible=False,
        )
        identity = quality_hash(body)
        durable_blob(
            self.directory / (identity + ".evidence.json"), canonical_bytes(body)
        )
        return identity
