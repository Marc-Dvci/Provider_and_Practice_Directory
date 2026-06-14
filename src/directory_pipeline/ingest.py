"""Directory ingestion: load provider records from JSON (SOLUTION_PLAN §9)."""

from __future__ import annotations

import json
from pathlib import Path

from directory_pipeline.config import SAMPLE_DIRECTORY
from directory_pipeline.models import ProviderRecord


def load_directory(path: Path | str | None = None) -> list[ProviderRecord]:
    """Load a directory snapshot.

    Accepts either a top-level JSON list of records or an object with a
    ``"records"`` key. Defaults to the bundled sample directory.
    """
    path = Path(path) if path is not None else SAMPLE_DIRECTORY
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload["records"] if isinstance(payload, dict) else payload
    return [ProviderRecord.model_validate(row) for row in rows]
