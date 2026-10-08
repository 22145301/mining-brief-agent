"""测试夹具。

两条纪律：

- **默认套件必须完全离线、完全确定。** 数据读 `fixtures/`，LLM 读 `fixtures/llm/`，
  时钟取 fixture 锚点。一个测试如果依赖系统时钟或真实网络，它就一定会在某个早上
  变红，而那种红是噪声不是信号。
- **测试用的 `Settings` 显式构造**，不走 `from_env()` —— 否则开发机上的
  `MINING_*` 环境变量会悄悄改变测试行为，套件就不再是"给定输入必然给定输出"。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from mining_brief.agent.llm import LLMRecorder, set_default_recorder
from mining_brief.config.settings import Settings
from mining_brief.datasources.fixtures import FixtureStore

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "fixtures"
LLM_FIXTURE_ROOT = FIXTURE_ROOT / "llm"

#: 题面原句（工单 01 的第一条验收）。
CANONICAL_REQUEST = "给我生成一份关于 Pilbara 锂矿的今日简报"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record-llm",
        action="store_true",
        default=False,
        help=(
            "重录模式：把测试碰到的**每一个**模型输入真实调用一次，结果并入 fixtures/llm/。"
            "需要 MINING_LLM_API_KEY。数据层仍是回放 —— 重录不该顺带把数据源切到真实抓取。"
        ),
    )


@pytest.fixture(scope="session", autouse=True)
def llm_recording(pytestconfig: pytest.Config, llm_fixture_root: Path) -> Iterator[None]:
    """重录模式的开关（默认关）。

    为什么重录要**由测试来跑**，而不是从 `scripts/record_llm.py` 的样例请求复现：
    回放的 key 落在输入数据上，而测试喂进去的数据是几十条用例各造各的（有的还塞了
    自建的新闻）。让测试自己在 live 模式下跑一遍，录下来的集合才**恰好等于**回放
    需要的集合 —— 少一条，回放就会以 `LLMReplayMiss` 当场点名。
    """
    if not pytestconfig.getoption("--record-llm"):
        yield
        return
    if not os.environ.get("MINING_LLM_API_KEY"):
        raise pytest.UsageError("--record-llm 需要 MINING_LLM_API_KEY（真实调用一次）")
    recorder = LLMRecorder(llm_fixture_root)
    set_default_recorder(recorder)
    try:
        yield
    finally:
        set_default_recorder(None)
        recorder.flush()


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


@pytest.fixture(scope="session")
def fault_url(fixture_root: Path) -> str:
    """`faults/` 组录下来的那条**真实** 503 的地址（A7 的样本）。

    地址从**清单里**取，不在测试里再抄一遍 —— 两处各写一份就会漂。按**状态**挑而不是
    按位置挑：`faults/` 下现在不止一个条目，靠顺序取是撞运气。
    """
    entries = [
        entry
        for entry in FixtureStore(fixture_root).manifest.entries
        if entry.path.startswith("faults/")
    ]
    spiking = [entry for entry in entries if entry.status == 503]
    assert len(spiking) == 1, f"faults 组里的 503 样本不是恰好一条：{entries}"
    return spiking[0].url


@pytest.fixture
def settings(tmp_path: Path, pytestconfig: pytest.Config) -> Settings:
    """回放模式、退避为 0 —— 与生产同构，但没有等待，也没有网络。

    唯一的例外是 `--record-llm`：那一轮**只**把 LLM 层切到真实调用（数据层照旧
    回放），录到的响应并入 `fixtures/llm/`。两个开关分开，重录导读不会顺带把
    铜价源切到真实抓取 —— 那要无头浏览器、要过 Cloudflare。
    """
    recording = bool(pytestconfig.getoption("--record-llm"))
    return Settings(
        data_mode="replay",
        llm_mode="live" if recording else "replay",
        llm_api_key=os.environ.get("MINING_LLM_API_KEY", "") if recording else "",
        llm_base_url=(
            os.environ.get("MINING_LLM_BASE_URL", "https://api.deepseek.com")
            if recording
            else "http://127.0.0.1:1"  # 回放永远不该碰它；填个必然连不上的地址
        ),
        llm_model=(
            os.environ.get("MINING_LLM_MODEL", "deepseek-chat") if recording else "test-model"
        ),
        http_proxy="",
        user_agent="mining-brief-test/0.1 (+test@example.com)",
        http_timeout_s=5.0,
        browser_timeout_s=5.0,
        browser_channel="",
        output_dir=str(tmp_path / "briefs"),
        fetch_attempts=3,
        retry_base_delay_s=0.0,
    )
