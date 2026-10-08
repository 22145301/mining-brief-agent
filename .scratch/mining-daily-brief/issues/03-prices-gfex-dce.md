# 03: 价格 · GFEX 与 DCE

**What to build:** 锂价与铁矿石价真的出现在日报的"价格走势"一节，各自带自己的数据截止时间与来源链接。这是价格与储量的桩里第一个被填上的。

**Blocked by:** 01

**Status:** done

**Category:** enhancement

- [x] `get_price` 返回**不晚于请求日期的最近可得值**，同时携带 `as_of` 与 `requested_date`（ADR-0004）
- [x] `get_trend` 返回窗口内的价格序列
- [x] 回退**不设独立标志位**，一律由 `as_of < requested_date` 表达；`delayed` 只表示数据源固有延迟，两者测试分别断言
- [x] 锂路由到 GFEX 碳酸锂、铁矿石路由到 DCE，各自走纯 HTTP 抓取（已实测可直接抓，不需要浏览器）
      —— ⚠️ **半条有实测更正**：DCE **官网**抓不到，铁矿石改用新浪财经转载的 DCE `i` 合约。见下。
- [x] 查一个确实没有数据的日期，返回明确的"未找到"，不是零、也不是近似值
- [x] 抓取层与解析层分离，adapter 里**不出现任何模式判断分支**（ADR-0003）
- [x] 数据录播就位：原始响应逐字节存，附 `sources.json` 记 URL / SHA256 / 抓取时间 / 状态
- [x] 故障 fixture 就位（一份原始响应里带 503），供 A7 用，**不往代码里打桩**
- [x] 两个工具的直连用例（切面 S2）走默认回放全绿
- [ ] 日报"价格走势"一节从"数据缺失"变成含锂与铁矿石两项，且两项的截止时间如实标注、互不相同
      —— ❌ **判定：在当前端到端路径上做不到**，原因见下。不是没做，是这条路走不通。

**未达成（1 项）**

## 实现记录

### 交付了什么

| 文件 | 内容 |
|---|---|
| `mining_brief/config/sources.py` | `PriceSource` 登记表 + `PRICE_SOURCES`（锂、铁矿石）；`QuoteFormat` 两种请求形状 |
| `mining_brief/datasources/prices.py` | 纯函数 `parse_gfex_daily` / `parse_sina_kline` / `candidate_dates` / `trading_date` + `PriceAdapter`（只做编排） |
| `mining_brief/datasources/fetchers.py` | `Fetcher.post_form` + 共享的 `canonical_post_url`（回放与实抓用同一套键） |
| `scripts/fetch_fixtures.py` | POST 源、`corroboration` 组、`faults` 组、`--throttle`、`_prune_stale`；锚点默认沿用 |
| `tests/test_price_parsers.py` | 解析层（11 例，含跨源核对） |
| `tests/test_price_tool.py` | S2 直连（11 例，含真 503 故障） |
| `tests/test_prices_section.py` | 第四节排版规则（6 例，覆盖端到端到不了的两品种路径） |
| `mining_brief/servers/price_server.py` | docstring 更正为实际路由；写明"未找到 / 取不到 / 录播缺失"三分 |
| `README.md` | 数据源表更正 + "为什么铁矿石不用 DCE 官网"小节 |
| `pyproject.toml` | 新增 `tzdata==2025.2`（**功能性依赖**，见下） |

### 判定一：铁矿石改走新浪财经转载的 DCE 合约

工单原文写"已实测可直接抓，不需要浏览器"——**这条实测结论对 DCE 不成立**。

`www.dce.com.cn` 整站挂在一套 JS 挑战式 WAF 后面，对 `urllib`、`curl`、以及**真的
Chrome**（Playwright，`channel="chrome"`）一律返回 **HTTP 412** 加一段挑战脚本。
两次有界尝试后停手（有界是刻意的：不要把一个"抓不到"变成一晚上的反复重试）。

