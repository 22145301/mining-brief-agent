"""CLI 参数面的断言。运行入口 `brief` 由 01 号工单补上。"""

from __future__ import annotations

from typer.testing import CliRunner

from mining_brief import __version__
from mining_brief.cli import app

runner = CliRunner()


def test_help_exits_zero_and_describes_the_tool() -> None:
    """陌生人 clone 后第一条命令就得有反馈。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "矿权日报" in result.stdout


def test_version_flag_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"mining-brief {__version__}"
