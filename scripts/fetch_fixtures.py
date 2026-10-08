#!/usr/bin/env python
"""一键抓取脚本：把真实响应抓下来存成 fixture，并更新 `fixtures/sources.json`。

用法：

    uv run python scripts/fetch_fixtures.py                      # 抓全部已登记的源
    uv run python scripts/fetch_fixtures.py --only news          # 只抓新闻源
    uv run python scripts/fetch_fixtures.py --only articles      # 只抓新闻源里列出的文章页
    uv run python scripts/fetch_fixtures.py --only prices        # 只抓行情
    uv run python scripts/fetch_fixtures.py --proxy http://127.0.0.1:7897

设计要点：

- 存的是**逐字节原始响应体**，不做任何归一化（ADR-0002）——否则默认路径就会跳过
  解析层，而解析层恰恰是断言最密的地方（关键词分流 A5、储量表 ground truth A6、
  逐字引用 A4）。
- `sources.json` 里的 SHA256 让"这份 fixture 对应哪一次真实抓取"可追溯。
- **锚点默认沿用**（`anchor_at`）：补 fixture 不该推进回放时钟，否则"同一份录播
  产出同一份日报"当场失效（ADR-0002）。要换一个时间基准得显式 `--reset-anchor`。
  这一点对行情尤其要紧 —— 抓哪些日期是由锚点算出来的，锚点一动，刚抓的
  fixture 与适配器接下来要问的日期就对不上了。
- 抓失败的源**不写进清单**并让脚本以非零码退出 —— 不允许留半份 fixture 冒充完整。
  唯一的例外是 `faults` 组：它的**目的**就是录下一份失败响应（A7 用），所以非 200
  照存，并在清单里如实记下那个状态码。
- GFEX 的行情接口约 20 次快速请求就开始限流（实测 HTTP 567），所以默认节流
  2 秒；`--throttle 0` 可以关掉。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mining_brief.config.sources import (  # noqa: E402
    ARTICLE_HOSTS,
    NEWS_SOURCES,
    PRICE_SOURCES,
    SINA_KLINE_URL,
)
from mining_brief.contracts import DEFAULT_WINDOW_DAYS, RawResponse  # noqa: E402
from mining_brief.datasources.fetchers import canonical_post_url  # noqa: E402
from mining_brief.datasources.news import parse_feed  # noqa: E402
from mining_brief.datasources.prices import candidate_dates  # noqa: E402

FIXTURE_DIR = ROOT / "fixtures"
MANIFEST_PATH = FIXTURE_DIR / "sources.json"
DEFAULT_UA = "Mozilla/5.0 (compatible; mining-brief/0.1; +contact@example.com)"
_SHANGHAI = ZoneInfo("Asia/Shanghai")

#: `faults` 组唯一的条目：一个**真实**的 503。
#:
#: A7（源故障时简报照样出）需要一个"上游拒绝服务"的样本来测，而这个样本必须是
#: 真的抓下来的 —— 手写一条 status=503 的清单条目谁都能写，但它证明不了任何事，
#: 而且会污染"清单 = 真实抓取记录"这个前提。httpbin 的这个端点专门用来按需回
#: 503，于是它被当成一个普通的数据源抓了一次，走的是同一条代码路径。
FAULT_SAMPLE_URL = "https://httpbin.org/status/503"

#: 碳酸锂的第三方转载日线（新浪的"主力连续"），**只用于交叉核对**。
#: 用 `SINA_KLINE_URL` 拼出来而不是手写一遍，免得两边哪天不一致。
SINA_KLINE_FOR_LITHIUM = SINA_KLINE_URL.format(symbol="lc0")


@dataclass(frozen=True, slots=True)
class PlannedSource:
    group: str
    url: str
    """要**真的请求**的地址。POST 时它是干净的接口地址，参数在 `form` 里 ——
    把参数同时写进查询串会让服务端收到两遍（GFEX 确实会，然后当成"那天没行情"）。"""

    rel_path: str
    form: tuple[tuple[str, str], ...] = field(default=())
    """非空则用 POST 表单发出去。"""

    allow_failure: bool = False
    """`faults` 组专用：非 200 照存。别的组一律非 200 即失败退出。"""

    @property
    def is_post(self) -> bool:
        return bool(self.form)

    @property
    def key(self) -> str:
        """这份录播在清单里的身份。**必须**与 `Fetcher.post_form` 算出来的一致 ——
        两边各写一份规范化逻辑，回放就会静默地查不到而炸。
        """
        return canonical_post_url(self.url, dict(self.form)) if self.form else self.url


def _article_urls_from_feeds() -> list[str]:
    """从**已抓到的**新闻 fixture 里取出文章链接。

    不在这里直接请求 feed —— 那会让"加抓文章页"变成一次隐式的新闻重抓，
    从而产生新旧混排的窗口（旧的新闻在旧窗口里，新的在新窗口里）。
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


