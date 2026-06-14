"""Shared source infrastructure: HTTP, offline fixtures, content hashing.

The live :class:`HttpClient` adds two production concerns the MVP would otherwise
gloss over:

* **Resilience** — a retry/backoff adapter so a transient 429/5xx from a free
  government endpoint doesn't fail a whole reconciliation cycle.
* **Cost control** — a small on-disk response cache (SOLUTION_PLAN §7). Re-running
  the pipeline, or re-verifying a record inside the cache TTL, never re-hits the
  network. Offline mode never touches either path.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from directory_pipeline.config import Settings
from directory_pipeline.logging_config import get_logger

log = get_logger("sources")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_hash(payload: Any) -> str:
    """Stable content hash of a source payload, stored in the audit trail so an
    update is reproducible and defensible months later (SOLUTION_PLAN §6.7)."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:32]


class OfflineModeError(RuntimeError):
    """Raised when offline mode is requested but no fixture exists for a call."""


class HttpClient:
    """Thin JSON HTTP wrapper: shared session, retry/backoff, optional disk cache."""

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or self._build_session(settings)
        self.session.headers.setdefault("User-Agent", "provider-directory-pipeline/0.1")

    @staticmethod
    def _build_session(settings: Settings) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=settings.http_retries,
            backoff_factor=0.5,  # 0.5s, 1s, 2s, ...
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # -- cache ------------------------------------------------------------ #
    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path:
        key = json.dumps({"url": url, "params": params or {}}, sort_keys=True, default=str)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self.settings.cache_dir / f"{digest}.json"

    def _cache_read(self, path: Path) -> Any | None:
        if not self.settings.http_cache or not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.settings.http_cache_ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_write(self, path: Path, payload: Any) -> None:
        if not self.settings.http_cache:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:  # caching is best-effort, never fatal
            log.debug("cache write failed for %s: %s", path, exc)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        cache_path = self._cache_path(url, params)
        cached = self._cache_read(cache_path)
        if cached is not None:
            log.debug("cache hit: %s", url)
            return cached
        resp = self.session.get(url, params=params, timeout=self.settings.http_timeout)
        resp.raise_for_status()
        payload = resp.json()
        self._cache_write(cache_path, payload)
        return payload


def load_fixture(settings: Settings, *parts: str) -> Any | None:
    """Load a bundled JSON fixture, or ``None`` if it does not exist."""
    path: Path = settings.fixtures_dir.joinpath(*parts)
    if not path.exists():
        log.debug("fixture miss: %s", path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))
