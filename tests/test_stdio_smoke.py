"""stdio 冒烟：**真起子进程**、走 stdio 传输，把每个 server 的每个工具都调通。

ADR-0001 刻意接受了一个取舍：默认路径走**进程内**协议连接，换来的是测试不必管
进程启停、清理和端口。代价是不覆盖 stdio 传输本身 —— 进程边界、启动方式、cwd、
stdout 干不干净、协议的编解码。这一票补的就是那一刀，所以这里的每一条都必须在
真子进程里跑：

- **cwd 刻意不是仓库根。** 宿主（Claude Desktop / Cursor）拉起 server 时工作目录
  是宿主的，不是仓库的；"换个目录起不来"是这条路上最容易翻的车（见 config/paths.py）。
- **stdout 只走协议。** 日志走 stderr 不是风格问题：stdio 传输上 stdout 就是协议线，
  一行日志混进去，客户端看到的就是一段解不开的 JSON。
- **outputSchema 真的在 wire 上。** 工具返回类型注解有没有变成宿主看得见的结构化
  契约，只有连上去 list 一次才知道。

标了 `stdio`，默认套件排除（pyproject 的 addopts），因为每条都要起真进程。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

from mining_brief.config.paths import REPO_ROOT
from mining_brief.config.reports import PILBARA_CET

pytestmark = pytest.mark.stdio

NEWS_MODULE = "mining_brief.servers.news_server"
PRICE_MODULE = "mining_brief.servers.price_server"
PDF_MODULE = "mining_brief.servers.mineral_pdf_server"

#: 每个 server 该有哪些工具 —— 与 `mcp-config.json` 里挂的是同一批。
EXPECTED_TOOLS = {
    NEWS_MODULE: {"search", "fetch_article"},
    PRICE_MODULE: {"get_price", "get_trend"},
    PDF_MODULE: {"extract_resources"},
}

#: 与 `tests/test_news_tool.py` 的检索式一致 —— 工具级用例与冒烟用例必须说同一件事。
CANONICAL_QUERY = "Pilgangoora Pilbara Minerals lithium"


def _params(module: str) -> StdioServerParameters:
    """按宿主的做法起一个 server：`python -m <module>`，cwd 是**别人的**目录。"""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=tempfile.gettempdir(),
        env={
            **os.environ,
            # 显式钉住回放：这一票验的是传输，不该顺带去够网络。
            "MINING_DATA_MODE": "replay",
            "MINING_LLM_MODE": "replay",
        },
    )


@asynccontextmanager
async def _session(module: str) -> AsyncIterator[ClientSession]:
    async with (
        stdio_client(_params(module)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _payload(result: CallToolResult) -> dict[str, Any]:
    """取结构化返回值 —— 宿主里的模型看到的也是它，不是那段给人读的文本。"""
    assert result.isError is False, result.content
    assert result.structuredContent is not None, (
        "没有 structuredContent 说明返回类型注解没变成 outputSchema"
    )
    return result.structuredContent


@pytest.mark.parametrize("module", sorted(EXPECTED_TOOLS))
async def test_every_server_comes_up_and_declares_a_schema_for_every_tool(module: str) -> None:
    async with _session(module) as session:
        tools = await session.list_tools()

    names = {tool.name for tool in tools.tools}
    assert names == EXPECTED_TOOLS[module], f"{module} 的工具集变了：{sorted(names)}"
    for tool in tools.tools:
        assert tool.description and len(tool.description) > 80, (
            f"{module}.{tool.name} 的描述太短 —— 宿主里的模型就是靠它决定要不要用的"
        )
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema is not None, f"{module}.{tool.name} 没有 outputSchema"
        assert tool.outputSchema["type"] == "object"


async def test_price_tools_answer_over_stdio() -> None:
    async with _session(PRICE_MODULE) as session:
        one = _payload(
            await session.call_tool("get_price", {"commodity": "lithium", "date": "2026-10-08"})
        )
        trend = _payload(await session.call_tool("get_trend", {"commodity": "lithium", "days": 7}))

    assert one["status"] == "ok"
    assert one["commodity"] == "lithium"
    assert one["point"]["as_of"] == one["requested_date"], "同一天的数据不该被标成回退"
    assert one["point"]["value"] == 117300.0
    assert trend["status"] == "ok"
    assert trend["points"], "7 天窗口里至少该有一天"
    assert [p["as_of"] for p in trend["points"]] == sorted(p["as_of"] for p in trend["points"])


async def test_news_tools_answer_over_stdio() -> None:
    async with _session(NEWS_MODULE) as session:
        search = _payload(await session.call_tool("search", {"query": CANONICAL_QUERY, "days": 30}))
        urls = [item["url"] for item in search["items"]]
        assert any("australianmining.com.au" in url for url in urls), urls
        article = _payload(
            await session.call_tool(
                "fetch_article", {"url": next(u for u in urls if "australianmining" in u)}
            )
        )

    assert search["status"] == "ok"
    assert search["items"], "题面原句对应的用例必须真的有内容"
    assert all(item["category"] for item in search["items"])
    assert article["status"] == "ok"
    assert len(article["article"]["text"]) > 500, "正文只拿到标题栏说明容器没定位对"


async def test_the_pdf_tool_answers_over_stdio() -> None:
    async with _session(PDF_MODULE) as session:
        extract = _payload(
            await session.call_tool("extract_resources", {"pdf_url": PILBARA_CET.pdf_url})
        )

    assert extract["status"] == "ok"
    table = extract["table"]
    assert table["project"] == "Pilgangoora"
    assert table["standard"] == "JORC"
    assert [row["category"] for row in table["rows"]] == ["Measured", "Indicated", "Inferred"]


def test_stdout_carries_protocol_lines_and_nothing_else() -> None:
    """手写一次握手，逐行检查 stdout。

    为什么不用 `stdio_client` 做这件事：它把协议帧吃掉、只把解析后的对象给你 ——
    多出来的那行日志会被它顺手丢掉，于是"stdout 是不是干净的"变成了**看不见**的事。
    这里要看的正是原始字节流。

    日志本身不是不该有：`get_price` 一次调用会打若干条 JSON 日志，它们必须出现在
    **stderr** 上（下面断言了）。
    """
    request_lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-smoke", "version": "0.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_price",
                "arguments": {"commodity": "lithium", "date": "2026-10-08"},
            },
        },
    ]
    stdin = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in request_lines)

    proc = subprocess.run(
        [sys.executable, "-m", PRICE_MODULE],
        input=stdin.encode("utf-8"),
        capture_output=True,
        cwd=tempfile.gettempdir(),
        env={**os.environ, "MINING_DATA_MODE": "replay", "MINING_LLM_MODE": "replay"},
        timeout=90,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    stdout_lines = [line for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    assert len(stdout_lines) >= 2, stdout_lines

    replies: dict[Any, dict[str, Any]] = {}
    for line in stdout_lines:
        frame = json.loads(line)  # 解析不了 = stdout 被日志污染了
        assert frame.get("jsonrpc") == "2.0", f"这行不是协议帧：{line[:200]}"
        if "id" in frame:
            replies[frame["id"]] = frame

    assert replies[1]["result"]["serverInfo"]["name"] == "lme-price-mcp"
    call_result = replies[2]["result"]
    assert call_result["isError"] is False
    assert call_result["structuredContent"]["point"]["value"] == 117300.0


def test_logs_go_to_stderr_and_never_to_stdout() -> None:
    """日志的落点只有一处：stderr。

    这条不是在测某个 server，而是在测**那个让上面几条成立的机制** —— 日志配置把
    输出流钉在 stderr。三个 server 的 `main()` 都先调 `configure_logging()` 再
    `mcp.run()`，所以 stdio 传输下不存在"某条日志顺手写进协议线"的窗口。
    """
    code = (
        "from mining_brief.config.logging import get_logger\n"
        "get_logger('stdio-smoke').info('probe.marker')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        cwd=tempfile.gettempdir(),
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout == b"", f"stdout 上出现了非协议内容：{proc.stdout!r}"
    assert "probe.marker" in proc.stderr.decode("utf-8", "replace")


def test_the_fixture_root_does_not_depend_on_the_working_directory() -> None:
    """**cwd 不是我们的。** 上面几条能跑通，靠的是默认录播根按**安装位置**推。

    这条把它单独钉出来：换个工作目录，`fixture_root()` 仍然指向仓库里那一份。
    不然宿主拉起 server 时的表现就会变成"能列工具、一取数据就说找不到清单"。
    """
    code = (
        "from mining_brief.config.paths import REPO_ROOT, fixture_root\n"
        "print(fixture_root())\n"
        "print(REPO_ROOT)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        cwd=tempfile.gettempdir(),
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    resolved, root = proc.stdout.splitlines()[:2]
    assert Path(resolved) == REPO_ROOT / "fixtures"
    assert Path(root) == REPO_ROOT
    assert (Path(resolved) / "sources.json").is_file()
    assert Path(tempfile.gettempdir()).resolve() != REPO_ROOT, "这一条的前提是 cwd 真的不是仓库"
