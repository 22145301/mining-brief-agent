#!/usr/bin/env python
"""冻结技术报告的资源量表：下载 PDF → 逐页抽文本 → 解析 → 存成 JSON（工单 05）。

    uv run python scripts/extract_resources.py                     # 全部登记的 PDF
    uv run python scripts/extract_resources.py --only pilgangoora-cet-2022
    uv run python scripts/extract_resources.py --proxy http://127.0.0.1:7897

三件必须说清楚的事：

1. **PDF 本身不入库**（ADR-0001）：二进制文件大、且受版权保护。入库的是**抽好的
   JSON**，另记 PDF 的 sha256 与字节数，让"这份 JSON 对应哪一次下载"可追溯。
   代价写在明处：默认（回放）路径覆盖的是"读冻结 JSON → `ResourceTable`"这一段，
   "真下载真解析"只在 `@pytest.mark.network` 用例里跑。

2. **产物里的 `human_verified` 一律写 `false`。** 这些数字是**解析器的输出**，
   不是事实。工单 05 的验收里有一条人工核对卡点：在这些数字被使用者对着 PDF 逐个
   核过之前，回放用例证明的是"解析器没有回归"，不是"数字对"。脚本**不会**替人
   把它翻成 `true` —— 那个字段只能由人在核对之后改。

3. **抽不到表不是错误。** 若某份报告里认不出表，脚本照常写出 JSON（`table: null`）
   并如实打印；只有"下载失败"才以非零码退出 —— 与 `fetch_fixtures.py` 同一条纪律：
   不留半份东西冒充完整。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mining_brief.config.reports import REPORT_SOURCES, ReportSource  # noqa: E402
from mining_brief.datasources.resources import (  # noqa: E402
    DEFAULT_RESOURCE_DIR,
    pages_from_pdf_bytes,
    parse_resource_table,
)

RESOURCE_DIR = ROOT / DEFAULT_RESOURCE_DIR
DEFAULT_UA = "mining-brief/0.1 (+contact@example.com)"


def _category_pages(pages: tuple[tuple[int, str], ...]) -> list[int]:
    """哪几页出现了法定类别词 —— 写进 JSON 供人核对时直接翻过去。"""
    words = ("measured", "indicated", "inferred", "proven", "probable")
    return [number for number, text in pages if any(w in text.lower() for w in words)]


async def extract_one(client: httpx.AsyncClient, source: ReportSource) -> dict[str, object]:
    response = await client.get(source.pdf_url)
    if response.status_code != 200:
        raise RuntimeError(f"{source.pdf_url} 返回 {response.status_code}，不写进 fixture")

    body = response.content
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"{source.pdf_url} 回来的不是 PDF（头部 {body[:8]!r}）")

    pages = pages_from_pdf_bytes(body)
    table = parse_resource_table(pages, source)

    marker_pages = {
        str(number): text for number, text in pages if source.header_marker.lower() in text.lower()
    }
    category_pages = _category_pages(pages)
    payload: dict[str, object] = {
        "pdf_url": source.pdf_url,
        "pdf_sha256": hashlib.sha256(body).hexdigest(),
        "pdf_bytes": len(body),
        "pdf_pages": len(pages),
        "category_pages": category_pages,
        #: 含表头标记的**那几页原文**。冻它们是为了让 `parse_resource_table` 能在
        #: 离线测试里被重跑并断言重现出 `table` —— 只冻结果的话，解析器一行都跑不到
        #: （见 `FrozenExtract.pages`）。整份 PDF 不入库，这几页是例外，通常一两页。
        "page_text": marker_pages,
        "project": source.project,
        "standard": str(source.standard),
        "parsed_at": datetime.now(UTC).isoformat(),
        #: 见模块 docstring 第 2 条 —— 脚本不替人翻这个字段。
        "human_verified": False,
        "human_verified_by": None,
        "human_verified_at": None,
        "table": table.model_dump(mode="json") if table else None,
    }
    if table is not None:
        payload["page_hint"] = source.page_hint
        payload["parsed_from_page"] = table.page_refs[-1].page

    target = RESOURCE_DIR / f"{source.slug}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


async def run(args: argparse.Namespace) -> int:
    selected = [
        source
        for source in REPORT_SOURCES.values()
        if args.only is None or source.slug == args.only
    ]
    if not selected:
        sys.stderr.write(f"没有匹配的报告（--only {args.only}）\n")
        return 2

    async with httpx.AsyncClient(
        timeout=args.timeout,
        follow_redirects=True,
        proxy=args.proxy or None,
        headers={"User-Agent": DEFAULT_UA, "Accept": "application/pdf,*/*"},
    ) as client:
        for source in selected:
            try:
                payload = await extract_one(client, source)
            except Exception as exc:
                sys.stderr.write(f"  !! {source.slug}: {type(exc).__name__}: {exc}\n")
                return 1
            page_text = payload.get("page_text")
            frozen_pages = len(page_text) if isinstance(page_text, dict) else 0
            category_pages = payload.get("category_pages")
            category_count = len(category_pages) if isinstance(category_pages, list) else 0
            table = payload.get("table")
            if not isinstance(table, dict):
                sys.stdout.write(
                    f"  ok {source.slug} -> fixtures/resources/{source.slug}.json"
                    f"（{payload['pdf_bytes']} 字节 / {payload['pdf_pages']} 页）"
                    " —— **未抽到表**，已如实记录\n"
                )
                continue
            rows = table["rows"]
            sys.stdout.write(
                f"  ok {source.slug} -> fixtures/resources/{source.slug}.json"
                f"（{payload['pdf_bytes']} 字节 / {payload['pdf_pages']} 页）"
                f" 抽到 {len(rows)} 行，来自第 {payload['parsed_from_page']} 页；"
                f"共 {category_count} 页含类别词；"
                f"冻结 {frozen_pages} 页原文供离线重跑\n"
            )
            for row in rows:
                sys.stdout.write(
                    f"       {row['category']:<10} 吨位 {row['tonnage_mt']} Mt"
                    f"  品位 {row['grade']} {row['grade_unit']}"
                    f"  含金属 {row['contained']}\n"
                )
    sys.stdout.write("\n记住：以上数字是**解析器的输出**，尚未人工核对（human_verified=false）。\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="只抽某一份（按 slug）")
    parser.add_argument("--proxy", default="", help="如 http://127.0.0.1:7897")
    parser.add_argument("--timeout", type=float, default=120.0)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
