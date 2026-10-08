"""回放纪律：**缺录播就报错，不回退真实调用、不静默降级**（ADR-0002 / ADR-0009）。

这是全项目最容易被"顺手改好"破坏的一条。它换来的是：CI 上的绿是真的绿，
"默认路径没碰网络"是个可断言的事实，而不是一句设计意图。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mining_brief.agent.llm import LLMReplayMiss, ReplayLLMClient, replay_key
from mining_brief.agent.pipeline import run_brief
from mining_brief.config.settings import Settings
from mining_brief.errors import REPLAY_MISS_SENTINEL, ReplayMiss


async def test_an_unrecorded_node_input_raises_instead_of_falling_back(
    llm_fixture_root: Path,
) -> None:
    client = ReplayLLMClient(llm_fixture_root)

    with pytest.raises(LLMReplayMiss) as excinfo:
        await client.complete(
            node="parse_intent",
            key_input={"request_text": "一句从来没录过的话"},
            system="S",
            user="U",
        )

    message = str(excinfo.value)
    assert REPLAY_MISS_SENTINEL in message
    assert "record_llm.py" in message  # 告诉人怎么修，而不只是说"失败了"
    assert replay_key("parse_intent", {"request_text": "一句从来没录过的话"}) in message


async def test_a_node_with_no_recording_file_at_all_also_raises(
    llm_fixture_root: Path,
) -> None:
    client = ReplayLLMClient(llm_fixture_root)

    with pytest.raises(LLMReplayMiss, match="narrate"):
        await client.complete(node="narrate", key_input={"x": 1}, system="S", user="U")


def test_llm_replay_miss_is_not_an_llm_error() -> None:
    """**这条断言是个设计决策，不是实现细节。**

    节点捕获 `LLMError` 会降级为缺省槽位 —— 对"模型这次没答上来"是对的。
    对"我们忘了重录"是错的：那会产出一份**按缺省值出的**日报，而它看起来和
    一次正常执行一模一样。所以 `LLMReplayMiss` 不能是 `LLMError`的子类。
    """
    from mining_brief.agent.llm import LLMError

    assert issubclass(LLMReplayMiss, ReplayMiss)
    assert not issubclass(LLMReplayMiss, LLMError)


async def test_a_replay_miss_kills_the_whole_run_instead_of_producing_a_degraded_brief(
    settings: Settings, fixture_root: Path
) -> None:
    """端到端的后果：宁可不产出，也不产出一份假的。

    注意这里 `settings.llm_mode` 是 replay 而录播里没有这句话 —— 这正是"有人改了
    prompt 或加了个新用例却忘了重录"的样子。**不许**出现一份写着"数据缺失"的日报。
    """
    with pytest.raises(LLMReplayMiss):
        await run_brief(
            "这句话从来没有被录过，所以解析不出意图",
            settings=settings,
            fixture_root=fixture_root,
        )


async def test_replay_never_touches_the_network_even_when_configured_to(
    settings: Settings, fixture_root: Path, canonical_request: str
) -> None:
    """把一个必然连不上的 base_url 配上，跑完整条链路仍然全绿 ——
    这就是"默认路径不碰网络"的可执行证据，而不是一句声明。
    """
    from dataclasses import replace

    hostile = replace(settings, llm_base_url="http://127.0.0.1:1", http_proxy="http://127.0.0.1:1")

    result = await run_brief(canonical_request, settings=hostile, fixture_root=fixture_root)

    assert result.refusal is None
    assert len(result.sections) == 6
