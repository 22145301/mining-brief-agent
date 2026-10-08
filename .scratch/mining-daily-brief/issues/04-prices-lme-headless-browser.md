# 04: 价格 · LME 走无头浏览器

**What to build:** 铜价真的出现在日报里。这是三个价格源里**唯一需要无头浏览器**的一个——Cloudflare 拦掉全部普通 HTTP 客户端，只能做真实页面导航——也是唯一带固有延迟的。

**Blocked by:** 03

**Status:** done

**Category:** enhancement

- [x] 浏览器 Fetcher 实现与 HTTP Fetcher **同接口**，adapter 一行都不改（ADR-0003 的两段式在这里兑现价值）
- [x] LME adapter 走真实页面导航取 `span.hero-metal-data__number`，不是 HTTP 直取
- [x] 铜价 `delayed` 恒为 `true`；且它与"回退到了更早日期"是**两件不同的事**，测试分别断言（ADR-0004）
- [x] 浏览器路径超时独立配置（起始 45s），与 HTTP 路径的 15s 分开，都只放在配置里
- [x] **缺浏览器时明确报错，不静默降级成"无数据"**——静默降级会让数据缺失伪装成数据源没数据
- [x] LME 的录播与故障 fixture 就位
- [ ] 日报"价格走势"一节有三项（锂 / 铜 / 铁矿石），截止时间各不相同且如实标注；铜的延迟属性在产物里可见
      —— ⚠️ **半条达成**：铜的延迟属性在产物里可见（已断言）；"三项"这一半**被 06 号工单挡住**，
      因为 `ReportScope.commodity_in_scope` 从 `config/archive.py` 推导，而档案里只有 Pilgangoora 一条。
      见下「未达成（半项）」。

**未达成（半项）**

## 实现记录

### 交付了什么

| 文件 | 内容 |
|---|---|
| `mining_brief/datasources/fetchers.py` | `BrowserFetcher`（渲染后的 DOM，不是解析结果）+ `RoutingFetcher` + `_is_launch_failure`；`build_fetcher` 收 `browser_timeout_s` / `browser_urls` / `browser_channel` |
| `mining_brief/config/sources.py` | `QuoteFormat` 加 `lme_hero`；`PriceSource.requires_browser`；铜的登记条目；`browser_urls()`（由登记表推，不另立清单） |
| `mining_brief/datasources/prices.py` | `_LmeHeroPage` + 纯函数 `parse_lme_hero`；`_latest_at_or_before` / `_series` 的 `lme_hero` 分支 |
| `mining_brief/errors.py` | `LoudFailure` 基类（统一"我们的错、不许降级"）+ `BrowserUnavailable` + `BROWSER_UNAVAILABLE_SENTINEL` |
| `mining_brief/agent/toolkit.py` | 认哨兵串，跨 MCP 边界把它还原成异常 |
| `mining_brief/config/settings.py` | `browser_channel` + `MINING_BROWSER_CHANNEL`；`DEFAULT_BROWSER_TIMEOUT_S = 45.0` |
| `mining_brief/servers/runtime.py` | 把 `browser_urls()` 与两个超时分别接进 `build_fetcher` |
| `scripts/fetch_fixtures.py` | `PlannedSource.via_browser`；`lme` 组；`--browser-channel` / `--browser-timeout`；浏览器与 HTTP 在写盘处合流 |
| `tests/test_price_lme.py` | 25 例（解析 / 延迟与回退分家 / 分流 / 响亮失败 / 真 403 降级 / 超时分开 / 录播可追溯） |
| `tests/test_prices_section.py` | +1 例（铜同时"延迟披露"且"回退自"）；把一处过时的夹具理由改成真实理由 |
| `README.md` / `.env.example` / `price_server.py` | 数据源表改"已接入"；新增"为什么铜价要无头浏览器"小节；`MINING_BROWSER_CHANNEL` 说明；工具 docstring 的四种"没有数" |

### 实测：LME 确实只有浏览器能过

| 方式 | 结果 |
|---|---|
| `httpx` / `urllib` 直取（含浏览器 UA） | **HTTP 403** |
| `curl`（直连） | **HTTP 403** |
| Playwright 起真 Chrome（`channel="chrome"`） | **HTTP 200**，读到 `14415.00` |

403 的那一份**抓下来存成了 fixture**（`fixtures/faults/lme-blocked.html`，5656 字节）。
用它而不是手写一条 `status=403` 的清单条目，是因为手写的那条证明不了任何事。
用它的是**同站另一个页面**（`lme-aluminium`）而非铜的 URL —— 清单按 URL 索引，
一个 URL 只能有一条录播，铜的 URL 已经被"浏览器抓到的正常页面"占了。

录播命令（真跑过，非示意）：

```bash
uv run python scripts/fetch_fixtures.py --only lme --browser-channel chrome \
    --proxy http://127.0.0.1:7897 --throttle 0
#   ok https://www.lme.com/en/metals/non-ferrous/lme-copper -> fixtures/prices/copper-lme-hero.html (289106 bytes)
#   ok 更新 fixtures/sources.json（anchor_at=2026-10-08T17:01:57.311481+00:00）

uv run python scripts/fetch_fixtures.py --only faults --throttle 0
#   ok [HTTP 503] https://httpbin.org/status/503 -> fixtures/faults/upstream-503.html (0 bytes)
#   ok [HTTP 403] https://www.lme.com/en/metals/non-ferrous/lme-aluminium -> fixtures/faults/lme-blocked.html (5656 bytes)
```