def replay_now() -> datetime:
    """行情要抓哪些日期，由**回放时钟**决定 —— 也就是清单里已有的锚点。

    没有清单时（首次抓取）才退回到系统时钟：那一次锚点会被写成"现在"，
    窗口自然对齐。
    """
    if MANIFEST_PATH.exists():
        payload = json.loads(MANIFEST_PATH.read_text("utf-8"))
        if payload.get("anchor_at"):
            return datetime.fromisoformat(str(payload["anchor_at"]))
    return datetime.now(UTC)


def _price_plan() -> list[PlannedSource]:
    """按登记表里记的**形状**规划请求。

    日期范围用 `candidate_dates` —— 就是适配器运行时用的同一个函数。不是巧合：
    这里少抓一天，回放就会在那一天查不到录播而炸（这是刻意的，见 ADR-0002）。
    """
    today = replay_now().astimezone(_SHANGHAI).date()
    planned: list[PlannedSource] = []
    for source in PRICE_SOURCES.values():
        if source.quote_format != "gfex_daily":
            planned.append(
                PlannedSource(
                    "prices",
                    source.quote_url,
                    f"prices/{source.commodity}-{source.symbol}-kline.json",
                )
            )
            continue
        for day in reversed(candidate_dates(today, DEFAULT_WINDOW_DAYS)):
            planned.append(
                PlannedSource(
                    "prices",
                    source.quote_url,
                    f"prices/{source.commodity}-{day.isoformat()}.json",
                    form=(
                        ("trade_date", day.strftime("%Y%m%d")),
                        ("trade_type", "0"),
                        ("variety", source.symbol),
                    ),
                )
            )
    return planned


def plan(group_filter: str | None) -> list[PlannedSource]:
    planned = [
        PlannedSource("news", source.url, f"news/{source.id}-feed.xml") for source in NEWS_SOURCES
    ]
    planned += [
        PlannedSource("articles", url, f"articles/{_slug(url)}.html")
        for url in _article_urls_from_feeds()
    ]
    planned += _price_plan()
    # `corroboration` 组不进生产链路，只用来**交叉核对**：碳酸锂的主力合约在
    # GFEX 官方接口与新浪的连续合约日线上必须给出同一个数。两边对不上，只可能是
    # 我们某一边读错了 —— 单看任何一边都发现不了。见 test_price_parsers.py。
    planned.append(
        PlannedSource("corroboration", SINA_KLINE_FOR_LITHIUM, "prices/lithium-lc0-kline.json")
    )
    planned.append(
        PlannedSource("faults", FAULT_SAMPLE_URL, "faults/upstream-503.html", allow_failure=True)
    )
    if group_filter:
        planned = [p for p in planned if p.group == group_filter]
    return planned


async def fetch_one(client: httpx.AsyncClient, source: PlannedSource) -> dict[str, object]:
    if source.is_post:
        response = await client.post(source.url, data=dict(source.form))
    else:
        response = await client.get(source.url)
    if response.status_code != 200 and not source.allow_failure:
        raise RuntimeError(f"{source.url} 返回 {response.status_code}，不写进 fixture")

    target = FIXTURE_DIR / source.rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)

    return {
        "url": source.key,
        "path": source.rel_path,
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "fetched_at": datetime.now(UTC).isoformat(),
        "content_type": response.headers.get("content-type", ""),
        "status": response.status_code,
        "bytes": len(response.content),
    }


