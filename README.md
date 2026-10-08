# 矿权日报 Agent

> ⏱ **只想快点跑起来？** 直接看 [`RUN.md`](RUN.md) —— clone 到产出日报，5 分钟。

对系统说一句自然语言（如"给我生成一份关于 Pilbara 锂矿的今日简报"），拿到一份 Markdown 矿权日报：**每个事实都能回溯到原始来源，缺什么也明说。**

## 这个系统不做什么

说清楚边界比罗列功能重要：

- **不预测、不估值、不给投资建议。** 越界请求（"预测明年锂价"）会被拒答，并回显听懂的部分 + 可用句式。
- **不编实体。** 矿名或品种不在自带的 8 条档案里，明确说"未覆盖"并列出可选项，绝不幻觉出一座矿。
- **不装权威。** 档案是自带的 8 个矿山，**不是**矿权登记簿 —— 没有公开免费源能支撑后者。
- **不掩饰数据缺口。** 任何一个源挂掉，日报照样出，那一节标注"数据缺失"，由「数据完整性」节说明缺了什么、为什么缺。

## 架构

```
                    ┌─ fetch_news ──────┐
parse_intent → resolve_entities → check_scope ─┼─ fetch_prices ─────┼→ compute_signals → assemble → narrate → verify_citations → render
                    └─ fetch_resources ─┘
                                    │
                              (不在覆盖内 → 拒答 → END)
```

九个节点，**模型只出现在第 1、2、7 个**（`parse_intent` / `resolve_entities` / `narrate`），其余全是纯函数。

三个并行 fetch 节点各自独立超时、重试、失败降级 —— 这是"为什么用图而不是顺序脚本"的全部答案，也是"任一源挂掉日报照样出"的实现方式（见 [`docs/adr/0006`](docs/adr/0006-fetch-nodes-catch-their-own-failures.md)）。

数据采集走三个 MCP server（`mining-news-mcp` / `mineral-pdf-mcp` / `lme-price-mcp`），**LLM 不做工具选择** —— 日报的数据采集是固定流程，把工具选择交给模型只会引入不确定性。同一批 server 可零改动挂进 Claude Desktop / Cursor，见 [`mcp-config.json`](mcp-config.json)。

## 装 / 跑 / 测

```bash
uv sync --all-extras                                          # 装（含浏览器与 PDF 解析这两个可选 extra）
uv run mining-brief brief "给我生成一份关于 Pilbara 锂矿的今日简报"   # 跑
uv run pytest                                                 # 测（默认离线、确定性）
```

默认模式**不需要任何 API key、不联网、结果确定**。`--live` 是唯一的实时开关。

## 数据源与取舍（如实声明）

| 数据 | 采用的源 | 状态 |
|---|---|---|
| 新闻 | mining.com RSS、公司官网 | 直取（需浏览器 UA） |
| 铜价 | LME 官网 | 可抓，但**只有延迟一日收盘价**（Cloudflare，须真实页面导航） |
| 锂价 | GFEX 广期所碳酸锂 | 直取 |
| 铁矿石价 | DCE 大商所铁矿石 | 直取 |
| 储量 | 各公司公开技术报告 PDF | 直取 |

**拿不到的，写在这里，不装：**

- **Platts IODEX / Mysteel / SMM / Fastmarkets**（铁矿石与锂的行业标准价）**全部付费墙**。
- **LME 实时价 / API 需机构注册**，只能用官网延迟收盘价。
- **SHFE 沪铜**是更即时的替代，但 `lme-price` 这个 server 名是题面定的，故铜主用 LME，SHFE 记入 ADR 作备选。
- **铁矿石**这一档标的是"知难而选的妥协项"：主流铁矿公司（BHP / Rio / Vale）走 20-F、不出具 NI 43-101，Fortescue 是例外。它和铜、锂**不是同等质量的数据**。

### 术语声明

题面把 Indicated / Inferred 称作"储量"，这是笔误 —— 它们是**资源量（Resource）**，与 Proven / Probable 的**储量（Reserve）**是不同类别。本项目的处理：产出物节标题沿用题面的「储量数据」，但节内数据严格按真实类别标注。详见 [`CONTEXT.md`](CONTEXT.md)。

## 交付物

| 文件 | 内容 |
|---|---|
| [`RUN.md`](RUN.md) | 题面点名的 5 分钟通道：clone → `docker compose up` → 产物在哪 |
| [`mcp-config.json`](mcp-config.json) | 把三个 server 挂进 Claude Desktop / Cursor（与题面同名放根目录） |
| [`CONTEXT.md`](CONTEXT.md) | 领域术语表，产出物与代码的用词一律以此为准 |
| [`docs/adr/`](docs/adr/) | 九条关键取舍的完整记录 |

## 设计决策

每个关键取舍在 [`docs/adr/`](docs/adr/) 有完整记录，动手前建议先读：

| ADR | 一句话 |
|---|---|
| [0001](docs/adr/0001-replay-seam-in-datasource-layer.md) | 回放模式真走 MCP 协议，但默认不起子进程 |
| [0002](docs/adr/0002-fixture-stores-raw-responses-frozen-clock.md) | fixture 存逐字节原始响应，回放时冻时钟 |
| [0003](docs/adr/0003-datasource-layer-splits-fetcher-from-parser.md) | 数据源层两段式：Fetcher 与 Parser 分离 |
| [0004](docs/adr/0004-price-adapter-falls-back-and-splits-dates.md) | 价格尽力回退，`as_of` 与 `requested_date` 分开 |
| [0005](docs/adr/0005-mcp-tools-return-result-envelopes.md) | MCP 工具统一返回结果信封，缺失是字段不是异常 |
| [0006](docs/adr/0006-fetch-nodes-catch-their-own-failures.md) | 每个 fetch 节点各自兜底（**不要当冗余删掉**） |
| [0007](docs/adr/0007-flat-state-no-reducers-derive-gaps.md) | state 扁平、零 reducer，缺失靠推导 |
| [0008](docs/adr/0008-single-package-and-thin-mcp-servers.md) | 单包布局，MCP server 只做薄壳 |
| [0009](docs/adr/0009-llm-replay-keyed-by-input-hash.md) | LLM 录播按输入数据哈希索引，查不到就报错 |
