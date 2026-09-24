"""Shared entry types for collection, curation and delivery."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    title: str
    url: str
    source: str
    published: datetime | None
    summary: str
    kind: str


@dataclass(frozen=True, slots=True)
class CuratedEntry:
    entry: Entry
    topic: str
    score: int
