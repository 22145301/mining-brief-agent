"""CLI 参数面的断言。运行入口 `brief` 由 01 号工单补上。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from mining_brief import __version__
from mining_brief.cli import app

runner = CliRunner()

#: 题面原句。与 `tests/conftest.py` 的 `canonical_request` 是同一句 —— 这里是子进程，
#: 拿不到夹具，所以只能各写一份；两处不同的话，这条用例证的就不是题面那句话了。
CANONICAL_REQUEST = "给我生成一份关于 Pilbara 锂矿的今日简报"


def test_help_exits_zero_and_describes_the_tool() -> None:
    """陌生人 clone 后第一条命令就得有反馈。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "矿权日报" in result.stdout


def test_version_flag_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"mining-brief {__version__}"


def test_cold_start_needs_no_environment_variables_at_all(tmp_path: Path) -> None:
    """**零配置冷启动**：不设任何 `MINING_*`，照样出报（工单 10 的验收）。

    刻意走**子进程**、刻意把环境变量表清空 —— 进程内构造 `Settings` 会把当前 shell
    的环境变量一并继承进来，于是"没有配置"就从被断言的对象变成了一个假设。
    工作目录也刻意不是仓库根：宿主/陌生人从哪儿跑都要成立（见 `config/paths.py`）。

    不联网这一半由回放层保证（`FixtureFetcher` 里根本没有网络那条路），
    可执行的证据在 `tests/test_replay_discipline.py`：把 base_url 指到一个必然
    连不上的地址，整条链路照样绿。
    """
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
        if key in os.environ  # Windows 上 python 缺 SYSTEMROOT 起不来；均为非 MINING_* 变量
    }

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mining_brief.cli",
            "brief",
            CANONICAL_REQUEST,
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        # 拿字节再自己解码：子进程的环境变量表被清空了，Windows 上它按控制台代码页
        # 写 stderr（日志里有中文），按 utf-8 解会炸在解码而不是炸在断言上。
        env=env,
        cwd=tmp_path,
        timeout=180,
    )
    stderr = proc.stderr.decode("utf-8", "replace")
    stdout = proc.stdout.decode("utf-8", "replace")

    assert proc.returncode == 0, stderr
    # PRD §5.3：stdout 上只有产物路径，没有全文，没有别的。
    assert stdout.strip().startswith(str(tmp_path)), stdout
    produced = Path(stdout.strip())
    assert produced.is_file()

    text = produced.read_text("utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings[-1] == "## 来源清单", headings
    for title in ("矿权动态", "新闻摘要", "储量数据", "价格走势", "风险提示", "数据完整性"):
        assert any(title in heading for heading in headings), f"产物少了「{title}」这一节"
