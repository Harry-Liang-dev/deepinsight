"""Run one explicit, minimal Qwen embedding transport smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from src.core import load_settings
from src.services import (
    EmbeddingConfigurationError,
    EmbeddingServiceError,
    QwenEmbeddingService,
)

_PUBLIC_SMOKE_TEXT = (
    "Public Sector research transport check; no private or credential data."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/live_qwen_embedding"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute exactly one embedding request and persist safe metadata."""

    args = _parser().parse_args(argv)
    settings = load_settings()
    stamp = datetime.now(UTC)
    run_dir = args.output_root / stamp.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    service = QwenEmbeddingService(
        settings.qwen,
        dimension=settings.qwen.embedding_dimension,
        batch_size=settings.qwen.embedding_batch_size,
    )
    common: dict[str, object] = {
        "run_id": run_dir.name,
        "timestamp": stamp.isoformat(),
        "provider": service.provider_name,
        "model": service.model_name,
        "remote_storage": False,
        "max_retries": settings.qwen.max_retries,
        "payload_class": "public_non_sensitive_transport_smoke",
        "secrets_transferred": 0,
    }
    try:
        vector = service.embed(_PUBLIC_SMOKE_TEXT)
        manifest = {
            **common,
            "status": "ok",
            "error_code": None,
            "request_count": service.request_count,
            "embedding_count": service.embedding_count,
            "vector_dimension": len(vector),
            "retry_count": 0 if settings.qwen.max_retries == 0 else None,
            "proxy_mode": service.proxy_mode,
            "transport_mode": service.transport_mode,
        }
        exit_code = 0
    except EmbeddingConfigurationError as exc:
        manifest = {
            **common,
            "status": "error",
            "error_code": exc.code,
            "error_message_safe": str(exc),
            "configuration_stage": exc.configuration_stage,
            "provider": exc.provider,
            "model": exc.model,
            "proxy_mode": exc.proxy_mode,
            "transport_mode": exc.transport_mode,
            "request_count": service.request_count,
            "embedding_count": service.embedding_count,
            "vector_dimension": service.dimension,
            "retry_count": 0,
        }
        exit_code = 2
    except EmbeddingServiceError as exc:
        manifest = {
            **common,
            "status": "error",
            "error_code": "embedding_request_error",
            "error_message_safe": str(exc),
            "configuration_stage": None,
            "proxy_mode": service.proxy_mode,
            "transport_mode": service.transport_mode,
            "request_count": service.request_count,
            "embedding_count": service.embedding_count,
            "vector_dimension": service.dimension,
            "retry_count": 0 if settings.qwen.max_retries == 0 else None,
        }
        exit_code = 1
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps({**manifest, "manifest_path": str(manifest_path)}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
