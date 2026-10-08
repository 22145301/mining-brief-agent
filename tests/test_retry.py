"""fetch 节点的有界重试（工单 01 验收：各自独立超时与重试）。

重试的是**工具链的瞬时故障**，不是数据源故障 —— 后者已经被吸收进降级信封，
是"一次成功的工具调用"，重试它只是白等。
"""

from __future__ import annotations

import pytest

from mining_brief.agent.retry import retry_params, with_retry
from mining_brief.errors import ReplayMiss


async def test_a_transient_failure_is_absorbed_and_the_result_is_returned() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("握手失败")
        return "ok"

    result = await with_retry(flaky, attempts=3, base_delay_s=0.0, label="t")

    assert result == "ok"
    assert calls["n"] == 3


async def test_it_gives_up_after_the_configured_attempts_and_raises_the_last_error() -> None:
    calls = {"n": 0}

    async def always_broken() -> str:
        calls["n"] += 1
        raise RuntimeError(f"第 {calls['n']} 次也失败了")

    with pytest.raises(RuntimeError, match="第 3 次也失败了"):
        await with_retry(always_broken, attempts=3, base_delay_s=0.0, label="t")

    assert calls["n"] == 3, "尝试次数必须**恰好**是配置的次数，不多不少"


async def test_every_retry_is_reported_with_its_delay() -> None:
    """退避要能被看见 —— 否则线上只会看到"慢"，看不到"重试了"。"""
    seen: list[tuple[int, int, float]] = []

    async def flaky() -> str:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await with_retry(
            flaky,
            attempts=3,
            base_delay_s=0.5,
            label="t",
            on_retry=lambda attempt, attempts, delay, _exc: seen.append((attempt, attempts, delay)),
        )

    assert seen == [(1, 3, 0.5), (2, 3, 1.0)]


async def test_a_replay_miss_is_not_retried() -> None:
    """录播缺失重试一万次也还是缺失 —— 立刻上抛，不浪费退避的时间。"""
    calls = {"n": 0}

    async def missing() -> str:
        calls["n"] += 1
        raise ReplayMiss("fixtures 里没有这个 URL")

    with pytest.raises(ReplayMiss):
        await with_retry(missing, attempts=3, base_delay_s=0.0, label="t")

    assert calls["n"] == 1


async def test_a_successful_first_attempt_never_waits() -> None:
    async def fine() -> str:
        return "ok"

    assert await with_retry(fine, attempts=3, base_delay_s=99.0, label="t") == "ok"


def test_attempts_must_be_at_least_one() -> None:
    import asyncio

    with pytest.raises(ValueError, match="至少为 1"):

        async def _nop() -> str:
            return "ok"

        asyncio.run(with_retry(_nop, attempts=0, base_delay_s=0.0, label="t"))


def test_retry_params_falls_back_conservatively_without_settings() -> None:
    """没有 settings 时也要有确定的行为，不能抛 KeyError。"""
    assert retry_params({}) == (3, 0.0)
