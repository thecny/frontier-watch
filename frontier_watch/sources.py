"""Collect recent papers, hardware news, and open-source repositories."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .models import Entry


MAX_RESPONSE_BYTES = 2_000_000
HTTP_TIMEOUT_SECONDS = 15
USER_AGENT = "frontier-watch/0.1"

ARXIV_RSS = "https://rss.arxiv.org/rss/eess.SP+cs.AR+eess.SY+cs.ET"
CNX_RSS = "https://www.cnx-software.com/feed/"
HACKADAY_RSS = "https://hackaday.com/blog/feed/"

HttpGet = Callable[[str, dict[str, str]], bytes]


def default_http_get(url: str, headers: dict[str, str]) -> bytes:
    """GET a public source with a finite timeout and response size."""
    request = Request(url, headers=headers)
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)


def _get_bounded(url: str, headers: dict[str, str], http_get: HttpGet) -> bytes:
    data = http_get(url, headers)
    if not isinstance(data, bytes):
        raise TypeError("HTTP source returned non-bytes data")
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("HTTP response exceeds size limit")
    return data


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _element_text(element: ElementTree.Element | None) -> str:
    return "" if element is None else "".join(element.itertext())


def _first_text(element: ElementTree.Element, *names: str) -> str:
    for name in names:
        value = _element_text(_child(element, name)).strip()
        if value:
            return value
    return ""


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(html.unescape(value))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value.strip())
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _rss_link(item: ElementTree.Element) -> str:
    for link in item:
        if _local_name(link.tag) != "link":
            continue
        if link.get("rel", "alternate") != "alternate":
            continue
        return (link.get("href") or _element_text(link)).strip()
    return ""


def _parse_feed(data: bytes, source: str, kind: str) -> list[Entry]:
    root = ElementTree.fromstring(data)
    root_name = _local_name(root.tag)
    if root_name == "feed":
        items = [child for child in root if _local_name(child.tag) == "entry"]
    elif root_name == "rss":
        channel = _child(root, "channel")
        if channel is None:
            raise ValueError("RSS channel missing")
        items = [child for child in channel if _local_name(child.tag) == "item"]
    elif root_name == "RDF":
        items = [child for child in root if _local_name(child.tag) == "item"]
    else:
        raise ValueError("Unsupported feed format")

    entries: list[Entry] = []
    for item in items:
        title = _clean_text(_first_text(item, "title"))
        url = _rss_link(item)
        published = _parse_date(_first_text(item, "published", "pubDate", "date", "updated"))
        if not (title and url and published):
            continue
        summary = _clean_text(_first_text(item, "summary", "description", "encoded", "content"))
        item_id = _first_text(item, "id", "guid") or item.get(
            "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", url
        )
        entries.append(
            Entry(
                id=item_id,
                title=title,
                url=url,
                source=source,
                published=published,
                summary=summary,
                kind=kind,
            )
        )
    return entries


def _parse_repositories(data: bytes) -> list[Entry]:
    payload = json.loads(data)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Invalid GitHub search response")
    entries: list[Entry] = []
    for repo in payload["items"]:
        if not isinstance(repo, dict):
            continue
        name = repo.get("full_name")
        url = repo.get("html_url")
        published = _parse_date(repo.get("created_at") or "")
        description = repo.get("description")
        summary = _clean_text(description) if isinstance(description, str) else ""
        if not (isinstance(name, str) and isinstance(url, str) and name and url and published and summary):
            continue
        entries.append(
            Entry(
                id=f"github:{repo.get('id', url)}",
                title=name,
                url=url,
                source="GitHub",
                published=published,
                summary=summary,
                kind="project",
            )
        )
    return entries


def _github_search_url(topic: str, since: str) -> str:
    query = f"{topic} in:name,description,readme created:>={since}"
    return "https://api.github.com/search/repositories?" + urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": 30}
    )


def fetch_all(
    now: datetime,
    http_get: HttpGet = default_http_get,
    github_token: str | None = None,
) -> tuple[list[Entry], list[str]]:
    """Fetch independent sources and return entries alongside source errors.

    Each arXiv run makes one request. Feed dates are preserved for curation;
    missing dates are omitted rather than treated as newly published.
    """
    entries: list[Entry] = []
    errors: list[str] = []
    common_headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml"}
    feeds = (
        ("arXiv", ARXIV_RSS, "paper"),
        ("CNX Software", CNX_RSS, "news"),
        ("Hackaday", HACKADAY_RSS, "news"),
    )
    for source, url, kind in feeds:
        try:
            entries.extend(_parse_feed(_get_bounded(url, common_headers, http_get), source, kind))
        except Exception as exc:
            errors.append(f"{source}: {type(exc).__name__}")

    since = (now.astimezone(timezone.utc) - timedelta(days=14)).date().isoformat()
    github_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        github_headers["Authorization"] = f"Bearer {github_token}"
    for topic in ("fpga", "dsp", "embedded"):
        try:
            url = _github_search_url(topic, since)
            entries.extend(_parse_repositories(_get_bounded(url, github_headers, http_get)))
        except Exception as exc:
            errors.append(f"GitHub {topic.upper()}: {type(exc).__name__}")
    return entries, errors
