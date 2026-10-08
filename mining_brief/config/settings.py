"""运行配置：只放**非密钥**配置，密钥一律走环境变量（CLAUDE.md 硬性要求）。

两个模式开关分开是刻意的 —— 见 `docs/adr/0009-llm-replay-keyed-by-input-hash.md`：
调一句导读的措辞不该被迫把铜价源切到真实抓取（那要无头浏览器、要过 Cloudflare）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, get_args

Mode = Literal["replay", "live"]

_MODES: frozenset[str] = frozenset(get_args(Mode))

# 默认值即"起点值"（ADR-0006）：HTTP 类 15s，浏览器类 45s（冷启动 + 页面导航 +
# 过 Cloudflare 挑战页）。首次真实抓取跑通后按实测校准。
DEFAULT_HTTP_TIMEOUT_S = 15.0
DEFAULT_BROWSER_TIMEOUT_S = 45.0

# 三次尝试（首次 + 两次重试）与 0.5s 起的指数退避。够覆盖"进程冷启动失败"这类
# 瞬时故障，又不至于让一次真的源故障拖到用户等不下去。
DEFAULT_FETCH_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_S = 0.5


class ConfigError(RuntimeError):
    """配置本身不合法 —— 启动期就该炸，不要拖到运行中途。"""


def _read_mode(name: str) -> Mode:
    raw = os.environ.get(name, "replay").strip().lower()
    if raw not in _MODES:
        raise ConfigError(f"{name} 只能是 {' 或 '.join(sorted(_MODES))}，收到 {raw!r}")
    return raw  # type: ignore[return-value]


def _read_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 需要是数字，收到 {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须为正数，收到 {value}")
    return value


def _read_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 需要是整数，收到 {raw!r}") from exc
    if value < 1:
        raise ConfigError(f"{name} 至少为 1，收到 {value}")
    return value


def _read_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    """进程的完整配置快照。构造一次、注入下去，不要在各处重复读 env。"""

    data_mode: Mode
    llm_mode: Mode
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    http_proxy: str
    user_agent: str
    http_timeout_s: float
    browser_timeout_s: float
    browser_channel: str
    """浏览器走哪个 channel：空 = playwright 自带的 chromium（要 `playwright install
    chromium`）；`chrome` = 用系统装的 Chrome（省一次下载）。它进配置是因为
    "这台机器上能起来的浏览器是哪个"是**环境事实**，不该写死在抓取代码里。"""

    output_dir: str
    """日报落盘的目录（PRD §5.3）。默认 `briefs/`，可用 `MINING_OUTPUT_DIR` 覆盖。
    放配置里而不是写死，是为了让测试能写进 `tmp_path` 而不是污染工作区。"""

    fetch_attempts: int
    """每个 fetch 节点的**独立**尝试次数（工单 01 验收：各自独立超时与重试）。"""

    retry_base_delay_s: float
    """重试退避的基数，第 n 次重试等 `base * 2^(n-1)` 秒。测试里置 0 以免拖慢套件。"""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_mode=_read_mode("MINING_DATA_MODE"),
            llm_mode=_read_mode("MINING_LLM_MODE"),
            llm_api_key=_read_str("MINING_LLM_API_KEY"),
            llm_base_url=_read_str("MINING_LLM_BASE_URL", "https://api.deepseek.com"),
            llm_model=_read_str("MINING_LLM_MODEL", "deepseek-chat"),
            http_proxy=_read_str("MINING_HTTP_PROXY"),
            user_agent=_read_str("MINING_USER_AGENT", "mining-brief/0.1 (+contact@example.com)"),
            http_timeout_s=_read_float("MINING_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT_S),
            browser_timeout_s=_read_float("MINING_BROWSER_TIMEOUT", DEFAULT_BROWSER_TIMEOUT_S),
            browser_channel=_read_str("MINING_BROWSER_CHANNEL"),
            output_dir=_read_str("MINING_OUTPUT_DIR", "briefs"),
            fetch_attempts=_read_int("MINING_FETCH_ATTEMPTS", DEFAULT_FETCH_ATTEMPTS),
            retry_base_delay_s=_read_float("MINING_RETRY_BASE_DELAY", DEFAULT_RETRY_BASE_DELAY_S),
        )

    def for_live_run(self) -> Settings:
        """`--live` 的语义：把两个开关都置为 live（ADR-0009）。"""
        from dataclasses import replace

        return replace(self, data_mode="live", llm_mode="live")

    @property
    def is_replay(self) -> bool:
        return self.data_mode == "replay" and self.llm_mode == "replay"
