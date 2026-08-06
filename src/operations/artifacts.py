"""Atomic local DuckDB and FAISS snapshot/backup bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from src.core import StorageSettings
from src.repositories.locking import duckdb_file_lock


class ArtifactBundleError(RuntimeError):
    """Raised when a local storage bundle cannot be completed."""


def create_backup(
    storage: StorageSettings,
    *,
    now: datetime | None = None,
) -> Path:
    """Create one immutable backup under the configured backup root."""

    return _create_bundle(storage, storage.backup_root, "backup", now=now)


def create_snapshot(
    storage: StorageSettings,
    *,
    now: datetime | None = None,
) -> Path:
    """Create one immutable snapshot under the configured snapshot root."""

    return _create_bundle(storage, storage.snapshot_root, "snapshot", now=now)


def _create_bundle(
    storage: StorageSettings,
    destination_root: Path,
    bundle_type: str,
    *,
    now: datetime | None,
) -> Path:
    database = storage.duckdb_path
    if not database.is_file():
        raise ArtifactBundleError("DuckDB source file does not exist")
    destination_root.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    bundle_name = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    destination = destination_root / bundle_name
    if destination.exists():
        raise ArtifactBundleError("artifact bundle destination already exists")
    temporary = Path(tempfile.mkdtemp(prefix=".bundle-", dir=destination_root))
    try:
        with duckdb_file_lock(database):
            database_copy = temporary / "platform.duckdb"
            shutil.copy2(database, database_copy)
            faiss_archive = temporary / "faiss.tar.gz"
            with tarfile.open(faiss_archive, "w:gz") as archive:
                if storage.faiss_root.is_dir():
                    archive.add(storage.faiss_root, arcname="faiss")
        manifest = {
            "bundle_type": bundle_type,
            "created_at": timestamp.isoformat(),
            "duckdb_sha256": _sha256(database_copy),
            "faiss_archive_sha256": _sha256(faiss_archive),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise ArtifactBundleError("failed to create local artifact bundle") from exc
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
