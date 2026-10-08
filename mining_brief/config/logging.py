"""结构化日志。全仓库禁裸 `print`（由 ruff 的 T20 规则挡住，不靠自觉）。

日志一律走 **stderr** —— 这一点对 MCP server 尤其要紧：stdio 传输下 stdout
只归协议所有，日志写进去会污染协议线（工单 09 的验收项）。
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """幂等 —— 多次调用只生效一次，测试里反复建 app 不会叠加 handler。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    resolved = (level or os.environ.get("MINING_LOG_LEVEL") or "INFO").upper()

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=resolved)
    # 第三方库的默认 INFO 太吵（httpx 每次请求、mcp 每次协议往返都打一条）。
    # 只有把 MINING_LOG_LEVEL 调到 DEBUG 时才放开 —— 排查问题时才需要它们。
    if resolved != "DEBUG":
        for noisy in ("mcp", "httpx", "httpcore", "openai"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.KeyValueRenderer(key_order=["event"], sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(resolved, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str, **initial: Any) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name).bind(**initial)  # type: ignore[no-any-return]
