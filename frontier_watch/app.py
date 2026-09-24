"""One digest run and its persistent delivery state."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .curate import entry_keys, select_entries
from .delivery import format_digest, send_digest
from .models import Entry
from .sources import fetch_all


class SourceError(RuntimeError):
    """No source could provide any usable data during a failed collection."""


@dataclass(frozen=True)
class RunResult:
    status: str
    count: int
    digest: str
    errors: tuple[str, ...]


def load_keywords(path: Path) -> dict[str, tuple[str, ...]]:
    """Load user-selected topic rules from a small JSON mapping."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read topic rules: {path}") from exc
    if (
        not isinstance(data, dict)
        or not data
        or any(
            not isinstance(topic, str)
            or not topic.strip()
            or not isinstance(terms, list)
            or not terms
            or any(not isinstance(term, str) or not term.strip() for term in terms)
            for topic, terms in data.items()
        )
    ):
        raise ValueError(f"Invalid topic rules: {path}")
    return {topic.strip(): tuple(term.strip() for term in terms) for topic, terms in data.items()}


def load_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read delivery state: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sent_ids"), list):
        raise ValueError(f"Invalid delivery state: {path}")
    ids = data["sent_ids"]
    if not all(isinstance(value, str) and value for value in ids):
        raise ValueError(f"Invalid delivery state: {path}")
    return set(ids)


def save_state(path: Path, sent_ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"sent_ids": sorted(sent_ids)}, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".sent-", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def run(
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    state_path: Path = Path("data/sent.json"),
    fetcher: Callable | None = None,
    sender: Callable | None = None,
    env: Mapping[str, str] | None = None,
    channel: str | None = None,
    lookback_hours: int = 72,
    limit: int = 8,
    keywords: Mapping[str, Sequence[str]] | None = None,
) -> RunResult:
    """Collect, select, and deliver one digest, recording IDs after success."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if lookback_hours <= 0 or limit <= 0:
        raise ValueError("lookback_hours and limit must be positive")
    env = os.environ if env is None else env
    fetcher = fetch_all if fetcher is None else fetcher
    sender = send_digest if sender is None else sender
    entries, errors = fetcher(now, github_token=env.get("GITHUB_TOKEN"))
    if not entries and errors:
        raise SourceError("All information sources failed; no digest was sent")
    selected = select_entries(
        entries,
        load_state(state_path),
        now,
        lookback_hours=lookback_hours,
        limit=limit,
        keywords=keywords,
    )
    if not selected:
        return RunResult("empty", 0, "", tuple(errors))
    digest = format_digest(selected, now)
    if dry_run:
        return RunResult("preview", len(selected), digest, tuple(errors))
    sender(digest, channel or env.get("PUSH_CHANNEL", "serverchan"), env)
    sent_ids = load_state(state_path)
    for curated in selected:
        sent_ids.update(entry_keys(curated.entry))
    save_state(state_path, sent_ids)
    return RunResult("sent", len(selected), digest, tuple(errors))
