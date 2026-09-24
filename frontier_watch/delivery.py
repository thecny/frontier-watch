"""Format a curated digest and deliver it through a phone push channel."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable, Mapping
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .models import CuratedEntry


class DeliveryError(RuntimeError):
    """A digest could not be safely delivered."""


_TITLE = "芯片前沿雷达"
_CHINA_TIME = timezone(timedelta(hours=8))


def format_digest(entries: list[CuratedEntry], now: datetime) -> str:
    """Render readable plain text with a direct link for each item."""
    day = now.astimezone(_CHINA_TIME).date().isoformat()
    sections = [f"{_TITLE} · {day} · {len(entries)} 条"]
    for index, curated in enumerate(entries, start=1):
        entry = curated.entry
        title = " ".join(entry.title.split())
        summary = " ".join(entry.summary.split()) or "暂无简介"
        if len(summary) > 180:
            summary = summary[:179].rstrip() + "…"
        sections.append(
            f"{index}. {title}\n"
            f"主题：{curated.topic} · 来源：{entry.source}\n"
            f"简介：{summary}\n"
            f"原文：{entry.url}"
        )
    return "\n\n".join(sections)


def _default_http_post(url: str, data: bytes, headers: Mapping[str, str]):
    request = Request(url, data=data, headers=dict(headers), method="POST")
    return urlopen(request, timeout=20)


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise DeliveryError(f"缺少推送配置：{key}")
    return value


def _json_payload(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _telegram_chunks(text: str) -> list[str]:
    """Keep each Bot API message within 4096 characters without losing text."""
    chunks = []
    remaining = text
    while len(remaining) > 4096:
        # Prefer a paragraph or line ending near the limit so links stay intact.
        split_at = remaining.rfind("\n\n", 2048, 4096)
        if split_at >= 0:
            split_at += 2
        else:
            split_at = remaining.rfind("\n", 2048, 4096)
            split_at = split_at + 1 if split_at >= 0 else 4096
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


def send_digest(
    text: str,
    channel: str,
    env: Mapping[str, str],
    http_post: Callable | None = None,
) -> None:
    """Deliver once; raise for transport errors and service-level failures.

    ``http_post`` accepts ``(url, data, headers)`` and returns an object
    exposing ``status`` and ``read()``. It may be injected for offline tests.
    """
    channel = channel.strip().lower()
    if not text.strip():
        raise DeliveryError("简报内容为空")

    if channel in ("serverchan", "wechat"):
        key = _required(env, "SERVERCHAN_SENDKEY")
        url = f"https://sctapi.ftqq.com/{quote(key, safe='')}.send"
        data = urlencode({"title": _TITLE, "desp": text}).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    elif channel == "bark":
        key = _required(env, "BARK_DEVICE_KEY")
        base_url = (env.get("BARK_SERVER_URL", "").strip() or "https://api.day.app").rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise DeliveryError("BARK_SERVER_URL 需要是不含查询参数的 HTTPS 地址")
        url = base_url + "/push"
        data = _json_payload({
            "device_key": key,
            "title": _TITLE,
            "body": text,
            "group": "frontier-watch",
        })
        headers = {"Content-Type": "application/json; charset=utf-8"}
    elif channel == "telegram":
        token = _required(env, "TELEGRAM_BOT_TOKEN")
        chat_id = _required(env, "TELEGRAM_CHAT_ID")
        url = f"https://api.telegram.org/bot{quote(token, safe=':')}/sendMessage"
        telegram_parts = _telegram_chunks(text)
        headers = {"Content-Type": "application/json; charset=utf-8"}
    elif channel == "wecom":
        url = _required(env, "WECOM_WEBHOOK_URL")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "qyapi.weixin.qq.com":
            raise DeliveryError("WECOM_WEBHOOK_URL 不是企业微信的 HTTPS Webhook")
        data = _json_payload({"msgtype": "markdown", "markdown": {"content": text}})
        headers = {"Content-Type": "application/json; charset=utf-8"}
    else:
        raise DeliveryError("不支持的推送渠道；请选择 serverchan、bark、telegram 或 wecom")

    if http_post is None:
        http_post = _default_http_post
    payloads = (
        [_json_payload({"chat_id": chat_id, "text": part}) for part in telegram_parts]
        if channel == "telegram" else [data]
    )
    for payload in payloads:
        try:
            response = http_post(url, payload, headers)
            try:
                status = response.status
                body = response.read()
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except Exception:
            # HTTP exceptions often embed the full URL, which may contain a key.
            raise DeliveryError(f"{channel} 推送请求失败") from None

        if not 200 <= status < 300:
            raise DeliveryError(f"{channel} 推送返回 HTTP {status}")
        try:
            result = json.loads(body) if body else {}
        except (TypeError, ValueError):
            raise DeliveryError(f"{channel} 推送响应无效") from None
        if not isinstance(result, dict):
            raise DeliveryError(f"{channel} 推送响应无效")

        if channel in ("serverchan", "wechat"):
            success = result.get("code") == 0
        elif channel == "bark":
            success = result.get("code", 200) == 200
        elif channel == "telegram":
            success = result.get("ok") is True
        else:
            success = result.get("errcode") == 0
        if not success:
            raise DeliveryError(f"{channel} 服务拒绝推送")
