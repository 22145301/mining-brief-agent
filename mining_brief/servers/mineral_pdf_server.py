"""`mineral-pdf-mcp` —— 题面点名的三个 server 之一。

**薄壳**（ADR-0008）：参数校验 → adapter → 信封。

一个刻意的例外值得说明：题面写的是抽 "NI 43-101" 储量，但题面举例的 Pilbara 走
JORC。JORC 2012 与 NI 43-101 **共用** Measured / Indicated / Inferred 这套分类词，
所以"体系"只是一个标注字段，解析路径是同一条（PRD §6.1 注）。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mining_brief.contracts import ResourceExtract
from mining_brief.servers.runtime import Runtime, default_runtime

mcp = FastMCP("mineral-pdf-mcp")

_runtime_override: Runtime | None = None


def _runtime() -> Runtime:
    return _runtime_override or default_runtime()


def set_runtime(runtime: Runtime | None) -> None:
    """给测试用的注入点。生产路径上没人调用它。"""
    global _runtime_override
    _runtime_override = runtime


@mcp.tool()
async def extract_resources(pdf_url: str) -> ResourceExtract:
    """从一份技术报告 PDF 里抽出资源量 / 储量表。

    **何时用**：需要某个项目的资源量或储量数字时。URL 从矿权档案里拿。

    **参数**：`pdf_url` 是技术报告 PDF 的直链。

    **返回**：`ResourceExtract` 信封。`table.rows` 每行标 `category`
    （`Measured` / `Indicated` / `Inferred` 是**资源量**，`Proven` / `Probable` 是**储量** ——
    两类不同，行上的 `kind` 字段把它们分开）；`table.standard` 标明报告体系
    （`NI 43-101` 还是 `JORC`）；`table.page_refs` 给出每个数字来自 PDF 第几页。
    """
    runtime = _runtime()
    return await runtime.resources().extract_resources(pdf_url=pdf_url, now=runtime.now())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
