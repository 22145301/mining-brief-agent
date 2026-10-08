#!/usr/bin/env python
"""一键抓取脚本：把真实响应抓下来存成 fixture，并更新 `fixtures/sources.json`。

用法：

    uv run python scripts/fetch_fixtures.py                      # 抓全部已登记的源
    uv run python scripts/fetch_fixtures.py --only news          # 只抓新闻源
    uv run python scripts/fetch_fixtures.py --only articles      # 只抓新闻源里列出的文章页
    uv run python scripts/fetch_fixtures.py --proxy http://127.0.0.1:7897
    uv run python scripts/fetch_fixtures.py --only articles --keep-anchor

设计要点：

- 存的是**逐字节原始响应体**，不做任何归一化（ADR-0002）——否则默认路径就会跳过
  解析层，而解析层恰恰是断言最密的地方（关键词分流 A5、储量表 ground truth A6、
  逐字引用 A4）。
- `sources.json` 里的 SHA256 让"这份 fixture 对应哪一次真实抓取"可追溯。
- `anchor_at` 是回放模式下的"现在"，重跑脚本会推进它（ADR-0002）。但**追加抓取**
  要配 `--keep-anchor`：否则每补一个 fixture 都会把已有回放的时间推到新的一天，
  "同一份录播产出同一份日报"就不再成立。
- 抓失败的源**不写进清单**并让脚本以非零码退出 —— 不允许留半份 fixture 冒充完整。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mining_brief.config.sources import ARTICLE_HOSTS, NEWS_SOURCES  # noqa: E402
from mining_brief.contracts import RawResponse  # noqa: E402
from mining_brief.datasources.news import parse_feed  # noqa: E402

FIXTURE_DIR = ROOT / "fixtures"
DEFAULT_UA = "Mozilla/5.0 (compatible; mining-brief/0.1; +contact@example.com)"


@dataclass(frozen=True, slots=True)
class PlannedSource:
    group: str
    url: str
    rel_path: str


def _article_urls_from_feeds() -> list[str]:
    """从**已抓到的**新闻 fixture 里取出文章链接。

    不在这里直接请求 feed —— 那会让"加抓文章页"变成一次隐式的新闻重抓，
    从而在 `--keep-anchor` 下产生新旧混排的窗口。
    """
    urls: list[str] = []
    seen: set[str] = set()
    for path in sorted((FIXTURE_DIR / "news").glob("*-feed.xml")):
        # 复用生产解析器，不另写一套 XML 取链接的代码 —— 两套解析迟早会不一致。
        raw = RawResponse(
            url=path.as_uri(),
            status=200,
            content_type="application/xml",
            body=path.read_bytes(),
            fetched_at=datetime.now(UTC),
        )
        for item in parse_feed(raw):
            if item.url in seen:
                continue
            if urlparse(item.url).netloc not in ARTICLE_HOSTS:
                continue
            seen.add(item.url)
            urls.append(item.url)
    return urls


def _slug(url: str) -> str:
    """从 URL 路径取一个能认出来的文件名，太长就截断（Windows 路径长度很紧）。"""
    path = urlparse(url).path.strip("/").replace("/", "-") or "index"
    return path[:80].strip("-")


def plan(group_filter: str | None) -> list[PlannedSource]:
    planned = [
        PlannedSource("news", source.url, f"news/{source.id}-feed.xml") for source in NEWS_SOURCES
    ]
    planned += [
        PlannedSource("articles", url, f"articles/{_slug(url)}.html")
        for url in _article_urls_from_feeds()
    ]
    if group_filter:
        planned = [p for p in planned if p.group == group_filter]
    return planned


async def fetch_one(client: httpx.AsyncClient, source: PlannedSource) -> dict[str, object]:
    response = await client.get(source.url)
    if response.status_code != 200:
        raise RuntimeError(f"{source.url} 返回 {response.status_code}，不写进 fixture")

    target = FIXTURE_DIR / source.rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)

    return {
        "url": source.url,
        "path": source.rel_path,
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "fetched_at": datetime.now(UTC).isoformat(),
        "content_type": response.headers.get("content-type", ""),
        "status": response.status_code,
        "bytes": len(response.content),
    }


def merge_manifest(
    new_entries: list[dict[str, object]], *, keep_anchor: bool = False
) -> dict[str, object]:
    """新抓的条目覆盖同名 URL 的旧条目，其余原样保留 —— 允许分组分次抓取。

    `keep_anchor=True` 时沿用旧清单的锚点时间。**追加抓取必须用它**：否则补一个
    文章页就把整个回放的时间基准推到今天，已有 fixture 与已有 LLM 录播组成的
    "同一份输入"会产出不同日报（ADR-0002 的确定性就断了）。
    """
    manifest_path = FIXTURE_DIR / "sources.json"
    existing: dict[str, dict[str, object]] = {}
    previous_anchor: str | None = None
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text("utf-8"))
        existing = {str(e["url"]): e for e in payload["entries"]}
        previous_anchor = payload.get("anchor_at")

    for entry in new_entries:
        existing[str(entry["url"])] = entry

    reuse_anchor = keep_anchor and previous_anchor is not None
    anchor = previous_anchor if reuse_anchor else datetime.now(UTC).isoformat()

    payload = {
        "anchor_at": anchor,
        "entries": [existing[key] for key in sorted(existing)],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return payload


async def run(args: argparse.Namespace) -> int:
    planned = plan(args.only)
    if not planned:
        sys.stderr.write(f"没有匹配的源（--only {args.only}）\n")
        return 2

    async with httpx.AsyncClient(
        timeout=args.timeout,
        follow_redirects=True,
        proxy=args.proxy or None,
        headers={"User-Agent": args.user_agent, "Accept": "*/*"},
    ) as client:
        entries: list[dict[str, object]] = []
        for source in planned:
            entry = await fetch_one(client, source)
            sys.stdout.write(
                f"  ok {source.url} -> fixtures/{entry['path']} ({entry['bytes']} bytes)\n"
            )
            entries.append(entry)

    payload = merge_manifest(entries, keep_anchor=args.keep_anchor)
    sys.stdout.write(f"  ok 更新 fixtures/sources.json（anchor_at={payload['anchor_at']}）\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["news", "articles"], default=None, help="只抓某一组源")
    parser.add_argument(
        "--keep-anchor",
        action="store_true",
        help="沿用旧清单的 anchor_at —— 追加 fixture 时用它，避免把回放时钟往前推。",
    )
    parser.add_argument("--proxy", default="", help="如 http://127.0.0.1:7897")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