改用新浪财经的历史日 K 线，它载的**就是 DCE 的 `i` 合约**，而且**可交叉核对** ——
2026-10-08，GFEX 官方（碳酸锂主力 2701）与新浪（碳酸锂 `lc0`）三个字段逐项相同：

| 字段 | GFEX 官方 | 新浪 | 是否被断言 |
|---|---|---|---|
| 收盘 `close` / `c` | 117300 | 117300 | ✅ |
| 结算 `clearPrice` / `s` | 121540 | 121540 | ✅ |
| 持仓 `openInterest` / `p` | 409678 | 409678 | ✅ |

三个**量纲完全不同**的字段同时相等，说明解析层没读错。断言在
`tests/test_price_parsers.py::test_sina_agrees_with_the_gfex_official_number`。

**纪律说明**：这处偏离**没有**改动 ADR 或 PRD 的结论，只改了 `config/` 里的一行
登记（`price_source.quote_url`）并在代码注释与 README 里写明理由。`exchange` 仍记
`DCE`（合约所属），引用块的 `publisher` 记新浪财经（数据**发布方**）。

### 判定二：`tzdata` 成为功能性依赖

Windows / macOS 上 `zoneinfo.ZoneInfo("Asia/Shanghai")` 会抛 `ZoneInfoNotFoundError`
（没有系统 IANA 库）。价格模块要用**北京时间**判交易日 —— 锚点 `2026-10-08T17:01Z`
在 UTC 是 10-08、在北京已经是 **10-09**，用 UTC 算会整体差一天。所以这不是"某个
平台的可选优化"，缺了它陌生人 clone 下来第一次查价就崩。

### 判定三：为什么第 10 条走不通（**未达成，如实记录**）

`ReportScope.commodity_in_scope` 是从 `config/archive.py` 推出来的，而档案里只有
**一条**（Pilgangoora / Pilbara Minerals / **lithium**）。于是：

1. **铁矿石永远进不了范围**。它在 `PRICE_SOURCES` 里登记齐全、`get_price` /
   `get_trend` 都真能取到数（`test_price_tool.py` 里直接调用证明了），但端到端的
   范围推导不会把它带进来 —— 第四节永远只有锂一项。
2. **"截止时间互不相同"也达不到**。2026 年国庆 10-01…10-07 休市，两个交易所都只在
   10-08 发布了行情，而回放时钟是北京时间 10-09 凌晨（那天两边都还没发布）。
   所以两项的 `as_of` **都是 2026-10-08** —— 巧了，但确实相同。
3. 想让它成立就得让一句请求同时覆盖锂与铁矿石，而**离线改不了请求**：LLM 录播按
   输入哈希寻址，没有 API key 就无法录一条新的 `parse_intent`。这是红线 ②，不做。

**已做的补偿**：把这套排版规则拿到单元层面钉住（`tests/test_prices_section.py`，
6 例），覆盖"两个品种各占一行、各标各的日期、各成一条引用"。也就是说规则**是对的、
被测的**，只是端到端目前到不了那条路。要在端到端上看到，得先给档案加一条铁矿条目
（或让范围支持多品种）—— 已写进交接报告的"需要人做的事"。

### 顺带更正的两处既存断言

- `tests/test_e2e_slice.py` 还断言第四节 `facts == ()` 且 note 里有"数据缺失" ——
  价格接通后这是**过期的**。改为断言"锂有一个带引用的价格事实 + 截止时间是最后
  交易日而不是今天"，并把"价格已接通"和"储量仍缺失"放在同一条里各就各位。
- 同一文件里拿价格当"降级样本"的那条，改拿**储量**当样本（锚定时刻唯一还取不到的
  源），并加强为"同一个理由要在它自己那节与第六节里原样出现"。

这两处都不是为了让测试变绿而放宽：改动后断言**更多**，且新增了"过期的免责声明
不得残留"（`"尚未接入" not in integrity`）这类反向守卫。

### 验证

```
uv run pytest -q          # 93 passed
uv run ruff check .       # All checks passed!
uv run black --check .    # 55 files would be left unchanged
uv run mypy .             # Success: no issues found in 55 source files
```
