"""Select recent, relevant entries and provide stable keys for sent state."""

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import CuratedEntry, Entry


DEFAULT_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "DSP": ("dsp", "digital signal processing", "signal processing", "数字信号处理", "信号处理"),
    "FPGA": ("fpga", "field-programmable gate array", "现场可编程门阵列"),
    "可重构计算": ("reconfigurable", "可重构"),
    "嵌入式": ("embedded", "firmware", "microcontroller", "嵌入式", "单片机", "微控制器"),
    "硬件": ("hardware", "asic", "soc", "risc-v", "semiconductor", "verilog", "vhdl", "rtl", "芯片设计", "硬件"),
}


def canonical_url(url: str) -> str:
    """Return a stable HTTP(S) URL without fragments or tracking parameters."""
    if not isinstance(url, str):
        return ""
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return ""
    if (
        scheme not in {"http", "https"}
        or not host
        or re.search(r"\s", parts.netloc)
        or parts.username
        or parts.password
    ):
        return ""

    if ":" in host:
        host = f"[{host}]"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if not port or default_port else f"{host}:{port}"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    query = urlencode(sorted(query_pairs))
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def entry_keys(entry: Entry) -> set[str]:
    """Return the exact keys used by selection and persisted sent state."""
    keys = set()
    if isinstance(entry.id, str) and entry.id.strip():
        keys.add(entry.id.strip())
    url = canonical_url(entry.url)
    if url:
        keys.add(f"url:{url}")
    return keys


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _matches(text: str, term: str) -> bool:
    term = term.strip().casefold()
    if not term:
        return False
    pattern = re.escape(term)
    if term[0].isascii() and term[0].isalnum():
        pattern = r"(?<![a-z0-9])" + pattern
    if term[-1].isascii() and term[-1].isalnum():
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, text.casefold()) is not None


def _topic_score(entry: Entry, keywords: Mapping[str, tuple[str, ...]]) -> tuple[str, int]:
    title = entry.title.strip()
    summary = entry.summary if isinstance(entry.summary, str) else ""
    scores = {}
    for topic, terms in keywords.items():
        if not isinstance(topic, str) or not isinstance(terms, (tuple, list)):
            continue
        score = sum(
            3 * _matches(title, term) + _matches(summary, term)
            for term in terms
            if isinstance(term, str)
        )
        if score:
            scores[topic] = score
    if not scores:
        return "", 0
    topic = max(scores, key=scores.get)
    return topic, sum(scores.values())


def select_entries(
    entries: Iterable[Entry],
    seen_ids: Iterable[str],
    now: datetime,
    lookback_hours: float = 72,
    limit: int = 8,
    keywords: Mapping[str, tuple[str, ...]] | None = None,
) -> list[CuratedEntry]:
    """Select one best entry per topic, then fill remaining slots by rank.

    ``keywords`` replaces the default topic rules when supplied. Naive dates
    are interpreted as UTC; missing or malformed publication dates are skipped.
    """
    if not isinstance(now, datetime) or limit <= 0 or lookback_hours <= 0:
        return []
    current = _utc(now)
    oldest = current - timedelta(hours=lookback_hours)
    rules = DEFAULT_KEYWORDS if keywords is None else keywords
    seen = set(seen_ids or ())
    candidates = []

    for entry in entries:
        if (
            not isinstance(entry, Entry)
            or not isinstance(entry.title, str)
            or not entry.title.strip()
            or not isinstance(entry.published, datetime)
        ):
            continue
        keys = entry_keys(entry)
        if not any(key.startswith("url:") for key in keys) or keys & seen:
            continue
        published = _utc(entry.published)
        if not oldest <= published <= current:
            continue
        topic, score = _topic_score(entry, rules)
        if score:
            candidates.append((CuratedEntry(entry, topic, score), published))

    candidates.sort(
        key=lambda item: (-item[0].score, -item[1].timestamp(), canonical_url(item[0].entry.url))
    )
    selected = []
    used = set(seen)

    def add_if_new(curated: CuratedEntry) -> bool:
        keys = entry_keys(curated.entry)
        if keys & used:
            return False
        selected.append(curated)
        used.update(keys)
        return True

    for topic in rules:
        for curated, _ in candidates:
            if curated.topic == topic and add_if_new(curated):
                break
        if len(selected) >= limit:
            return selected

    for curated, _ in candidates:
        add_if_new(curated)
        if len(selected) >= limit:
            break
    return selected
