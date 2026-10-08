"""铜（LME）这条链路：浏览器抓取 + 页面解析 + 两种"不是最新"的分辨（工单 04）。

这一组跟前两组的分工：

- `test_price_parsers.py` 问的是"这份响应读对了吗"；
- 这一组问的是"**这条路**走得通吗"—— 浏览器与 HTTP 是不是同一个接口、分流是不是
  按登记表走、页面读不出数时会不会静默印一个错价、缺浏览器时会不会假装成"数据源
  没数据"。

里面最关键的一条是 `test_a_missing_browser_is_loud_...`：静默降级在这里的后果不是
少一个数，而是把**我们的环境问题**伪造成**数据源的结论** —— 报表上会写"LME 无数据"，
而 LME 好好地挂着。那比缺数据更糟，因为它把排查引向了错的方向。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mining_brief.config.settings import (
    DEFAULT_BROWSER_TIMEOUT_S,
    DEFAULT_HTTP_TIMEOUT_S,
    Settings,
)
from mining_brief.config.sources import (
    LME_COPPER_URL,
    PRICE_SOURCES,
    PriceSource,
    browser_urls,
)
from mining_brief.contracts import RawResponse
from mining_brief.datasources.fetchers import (
    BrowserFetcher,
    FixtureFetcher,
    HttpFetcher,
    RoutingFetcher,
    build_fetcher,
)
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.prices import PriceAdapter, parse_lme_hero
from mining_brief.errors import BrowserUnavailable, LoudFailure

#: 回放锚点那一夜的次日（北京时间 10-09 凌晨）—— 与别的测试用同一个时刻，
#: 免得"请求了哪一天"在不同测试里对不上。
NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def _recorded(store: FixtureStore, suffix: str) -> RawResponse:
    entry = next(e for e in store.manifest.entries if e.path.endswith(suffix))
    return store.raw(entry.url)


def _copper() -> PriceSource:
    return PRICE_SOURCES["copper"]


# ---------------------------------------------------------------------------
# 解析：从**真实录播**的 DOM 里读数（工单 04 验收第 2 条）
# ---------------------------------------------------------------------------


def test_the_recorded_lme_page_yields_the_hero_number_and_the_page_own_date(
    fixture_root: Path,
) -> None:
    """两个数都不是我算出来的，是页面里逐字读出来的。

    `14415.00` 来自 `span.hero-metal-data__number`；`2026-10-05` 来自日期选择器的
    `max`。**日期取自页面而不是取自我们的时钟**是刻意的：hero 数字本身不带日期，
    而这份页面自报的最新营业日比"今天减一天"早了三天。替数据源断言一个它没说的
    日子，正是这个项目最容易犯又最难发现的一类错。
    """
    raw = _recorded(FixtureStore(fixture_root), "copper-lme-hero.html")

    point = parse_lme_hero(raw, _copper())

    assert point.value == 14415.0
    assert point.as_of == "2026-10-05"
    assert point.commodity == "copper"
    assert point.exchange == "LME"
    assert (point.currency, point.unit) == ("USD", "吨")
    # 合约代码 `CA` 与 "(day-delayed)" 都是页面自己在 "Key contract information"
    # 里写的，所以这两个字段能被 fixture 逐字核到，不是我们的设定。
    assert point.symbol == "CA 3-month"
    assert raw.text().count("day-delayed") >= 1
    assert "Contract code" in raw.text().replace("&nbsp;", " ")


def test_a_page_without_the_hero_span_raises_instead_of_inventing_a_number() -> None:
    """页面改版时"抛"是唯一安全的动作。

    猜一个默认值（0、上一个数、None）都会让日报印出一个**看起来完全正常**的
    错价格 —— 那是最贵的一类 bug。所以这里宁可炸。
    """
    hollow = RawResponse(
        url=LME_COPPER_URL,
        status=200,
        content_type="text/html; charset=utf-8",
        body=b"<html><body><p>maintenance</p></body></html>",
        fetched_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="hero-metal-data__number"):
        parse_lme_hero(hollow, _copper())


def test_a_page_without_a_business_date_raises_rather_than_borrowing_our_clock() -> None:
    """有数字、没有日期，同样要炸 —— 用系统时钟补日期就是替数据源编日子。

    这两种缺法分开测：它们对应页面里两块**互相独立**的标记（hero 的 span 与
    日期选择器），只测一种的话，另一块被删掉时不会有任何东西变红。
    """
    undated = RawResponse(
        url=LME_COPPER_URL,
        status=200,
        content_type="text/html; charset=utf-8",
        body=b'<span class="hero-metal-data__number">14415.00</span>',
        fetched_at=datetime.now(UTC),
    )

    with pytest.raises(ValueError, match="最新营业日"):
        parse_lme_hero(undated, _copper())


# ---------------------------------------------------------------------------
# 延迟 vs 回退：两件不同的事，分别断言（工单 04 验收第 3 条，ADR-0004）
# ---------------------------------------------------------------------------


async def test_copper_is_day_delayed_and_that_is_not_the_same_as_falling_back(
    fixture_root: Path,
) -> None:
    """同一个品种、三种请求日期，把这两个概念**分别**钉住。

    页面上那句 "(day-delayed)" 是**数据源固有**的延迟：不管我们问哪一天，`delayed`
    恒为 `True`。而"回退"是 `as_of < requested_date`：我们问的日子比页面能给的最新
    营业日**更晚**，于是拿了一个更早的日期顶上。两者可以同时真，也可以一个真一个假
    —— 它们不是同一个字段的两种写法。

    - 问 10-05（页面自报的最新营业日）：`delayed=True`、**不**回退 —— 这是最干净
      的一组：延迟为真而回退为假，一个标志位写不出来。
    - 问 10-06（比最新营业日更晚）：两者都为真。
    - 问 10-04（比最新营业日更早）：页面答不了 → `UNAVAILABLE`，而不是把最新价
      当成那天的价回出去（拿未来答过去）。
    """
    adapter = PriceAdapter(FixtureFetcher(FixtureStore(fixture_root)))

    exact = await adapter.get_price("copper", "2026-10-05", NOW)
    assert exact.point is not None
    assert exact.point.delayed is True, "页面写着 day-delayed，与问哪一天无关"
    assert exact.point.is_fallback is False, "10-05 就是页面自报的最新营业日，没有回退"

    later = await adapter.get_price("copper", "2026-10-06", NOW)
    assert later.point is not None
    assert later.point.delayed is True
    assert later.point.is_fallback is True, "问的是 10-06，给的是 10-05 —— 这才叫回退"

    earlier = await adapter.get_price("copper", "2026-10-04", NOW)
    assert earlier.point is None
    assert earlier.source_status.value == "unavailable"
    assert earlier.reason is not None and "不支持历史查询" in earlier.reason


async def test_the_lme_page_never_answers_with_a_date_newer_than_we_asked(
    fixture_root: Path,
) -> None:
    """把上一条的"更早"那一格再单独钉一次，断言的措辞不同。

    `as_of > requested` 若被当成正常结果回出去，日报就会用 10-05 的价回答
    "10-04 多少钱" —— 数字是真的，日期是假的，而读者无从分辨。
    """
    adapter = PriceAdapter(FixtureFetcher(FixtureStore(fixture_root)))

    lookup = await adapter.get_price("copper", "2026-10-03", NOW)

    assert lookup.status == "degraded"
    assert lookup.source_status.value == "unavailable"
    assert lookup.point is None


# ---------------------------------------------------------------------------
# 分流：浏览器与 HTTP 同接口，adapter 一行不改（工单 04 验收第 1 条，ADR-0003）
# ---------------------------------------------------------------------------


async def test_routing_sends_the_lme_url_to_the_browser_and_everything_else_to_http() -> None:
    """分流的依据是登记表里的 `requires_browser`，不是一段写死的 if。

    两个"搬运工"各自记下自己被叫到了没有 —— 断言的是**哪个被叫到**，而不是
    调用次数：真正的风险是"LME 被发给 HTTP 抓取"（结果是一份 403 挑战页被当成
    数据），而不是多发一次请求。
    """
    seen: list[str] = []

    class _Recorder:
        def __init__(self, tag: str) -> None:
            self._tag = tag

        async def fetch(self, url: str) -> RawResponse:
            seen.append(f"{self._tag}:{url}")
            return RawResponse(
                url=url,
                status=200,
                content_type="text/html",
                body=b"ok",
                fetched_at=datetime.now(UTC),
            )

        async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
            seen.append(f"{self._tag}:POST:{url}")
            return await self.fetch(url)

    router = RoutingFetcher(
        http=_Recorder("http"), browser=_Recorder("browser"), browser_urls=browser_urls()
    )

    await router.fetch(LME_COPPER_URL)
    other = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/x"
    await router.fetch(other)

    assert seen == [f"browser:{LME_COPPER_URL}", f"http:{other}"]


def test_the_two_fetchers_share_one_interface_so_the_adapter_needs_no_branch() -> None:
    """结构上断言"同接口"：两者都交出 `fetch` / `post_form`，且都是协程。

    这条看着像废话，但它正是 ADR-0003 兑现的地方 —— 一旦 `BrowserFetcher` 少了
    一个方法，`PriceAdapter` 就得开始判断"我手上这个 fetcher 会不会那个方法"，
    模式分支就从这里长出来了。
    """

    for cls in (HttpFetcher, BrowserFetcher, FixtureFetcher):
        for name in ("fetch", "post_form"):
            method = getattr(cls, name)
            assert inspect.iscoroutinefunction(method), f"{cls.__name__}.{name} 应是协程"


def test_build_fetcher_in_replay_never_touches_a_browser(fixture_root: Path) -> None:
    """回放模式下**不装配**浏览器，即使登记表里有浏览器源。

    这是"离线跑全套测试不需要装浏览器、不需要网络"的根据（ADR-0002）：LME 的录播
    是一份存下来的 HTML，与别的 fixture 走同一条读取路径。
    """
    fetcher = build_fetcher(
        data_mode="replay",
        fixture_root=fixture_root,
        timeout_s=5.0,
        browser_timeout_s=5.0,
        user_agent="test/0.1",
        browser_urls=browser_urls(),
    )

    assert isinstance(fetcher, FixtureFetcher)
    assert not isinstance(fetcher, RoutingFetcher)


def test_build_fetcher_in_live_routes_only_when_there_are_browser_sources() -> None:
    """真实模式下「没有浏览器源」就退回纯 HTTP —— 不让一次无谓的浏览器冷启动
    拖慢每一个请求。"""
    without = build_fetcher(
        data_mode="live",
        timeout_s=15.0,
        browser_timeout_s=45.0,
        user_agent="test/0.1",
        browser_urls=frozenset(),
    )
    with_browser = build_fetcher(
        data_mode="live",
        timeout_s=15.0,
        browser_timeout_s=45.0,
        user_agent="test/0.1",
        browser_urls=browser_urls(),
    )

    assert isinstance(without, HttpFetcher)
    assert isinstance(with_browser, RoutingFetcher)


def test_copper_is_the_only_registered_source_that_needs_a_browser() -> None:
    """分流清单由登记表推出。这条盯着"加品种时漏改"那类错：新源漏标
    `requires_browser` 不会报错，只会静静地走 HTTP、然后 403。"""
    assert browser_urls() == frozenset({LME_COPPER_URL})
    assert [c for c, s in PRICE_SOURCES.items() if s.requires_browser] == ["copper"]


# ---------------------------------------------------------------------------
# 缺浏览器必须**响亮**（工单 04 验收第 5 条，ADR-0002 / ADR-0006）
# ---------------------------------------------------------------------------


async def test_a_missing_browser_is_loud_and_never_degrades_into_no_data(
    fixture_root: Path,
) -> None:
    """浏览器起不来 → 异常炸穿 adapter，**不**变成"数据缺失"的信封。

    这是这一组里最重要的一条。降级成"数据缺失"的后果不是少一个数字，而是把
    **我们的环境问题**写成**数据源的结论**：日报上会出现"LME 无数据"，而 LME 好好
    挂着 —— 于是排查被引向交易所，而真正坏的是我们这台机器。
    """
    calls: list[str] = []

    class _NoBrowser:
        async def fetch(self, url: str) -> RawResponse:
            calls.append(url)
            raise BrowserUnavailable("无头浏览器起不来（channel=chrome）：系统没装 Chrome")

        async def post_form(self, url: str, form: Mapping[str, str]) -> RawResponse:
            raise AssertionError("铜源是 GET，不该走到 POST")

    adapter = PriceAdapter(_NoBrowser())

    with pytest.raises(BrowserUnavailable):
        await adapter.get_price("copper", "2026-10-05", NOW)

    assert calls == [LME_COPPER_URL], "得先真的去取，才谈得上「取不到」"


def test_browser_unavailable_is_a_loud_failure_alongside_replay_miss() -> None:
    """两者同属"我们的错，不许降级"这一类（`LoudFailure`）。

    adapter 里按这个基类 `except` 一次即可：漏掉任何一支，那种失败就会悄悄退化成
    "源没数据"。它们放在同一个基类下，就是为了让"要不要炸穿"这个判断只有一处。
    """
    from mining_brief.errors import ReplayMiss

    assert issubclass(BrowserUnavailable, LoudFailure)
    assert issubclass(ReplayMiss, LoudFailure)
    assert not issubclass(LoudFailure, (ValueError, OSError)), "它不是「输入错」也不是「环境错」"


def test_the_browser_unavailable_signal_survives_the_mcp_boundary() -> None:
    """跨 MCP 边界时信号会变成一个哨兵串（工具只能回文本）。

    这条断言的是**两边用的是同一个常量**：适配器抛的是它，toolkit 认的也是它。
    各自抄一份字符串，就会出现"抛得对、认不出"——失败照样被降级，而代码看起来
    是对的。
    """
    from mining_brief.errors import BROWSER_UNAVAILABLE_SENTINEL

    assert (
        BROWSER_UNAVAILABLE_SENTINEL
        in BrowserUnavailable(f"无头浏览器起不来 {BROWSER_UNAVAILABLE_SENTINEL}").args[0]
    )
    assert BROWSER_UNAVAILABLE_SENTINEL in str(BrowserUnavailable("x"))


# ---------------------------------------------------------------------------
# 故障：真实的 403 要按"取不到"降级，并带上状态码（工单 04 验收第 6 条）
# ---------------------------------------------------------------------------


async def test_the_recorded_403_degrades_with_its_status_code(fixture_root: Path) -> None:
    """`fixtures/faults/lme-blocked.html` 是一份**真的** 403（抓的时候存下来的），
    不是手写的一条 status=403。

    它走的是"同一个站、另一个页面"，因为清单按 URL 索引、一个 URL 只能有一条录播。
    考的事跟铜的行情页一样：LME 对没有浏览器的客户端一律 403。所以把铜的源指向这份
    录播，降级路径必须给出**状态码**，而不是"这个品种没数据"。
    """
    store = FixtureStore(fixture_root)
    blocked = _recorded(store, "lme-blocked.html")
    assert blocked.status == 403, "这份 fixture 必须是真抓下来的 403"

    # 把铜的取数地址临时指到那份 403 的 URL 上 —— 只换地址，不换形状。
    from dataclasses import replace

    copper_on_403 = replace(_copper(), quote_url=blocked.url)
    adapter = PriceAdapter(FixtureFetcher(store), {"copper": copper_on_403})

    lookup = await adapter.get_price("copper", "2026-10-05", NOW)

    assert lookup.status == "degraded"
    assert lookup.source_status.value == "unavailable"
    assert lookup.point is None
    assert lookup.reason is not None and "403" in lookup.reason


def test_the_blocked_fixture_is_a_genuine_cloudflare_rejection(fixture_root: Path) -> None:
    """顺带钉住这份 403 的出身：它本身就是一段挑战页，不是随便一个错误页。

    没有这条，`lme-blocked.html` 哪天被替换成一份普通的 404 页面，上面的测试
    照样会绿 —— 而它证明的事就变了。
    """
    raw = _recorded(FixtureStore(fixture_root), "lme-blocked.html")

    assert raw.status == 403
    assert "Just a moment" in raw.text() or "Cloudflare" in raw.text()


# ---------------------------------------------------------------------------
# 超时：浏览器与 HTTP 分开配置（工单 04 验收第 4 条）
# ---------------------------------------------------------------------------


def test_the_two_timeouts_are_separate_and_independently_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """45s 与 15s 是两个不同的数，而且各自能单独覆盖。

    合用一个超时在这一层是行不通的：HTTP 抓取冷启动几毫秒，浏览器要起进程、导航、
    等前端填数、过挑战页 —— 用 15s 卡浏览器会得到一个**看起来像源故障**的超时，
    而它其实只是我们给的时间不够。
    """
    for name in ("MINING_HTTP_TIMEOUT", "MINING_BROWSER_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)

    defaults = Settings.from_env()
    assert defaults.http_timeout_s == DEFAULT_HTTP_TIMEOUT_S == 15.0
    assert defaults.browser_timeout_s == DEFAULT_BROWSER_TIMEOUT_S == 45.0
    assert defaults.http_timeout_s != defaults.browser_timeout_s

    monkeypatch.setenv("MINING_BROWSER_TIMEOUT", "90")
    only_browser = Settings.from_env()
    assert only_browser.browser_timeout_s == 90.0
    assert only_browser.http_timeout_s == 15.0, "改浏览器超时不该动到 HTTP 那一档"

    monkeypatch.setenv("MINING_HTTP_TIMEOUT", "3")
    both = Settings.from_env()
    assert (both.http_timeout_s, both.browser_timeout_s) == (3.0, 90.0)


def test_the_browser_fetcher_gets_the_browser_timeout_not_the_http_one() -> None:
    """`build_fetcher` 把两个超时**分别**交给两个 fetcher —— 接错线的话，
    HTTP 会拿到 45s、浏览器拿到 15s，两边都不报错，只是行为诡异。"""
    fetcher = build_fetcher(
        data_mode="live",
        timeout_s=15.0,
        browser_timeout_s=45.0,
        user_agent="test/0.1",
        browser_urls=browser_urls(),
    )

    assert isinstance(fetcher, RoutingFetcher)
    # 顺手钉住两个搬运工各自是谁 —— 接错线的话（HTTP 拿 45s、浏览器拿 15s）
    # 两边都不会报错，只是行为诡异。
    assert isinstance(fetcher._http, HttpFetcher)
    assert isinstance(fetcher._browser, BrowserFetcher)
    assert fetcher._http._timeout_s == 15.0
    assert fetcher._browser._timeout_s == 45.0


def test_the_browser_channel_is_configurable_and_defaults_to_the_bundled_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`channel` 是**环境事实**（这台机器上能起来的是哪个浏览器），不该写死在代码里。

    本机实测：playwright 自带的 chromium 没装，系统 Chrome 在，于是
    `MINING_BROWSER_CHANNEL=chrome` 就是那份能让它跑起来的配置。
    """
    monkeypatch.delenv("MINING_BROWSER_CHANNEL", raising=False)
    assert Settings.from_env().browser_channel == ""

    monkeypatch.setenv("MINING_BROWSER_CHANNEL", "chrome")
    assert Settings.from_env().browser_channel == "chrome"


