"""`mineral-pdf-mcp` —— 题面点名的三个 server 之一。

**薄壳**（ADR-0008）：参数校验 → adapter → 信封。

一个刻意的例外值得说明：题面写的是抽 "NI 43-101" 储量，但题面举例的 Pilbara 走
JORC。JORC 2012 与 NI 43-101 **共用** Measured / Indicated / Inferred 这套分类词，
所以"体系"只是一个标注字段，解析路径是同一条（PRD §6.1 注）。

第二条纪律：返回的表是**解析器的输出**。在有人对着 PDF 核过之前，它说明的是"这份
报告第 N 页上印着这些数字、我们这样读它"，**不说明这些数字对**（PRD §12 的
ground truth 纪律）。`fixtures/resources/*.json` 里每份冻结记录都带一个
`human_verified`，人工核对之前它必须是 `false`。

这个字段目前**没有**进返回值 —— 信封上没有放它的地方，而"为了记一件事就往正式契约
里加一个字段"是要付代价的。所以缺口是**明摆着的**：产物上的储量数字眼下不携带
"是否已核对"这一位。记在工单 05 的收尾说明里，由人决定要不要提到产物上。
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
