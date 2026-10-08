"""配置层的断言：模式开关的默认值与 `--live` 的语义。

这里刻意不测"读环境变量的实现细节"，只测**外部行为**：给定环境变量，产物配置是什么。
"""

from __future__ import annotations

import pytest

from mining_brief.config.settings import ConfigError, Settings


def test_settings_default_to_replay_on_both_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    """零配置冷启动必须是回放、且不需要任何密钥（PRD §10、工单 10 的验收前提）。

    key 也要删：`--record-llm` 那一轮会把它导出到 shell 里，而"零配置"说的**就是**
    shell 里什么都没有的那种情形 —— 让这条断言跟着当前 shell 变红变绿，它测的就不是
    代码的默认值了。
    """
    monkeypatch.delenv("MINING_DATA_MODE", raising=False)
    monkeypatch.delenv("MINING_LLM_MODE", raising=False)
    monkeypatch.delenv("MINING_LLM_API_KEY", raising=False)

    settings = Settings.from_env()

    assert (settings.data_mode, settings.llm_mode) == ("replay", "replay")
    assert settings.is_replay is True
    assert settings.llm_api_key == ""


def test_live_run_flips_both_switches_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--live` 是把数据层与 LLM 层都置 live 的语法糖（ADR-0009）。"""
    monkeypatch.delenv("MINING_DATA_MODE", raising=False)
    monkeypatch.delenv("MINING_LLM_MODE", raising=False)

    live = Settings.from_env().for_live_run()

    assert (live.data_mode, live.llm_mode) == ("live", "live")
    assert live.is_replay is False


def test_the_two_switches_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """分开关的全部理由：改 LLM 措辞时不该被迫把数据层切到真实抓取（ADR-0009）。"""
    monkeypatch.setenv("MINING_DATA_MODE", "replay")
    monkeypatch.setenv("MINING_LLM_MODE", "live")

    settings = Settings.from_env()

    assert (settings.data_mode, settings.llm_mode) == ("replay", "live")
    assert settings.is_replay is False


def test_unknown_mode_is_a_startup_error_not_a_silent_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """拼错的模式名不能静默退回 replay —— 那会让"这次到底联没联网"失去答案。"""
    monkeypatch.setenv("MINING_DATA_MODE", "replayy")

    with pytest.raises(ConfigError, match="MINING_DATA_MODE"):
        Settings.from_env()