**锚点未动**（`anchor_at` 仍是 `2026-10-08T17:01:57.311481+00:00`）—— 补 fixture 不该
推进回放时钟，否则"同一份录播产出同一份日报"当场失效（ADR-0002）。

回放侧端到端确认（真跑过）：

```
copper    status=ok  src=ok  value=14415.0  as_of=2026-10-05 delayed=True fallback=True
lithium   status=ok  src=ok  value=117300.0 as_of=2026-10-08 delayed=False fallback=True
iron_ore  status=ok  src=ok  value=682.5   as_of=2026-10-08 delayed=False fallback=True
```

`delayed` 与 `fallback` 在铜这一行**分别是 True / True**，在锂那一行是 **False / True**
—— 同一个字段组合不出这两种情形，它们确实是两件事。

### 判定一：铜的 `as_of` 取自页面，不取自我们的时钟（ADR/spec 判断）

hero 数字本身**不带日期**。页面自己在数据集日期选择器上写了上界（录播里是
`2026-10-05`），而它比"今天减一天"早三天。两种做法：

1. 拿系统时钟减一天 → 我们会**替数据源断言**一个它没说的日子；
2. 读页面选择器的 `max` → 如实记页面自己说的最新营业日。

选了 (2)。**读不出日期时解析器抛异常**，不给默认值 —— 页面改版时猜一个日子，
日报会印出一个看起来完全正常的错价格，那是这个项目最贵的一类 bug。

### 判定二：`LoudFailure` 基类，而不是在每处 `except ReplayMiss` 后面再加一支

"缺浏览器"与"录播缺失"是同一类东西（我们的错），与"源取不到"（源的问题）相对。
如果每处 catch 各写一次，那么**漏掉一处**就正好是"数据缺失伪装成数据源没数据"
那种事故，而且它不会报错。于是：

- `errors.py` 新基类 `LoudFailure`，成员 `ReplayMiss`、`BrowserUnavailable`；
- 所有 catch 点统一改判 `except LoudFailure: raise`（`prices.py` / `news.py` / `nodes.py` 三处）；
- 跨 MCP 边界（工具只能回文本）用哨兵串 `「无头浏览器不可用」` 传递，**两边共用同一个常量**，
  另写了一例断言这一点。

### 判定三：`RoutingFetcher` 放在数据层，不放在 adapter

"LME 要浏览器"是关于**数据源**的事实，不是关于**运行模式**的事实。adapter 是整个
数据层里唯一**不许**出现模式判断的地方（ADR-0003），所以这条事实随 `browser_urls`
一路注入，adapter 从头到尾不知情 —— 它只知道自己在调 `fetch(url)`。这也就是本票
第一格"adapter 一行都不改"的实际含义：本票对 `prices.py` 的改动全在解析与
`quote_format` 分支上，**没有一处是 `if 浏览器`**。

### 判定四：回放模式**不装配浏览器**

`build_fetcher` 在 `replay` 下直接返回 `FixtureFetcher` —— LME 的录播是一份存下来的
HTML，与别的 fixture 走同一条读取路径。所以"离线跑全套测试"不需要装浏览器、不需要
网络（有一例断言这一点）。playwright 也只在 `_render` 内部**惰性 import**，模块顶层
不 import 它（也有一例断言）。

### 未达成（半项）：第 7 格的"三项"

第 7 格要求日报价格一节有锂 / 铜 / 铁矿石三项。"铜的延迟属性在产物里可见"这一半
**已达成并断言**（`tests/test_prices_section.py::test_a_delayed_commodity_that_also_fell_back_prints_both_qualifiers`）。
"三项"这一半达不到，原因**不在本票的代码**：

`ReportScope.commodity_in_scope` 从 `config/archive.py` 推导，而档案里只有
Pilgangoora 一条（锂）。铁矿石与铜即使在 `PRICE_SOURCES` 里登记好了、工具也真能
取到数，它们也进不了范围。`archive.py` 自己的注释写着"完整 8 座矿山由 06 号工单补齐"。

`fetch_prices`（`agent/nodes.py:428`）本来就是按 `scope.commodity_in_scope` 循环并
逐个降级的，**档案一补齐它就会长出三项**，不需要再改代码。

处置：按工单 03 的先例，这一格留 `[ ]`，不假装跑到了。打开它的是 06 号工单。

### 遗留（交给后续工单）

1. **06**：档案补到 8 座矿山 → 打开本票第 7 格，以及 03 号工单的同名未达成项。
2. **`datasources/resources.py` 尚未检查**是否也需要 `except LoudFailure: raise` 那
  一支（`prices.py` / `news.py` / `nodes.py` 已有）。本票范围内它还没接到 fetcher 上，
   接的时候必须一起补 —— 留待 05 号工单。
3. **`_RENDER_SETTLE_MS = 4000` 是起点值**（ADR-0006 的"起点值"约定）：本机实测够用，
   换机器/换网络应重新校准。
4. **playwright 自带 chromium 在本机没装**，所以本仓库的 `MINING_BROWSER_CHANNEL=chrome`
   走系统 Chrome。`uv run playwright install chromium` 之后可以留空用自带的。