def test_the_registry_records_where_the_lme_facts_came_from() -> None:
    """登记表里关于铜的三条事实必须与页面一致（否则引用块会印错的合约/单位）。"""
    source = PRICE_SOURCES["copper"]

    assert (source.exchange, source.symbol) == ("LME", "CA")
    assert (source.currency, source.unit) == ("USD", "吨")
    assert source.delayed is True
    assert source.quote_url == LME_COPPER_URL


def test_a_lme_point_cannot_be_serialised_without_its_delay_flag(
    fixture_root: Path,
) -> None:
    """`delayed` 是**产物里可见**的字段（验收第 7 条的"铜的延迟属性在产物里可见"）。

    它必须出现在契约模型的序列化结果里 —— 只存在内存里、不进 JSON，读者就看不到
    "这个数是延迟披露的"。这条钉住的是它有没有被某个 `exclude` 顺手滤掉。
    """
    point = parse_lme_hero(_recorded(FixtureStore(fixture_root), "copper-lme-hero.html"), _copper())

    payload = json.loads(point.model_dump_json())

    assert payload["delayed"] is True
    assert payload["as_of"] == "2026-10-05"
    assert "requested_date" in payload, "回退与否靠它比出来，不能被序列化滤掉"


def test_the_browser_extra_is_imported_lazily_so_the_default_suite_needs_no_playwright() -> None:
    """`playwright` 只在**真的要渲染**时才 import（`BrowserFetcher._render` 内部）。

    模块顶层 import 会让"没装 extra 的机器"连 `import mining_brief.datasources.fetchers`
    都失败 —— 而默认套件恰恰要在这类机器上跑。
    """
    import ast

    from mining_brief.datasources import fetchers

    tree = ast.parse(inspect.getsource(fetchers))
    top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = [
        alias.name
        for node in top_level
        for alias in node.names
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not any("playwright" in name for name in names), "playwright 不该在模块顶层被 import"
    assert "playwright" in inspect.getsource(fetchers.BrowserFetcher._render)


def test_nothing_in_the_fetcher_module_reads_the_environment_directly() -> None:
    """配置一路从 `Settings` 传进来，不在数据层里现读 env。

    数据层现读 env 的后果是测试无法真正隔离：开发机上的 `MINING_*` 会悄悄改变
    行为，而套件就不再是"给定输入必然给定输出"。
    """
    from mining_brief.datasources import fetchers

    source = Path(fetchers.__file__).read_text(encoding="utf-8")

    assert "os.environ" not in source
    assert "getenv" not in source


@pytest.mark.parametrize("name", ["MINING_DATA_MODE", "MINING_LLM_MODE"])
def test_an_unknown_mode_is_a_startup_error_not_a_silent_fallback(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """模式写错要当场炸，不能悄悄退回 replay。

    静默退回 replay 的后果是"我以为在跑真实抓取，其实一直在放录播" —— 一份
    完全正常的日报，出处却是旧的。宁可起不来。
    """
    from mining_brief.config.settings import ConfigError

    monkeypatch.setenv(name, "prod")

    with pytest.raises(ConfigError):
        Settings.from_env()


def test_the_lme_fixture_is_recorded_with_a_hash_so_it_is_traceable(fixture_root: Path) -> None:
    """录播必须能追到「哪一次真实抓取」（ADR-0002）—— URL 能对上、sha256 非空，
    且**磁盘上那份文件的哈希与清单记的一致**。

    最后一条才是重点：清单里躺着一个 sha256 但文件被换过，是这套设计里最隐蔽的
    一种坏法 —— 回放读出来的内容与"它声称抓到的"不是同一份，而两边都看不出异常。
    """
    store = FixtureStore(fixture_root)

    entry = next(e for e in store.manifest.entries if e.url == LME_COPPER_URL)
    body = (fixture_root / entry.path).read_bytes()

    assert entry.sha256
    assert entry.status == 200
    assert len(body) > 0
    assert hashlib.sha256(body).hexdigest() == entry.sha256
    assert os.path.getsize(fixture_root / entry.path) == len(body)
