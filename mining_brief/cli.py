"""命令行入口。

运行入口 `brief` 由 01 号工单落在本文件上 —— 本票（00）只交付参数面外壳：
`--help` 与 `--version` 可用，保证陌生人 clone 后第一条命令就有反馈。

产物路径的落法见 PRD §5.3：日报写进文件，**只把路径打到 stdout**，不吐全文 ——
否则产物就没法被测试断言了。届时用显式的 `sys.stdout.write` 而不是 `print`
（ruff 的 T20 规则在全仓库禁裸 print，见 pyproject.toml）。
"""

from __future__ import annotations

import sys

import typer

from mining_brief import __version__

app = typer.Typer(
    name="mining-brief",
    help=(
        "矿权日报 Agent —— 输入一句自然语言，"
        "输出一份每个事实都能回溯到原始来源的 Markdown 日报。"
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
