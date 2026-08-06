"""Tests for atomic local backup and snapshot bundles."""

from __future__ import annotations

import hashlib
import json
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.api.services import LocalSnapshotQueryService
from src.core import StorageSettings
from src.operations import ArtifactBundleError, create_backup, create_snapshot

NOW = datetime(2026, 8, 7, 10, 30, tzinfo=UTC)


def _storage(tmp_path: Path) -> StorageSettings:
    database = tmp_path / "duckdb" / "platform.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"deterministic-duckdb-copy")
    faiss_root = tmp_path / "faiss"
    faiss_root.mkdir()
    (faiss_root / "L2.faiss").write_bytes(b"vector-index")
    return StorageSettings(
        duckdb_path=database,
        faiss_root=faiss_root,
        raw_root=tmp_path / "raw",
        snapshot_root=tmp_path / "snapshots",
        backup_root=tmp_path / "backups",
    )


def test_snapshot_bundle_contains_checksummed_database_and_faiss(
    tmp_path: Path,
) -> None:
    """A completed snapshot should be immutable-looking and self-verifiable."""

    storage = _storage(tmp_path)

    bundle = create_snapshot(storage, now=NOW)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    copied = bundle / "platform.duckdb"
    archive = bundle / "faiss.tar.gz"
    assert manifest["bundle_type"] == "snapshot"
    assert manifest["duckdb_sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    assert (
        manifest["faiss_archive_sha256"]
        == hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    with tarfile.open(archive, "r:gz") as tar:
        assert "faiss/L2.faiss" in tar.getnames()
    assert not list(storage.snapshot_root.glob(".bundle-*"))


def test_backup_rejects_missing_database_without_partial_output(
    tmp_path: Path,
) -> None:
    """A missing source must not create an apparently complete backup."""

    storage = StorageSettings(
        duckdb_path=tmp_path / "missing.duckdb",
        faiss_root=tmp_path / "faiss",
        raw_root=tmp_path / "raw",
        snapshot_root=tmp_path / "snapshots",
        backup_root=tmp_path / "backups",
    )

    with pytest.raises(ArtifactBundleError, match="does not exist"):
        create_backup(storage, now=NOW)

    assert not storage.backup_root.exists()


def test_snapshot_query_returns_latest_valid_bundle_for_date(
    tmp_path: Path,
) -> None:
    """API query should expose logical names, not local filesystem paths."""

    storage = _storage(tmp_path)
    first = create_snapshot(storage, now=NOW)
    later = create_snapshot(
        storage,
        now=datetime(2026, 8, 7, 11, 30, tzinfo=UTC),
    )
    (first / "ignored.txt").write_text("older", encoding="utf-8")
    (storage.snapshot_root / "malformed").mkdir()
    (storage.snapshot_root / "malformed" / "manifest.json").write_text(
        "{bad-json",
        encoding="utf-8",
    )

    result = LocalSnapshotQueryService(storage.snapshot_root).get(date(2026, 8, 7))

    assert result is not None
    assert result.duckdb_artifact == "platform.duckdb"
    assert result.faiss_artifacts == ["faiss.tar.gz"]
    assert later.is_dir()
    assert (
        LocalSnapshotQueryService(storage.snapshot_root).get(date(2026, 8, 6)) is None
    )
