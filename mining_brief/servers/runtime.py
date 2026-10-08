"""三个 MCP server 的**组装点**：把配置、fixture 仓库、抓取器、adapter 拼起来。

这是全仓库唯一"知道自己在哪种模式下"的地方 —— 数据从这一刻往下就只是一堆
已构造好的对象，adapter 与节点都不再判断模式（ADR-0003）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from mining_brief.config.settings import Settings
from mining_brief.config.sources import browser_urls
from mining_brief.datasources.fetchers import Fetcher, build_fetcher
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.news import NewsAdapter
from mining_brief.datasources.prices import PriceAdapter
from mining_brief.datasources.resources import ResourceAdapter, build_resource_source

DEFAULT_FIXTURE_ROOT = Path("fixtures")


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        fixture_root: Path | str = DEFAULT_FIXTURE_ROOT,
    ) -> None:
        self.settings = settings
        self.fixture_root = Path(fixture_root)
        self._store: FixtureStore | None = None

    @property
    def store(self) -> FixtureStore:
        """按需构造 —— 实时模式不需要 fixture，也就不该因为缺清单而启动失败。"""
        if self._store is None:
            self._store = FixtureStore(self.fixture_root)
        return self._store

    def now(self) -> datetime:
        """回放模式的时间真相来自 fixture 锚点，不读系统时钟（ADR-0002）。

        因此回放产出的简报带的是过去的日期 —— 这是刻意的，也是 A1 端到端断言
        可复现的前提（否则今天跑绿、明天跑红）。
        """
        if self.settings.data_mode == "replay":
            return self.store.anchor_at
        return datetime.now(UTC)

    def fetcher(self) -> Fetcher:
        return build_fetcher(
            data_mode=self.settings.data_mode,
            fixture_root=self.fixture_root,
            timeout_s=self.settings.http_timeout_s,
            browser_timeout_s=self.settings.browser_timeout_s,
            user_agent=self.settings.user_agent,
            proxy=self.settings.http_proxy,
            # 哪些源要浏览器，由登记表推出 —— 组装点只负责把它传下去，不判断谁是谁。
            browser_urls=browser_urls(),
            browser_channel=self.settings.browser_channel,
        )

    def news(self) -> NewsAdapter:
        return NewsAdapter(self.fetcher())

    def prices(self) -> PriceAdapter:
        return PriceAdapter(self.fetcher())

    def resources(self) -> ResourceAdapter:
        return ResourceAdapter(
            build_resource_source(
                data_mode=self.settings.data_mode,
                fetcher=self.fetcher(),
                # 冻结的抽取结果放在 fixture 根下的 resources/ 里，与别的数据分开：
                # 它们不是"某个 URL 的原文"，而是**解析器的输出**（见 resources.py）。
                resource_dir=self.fixture_root / "resources",
            )
        )


@lru_cache(maxsize=1)
def default_runtime() -> Runtime:
    """进程级单例。MCP server 启动时用它 —— 环境变量只读一次，行为可预期。"""
    return Runtime(Settings.from_env())
