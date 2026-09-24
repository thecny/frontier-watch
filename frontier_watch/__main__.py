"""Command-line entry point for the daily digest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .app import SourceError, load_keywords, run
from .delivery import DeliveryError
from .models import Entry


def _sample_fetcher(now: datetime, github_token: str | None = None):
    sample_path = Path(__file__).resolve().parent.parent / "examples" / "sample.json"
    examples = json.loads(sample_path.read_text(encoding="utf-8"))
    entries = [
        Entry(
            id=item["id"],
            title=item["title"],
            url=item["url"],
            source=item["source"],
            published=now - timedelta(hours=item["age_hours"]),
            summary=item["summary"],
            kind=item["kind"],
        )
        for item in examples
    ]
    return entries, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSP / FPGA / embedded daily digest")
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending or saving state")
    parser.add_argument("--sample", action="store_true", help="Use offline example items; implies --dry-run")
    parser.add_argument("--channel", choices=["serverchan", "bark", "telegram", "wecom"])
    parser.add_argument("--state", type=Path, default=Path("data/sent.json"))
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--topics", type=Path, help="JSON file that replaces default topic keywords")
    args = parser.parse_args(argv)
    try:
        result = run(
            now=datetime.now(timezone.utc),
            dry_run=args.dry_run or args.sample,
            state_path=args.state,
            fetcher=_sample_fetcher if args.sample else None,
            channel=args.channel,
            lookback_hours=args.lookback_hours,
            limit=args.limit,
            keywords=load_keywords(args.topics) if args.topics else None,
        )
    except (SourceError, ValueError) as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1
    except DeliveryError:
        print("推送失败：请检查渠道凭据、配额和网络；本次条目未记为已发送。", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"运行失败：{type(exc).__name__}；本次条目未记为已发送。", file=sys.stderr)
        return 1
    for error in result.errors:
        print(f"来源警告：{error}", file=sys.stderr)
    if result.status == "preview":
        print(result.digest)
    elif result.status == "sent":
        print(f"已推送 {result.count} 条信息。")
    else:
        print("最近没有新的相关信息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