def _prune_stale(existing: dict[str, dict[str, object]]) -> list[str]:
    """剔除"清单里的 sha256 与磁盘上的文件对不上"的条目，返回被剔除的 URL。

    这挡的是一类很容易发生的事故：改了 `rel_path` 或接口地址之后重抓，旧条目的
    URL 与新条目不同，于是**两份条目指向同一个文件**，其中一份记的是旧内容的
    校验和。它不会让抓取报错，只会让 `FixtureStore.raw()` 在**回放时**抛
    "校验和不符" —— 报错离原因很远。与其靠人记得手动删，不如让脚本自己收敛。

    只判 sha256，不判 URL：URL 是条目的身份，sha256 才是"这份文件是不是它记的那份"。
    """
    stale: list[str] = []
    for url, entry in existing.items():
        sha = str(entry.get("sha256") or "")
        if not sha:  # 二进制条目（PDF）没有 body 文件，见 ADR-0001
            continue
        body_path = FIXTURE_DIR / str(entry.get("path") or "")
        if not body_path.exists() or hashlib.sha256(body_path.read_bytes()).hexdigest() != sha:
            stale.append(url)
    for url in stale:
        del existing[url]
    return stale


def merge_manifest(
    new_entries: list[dict[str, object]], *, reset_anchor: bool = False
) -> dict[str, object]:
    """新抓的条目覆盖同名 URL 的旧条目，其余原样保留 —— 允许分组分次抓取。

    **锚点默认沿用**：补一个文章页就把整个回放的时间基准推到今天，已有 fixture 与
    已有 LLM 录播组成的"同一份输入"会产出不同日报（ADR-0002 的确定性就断了）。
    要换基准得显式 `--reset-anchor`，那是一次有意识的"重拍一张快照"。
    """
    existing: dict[str, dict[str, object]] = {}
    previous_anchor: str | None = None
    if MANIFEST_PATH.exists():
        payload = json.loads(MANIFEST_PATH.read_text("utf-8"))
        existing = {str(e["url"]): e for e in payload["entries"]}
        previous_anchor = payload.get("anchor_at")

    for entry in new_entries:
        existing[str(entry["url"])] = entry

    dropped = _prune_stale(existing)
    if dropped:
        sys.stdout.write(f"  ok 剔除失效条目：{dropped}\n")

    reuse_anchor = not reset_anchor and previous_anchor is not None
    anchor = previous_anchor if reuse_anchor else datetime.now(UTC).isoformat()

    payload = {
        "anchor_at": anchor,
        "entries": [existing[key] for key in sorted(existing)],
    }
    MANIFEST_PATH.write_text(
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
        for index, source in enumerate(planned):
            if index and args.throttle:
                await asyncio.sleep(args.throttle)
            entry = await fetch_one(client, source)
            status = entry["status"]
            flag = "" if status == 200 else f" [HTTP {status}]"
            sys.stdout.write(
                f"  ok{flag} {source.key} -> fixtures/{entry['path']} ({entry['bytes']} bytes)\n"
            )
            entries.append(entry)

    payload = merge_manifest(entries, reset_anchor=args.reset_anchor)
    sys.stdout.write(f"  ok 更新 fixtures/sources.json（anchor_at={payload['anchor_at']}）\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=["news", "articles", "prices", "corroboration", "faults"],
        default=None,
        help="只抓某一组源",
    )
    parser.add_argument(
        "--reset-anchor",
        action="store_true",
        help="把回放时钟重设为**现在**。默认沿用旧锚点 —— 随便补个 fixture 不该"
        "改变已有录播的时间基准（ADR-0002）。",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=2.0,
        help="两次请求之间的间隔秒数，默认 2（GFEX 接口约 20 次快速请求即限流）。",
    )
    parser.add_argument("--proxy", default="", help="如 http://127.0.0.1:7897")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
