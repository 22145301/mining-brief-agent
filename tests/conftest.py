"""测试夹具。

两条纪律：

- **默认套件必须完全离线、完全确定。** 数据读 `fixtures/`，LLM 读 `fixtures/llm/`，
  时钟取 fixture 锚点。一个测试如果依赖系统时钟或真实网络，它就一定会在某个早上
  变红，而那种红是噪声不是信号。
- **测试用的 `Settings` 显式构造**，不走 `from_env()` —— 否则开发机上的
  `MINING_*` 环境变量会悄悄改变测试行为，套件就不再是"给定输入必然给定输出"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mining_brief.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "fixtures"
LLM_FIXTURE_ROOT = FIXTURE_ROOT / "llm"

#: 题面原句（工单 01 的第一条验收）。
CANONICAL_REQUEST = "给我生成一份关于 Pilbara 锂矿的今日简报"


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture(scope="session")
def llm_fixture_root() -> Path:
    return LLM_FIXTURE_ROOT


@pytest.fixture(scope="session")
def canonical_request() -> str:
    """题面原句（工单 01 的第一条验收）。"""
    return CANONICAL_REQUEST


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """回放模式、退避为 0 —— 与生产同构，但没有等待，也没有网络。"""
    return Settings(
        data_mode="replay",
        llm_mode="replay",
        llm_api_key="",
        llm_base_url="http://127.0.0.1:1",  # 回放永远不该碰它；填个必然连不上的地址
        llm_model="test-model",
        http_proxy="",
        user_agent="mining-brief-test/0.1 (+test@example.com)",
        http_timeout_s=5.0,
        browser_timeout_s=5.0,
        browser_channel="",
        output_dir=str(tmp_path / "briefs"),
        fetch_attempts=3,
        retry_base_delay_s=0.0,
    )
