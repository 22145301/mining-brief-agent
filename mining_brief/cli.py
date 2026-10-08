"""命令行入口。

运行入口 `brief` 由 01 号工单落在本文件上 —— 本票（00）只交付参数面外壳：
`--help` 与 `--version` 可用，保证陌生人 clone 后第一条命令就有反馈。

产物路径的落法见 PRD §5.3：日报写进文件，**只把路径打到 stdout**，不吐全文 ——
否则产物就没法被测试断言了。届时用显式的 `sys.stdout.write` 而不是 `print`
（ruff 的 T20 规则在全仓库禁裸 print，见 pyproject.toml）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from mining_brief import __version__
from mining_brief.config.logging import configure_logging
from mining_brief.config.settings import ConfigError, Settings

app = typer.Typer(
    name="mining-brief",
    help=(
        "矿权日报 Agent —— 输入一句自然语言，输出一份每个事实都能回溯到原始来源的 Markdown 日报。"
    ),
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        sys.stdout.write(f"mining-brief {__version__}\n")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="打印版本号后退出。",
    ),
) -> None:
    """全局选项。"""


@app.command()
def brief(
    request: str = typer.Argument(
        ..., help="一句自然语言，例如「给我生成一份关于 Pilbara 锂矿的今日简报」。"
    ),
    live: bool = typer.Option(
        False, "--live", help="把数据层与 LLM 层都切到实时（需要密钥与网络）。默认全回放。"
    ),
    out: Path | None = typer.Option(
        None, "--out", help="日报落盘目录。默认取 MINING_OUTPUT_DIR，再默认 briefs/。"
    ),
    fixture_root: Path = typer.Option(
        Path("fixtures"), "--fixture-root", help="回放用的录播根目录。"
    ),
) -> None:
    """生成一份矿权日报，**只把产物路径打到 stdout**（PRD §5.3）。"""
    configure_logging()

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        sys.stderr.write(f"配置错误：{exc}\n")
        raise typer.Exit(code=2) from exc

    if live:
        settings = settings.for_live_run()
    if out is not None:
        from dataclasses import replace

        settings = replace(settings, output_dir=str(out))

    from mining_brief.agent.pipeline import run_brief

    try:
        result = asyncio.run(run_brief(request, settings=settings, fixture_root=fixture_root))
    except Exception as exc:
        sys.stderr.write(f"生成失败：{type(exc).__name__}: {exc}\n")
        raise typer.Exit(code=1) from exc

    # 刻意不吐全文：产物落盘、路径打到 stdout，日报才能被测试逐字断言。
    sys.stdout.write(f"{result.output_path}\n")
    if result.refusal is not None:
        raise typer.Exit(code=3)  # 拒答是**成功执行**，但退出码要与"出报"区分开


def main() -> None:
    app()


if __name__ == "__main__":
    main()
