"""Byte-pinned public prompt cores; these data never grant runtime permission."""

import hashlib
import json
from pathlib import Path


def prompt_cores() -> dict[str, str]:
    """Load exact approved prompt bytes; reject local drift before compilation."""
    root = Path(__file__).parent / "prompts"
    rows = json.loads((root / "manifest.json").read_bytes())["variants"]
    result = {}
    for row in rows:
        path = root / row["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("PROMPT_PATH_ESCAPE")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("PROMPT_CORE_DRIFT")
        result[row["variant_id"]] = raw.decode("utf-8")
    return result
