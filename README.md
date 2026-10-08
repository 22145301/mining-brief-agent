# 矿权日报 Agent

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

> ⏱ **只想快点跑起来？** 直接看 [`RUN.md`](RUN.md) —— clone 到产出日报，5 分钟。
>
> badge 里的 `OWNER/REPO` 是**全仓库唯一需要替换的占位**：badge 指向 GitHub 上的
> Actions 结论，而本仓库当前没有 git remote（还没推上去）。推之前替换一次即可。

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

不装 uv 也行：`docker compose up` 跑同一件事（跑完即退，产物落在挂载出来的 `./briefs/`，
与本地跑逐字节相同 —— 镜像里跑的也是回放）。两条路的取舍见 [`RUN.md`](RUN.md)。

默认模式**不需要任何 API key、不联网、结果确定**。代价写在明面上：**回放只认录过的输入**，
换一句没录过的话它会报 `LLMReplayMiss` 而不是偷偷去调模型（ADR-0009）——离线可问的就是
`scripts/record_llm.py` 里那四条样例句（一句出报、一句整档案出报、两句拒答）。
`--live` 是唯一的实时开关。

### 开发闸门（CI 跑的就是这四条）

```bash
uv run ruff check . && uv run ruff format --check .   # lint + 格式化
uv run mypy                                           # 严格模式，覆盖 tests/
uv run pytest                                         # 默认套件：离线、确定性
uv run pytest -m stdio                                # 真子进程走 stdio 传输
```

格式化**只有一个权威**（ruff）。Black 与 `ruff format` 对同一份文件会给出不同结果，
两个都挂只会让 CI 取决于谁先跑 —— 实测记录写在 `pyproject.toml` 里。

### 挂进 MCP 宿主（Claude Desktop / Cursor / Claude Code）

三个 server 也能**脱离这份日报**单独用。根目录的 [`mcp-config.json`](mcp-config.json)
把三个都列好了，都是 `uv run --directory ${workspaceFolder} <server 名>`：

- **Cursor / Claude Code（项目级）**：`${workspaceFolder}` 由宿主替换成仓库路径，**原样可用**。
- **Claude Desktop**：它不做变量替换，把 `${workspaceFolder}` 换成 clone 的绝对路径即可
  （`sed -i "s|\${workspaceFolder}|$PWD|g" mcp-config.json`）。
- 想再省一步：`uv tool install .` 会把三个名字放进 PATH，此时 `command` 直接写
  `mining-news-mcp` 就行 —— 但要把 `MINING_FIXTURE_ROOT` 指向 clone 里的 `fixtures/`
  （工具装到别处的 venv 里了，录播不在它旁边）。

自查一条命令：

```bash
claude mcp list        # 三个都该是 ✔ Connected
```

在真宿主里实测过（2026-10-08，Claude Code，`✔ Connected` × 3）。两个细节让这件事成立：
**默认录播根按安装位置推、不按 cwd 推**（宿主拉起 server 时工作目录是宿主的），
以及**日志一律走 stderr**（stdio 传输下 stdout 只归协议所有）。两条都有用例守着，
见 `tests/test_stdio_smoke.py`。

## 数据源与取舍（如实声明）

| 数据 | 采用的源 | 状态 |
|---|---|---|
| 新闻 | mining.com RSS、Australian Mining RSS + 文章页 | 直取（mining.com 本机需走代理，否则 CloudFront 403） |
| 锂价 | GFEX 广期所官方日行情（POST 表单，按日索取） | **已接入**，主力合约取持仓量最大者 |
| 铁矿石价 | 新浪财经转载的 DCE `i` 合约日 K 线（GET，含全史） | **已接入**，见下方"为什么不是 DCE 官网" |
| 铜价 | LME 官网行情页（3 个月收盘价） | **已接入**（走**无头浏览器**，见下）；数据源固有 "day-delayed"，如实标注 |
| 储量 | 各公司公开技术报告 PDF（JORC 与 NI 43-101 走**同一条**解析路径） | **已接入**：Pilgangoora 用公司公开的 CET 演示材料第 36 页（**不是**独立技术报告，取舍见下），另登记 PMET 的 2025 年技术报告 |

**拿不到的，写在这里，不装：**

- **Platts IODEX / Mysteel / SMM / Fastmarkets**（铁矿石与锂的行业标准价）**全部付费墙**。
- **LME 实时价 / API 需机构注册**，只能用官网延迟收盘价 —— 且该行情页**只给最新一天**，
  问更早的日子它会如实回一句"该源不支持历史查询"，而不是拿最新价冒充那天的价。
- **SHFE 沪铜**是更即时的替代，但 `lme-price` 这个 server 名是题面定的，故铜主用 LME，SHFE 记入 ADR 作备选。
- **铁矿石**这一档标的是"知难而选的妥协项"：主流铁矿公司（BHP / Rio / Vale）走 20-F、不出具 NI 43-101，Fortescue 是例外。它和铜、锂**不是同等质量的数据**。

#### 为什么铁矿石不用 DCE 官网（实测，不是保守估计）

`www.dce.com.cn` 整站挂在一套 JS 挑战式 WAF（瑞数）后面：对 `urllib`、`curl`、
以及**真的 Chrome**（Playwright，`channel="chrome"`）一律返回 **HTTP 412** 加一段
挑战脚本。两次有界尝试后停手。

改用**新浪财经转载的 DCE 合约数据**，理由是它可交叉核对 —— 2026-10-08 同一天：

| | GFEX 官方（碳酸锂主力 2701） | 新浪（碳酸锂 `lc0`） |
|---|---|---|
| 收盘 | 117300 | 117300 |
| 结算 | 121540 | 121540 |
| 持仓量 | 409678 | 409678 |

两边逐项相同，说明解析层没有读错（该断言在 `tests/test_price_parsers.py`）。
报价单位两边都是**元/吨**；引用块里 `publisher` 记的是数据的**发布方**（新浪财经），
不是合约所属的交易所。

#### 为什么铜价要无头浏览器（实测）

LME 官网整站挂在 Cloudflare 后面：`httpx`、`urllib`、`curl` 直取**一律 403**，
带正常的浏览器 UA 也一样。只有**真实页面导航**能过 —— `https://www.lme.com/en/metals/non-ferrous/lme-copper`
用 Playwright 起真 Chrome 才拿到 200。所以铜是登记表里**唯一** `requires_browser=True`
的源，也是唯一走 `BrowserFetcher` 的路径。

两件事值得单独说：

1. **延迟 ≠ 回退。** 页面上写着 "3-month Closing Price **(day-delayed)**"，所以铜的
   `delayed` 恒为 `true` —— 那是**数据源固有**的披露延迟。而"回退"是 `as_of < requested_date`，
   是**我们**往前找了更早的一天。两者可以同时真、也可以一真一假，所以它们是两件事、
   两个字段，测试里**分别断言**（见 [ADR-0004](docs/adr/0004-price-adapter-falls-back-and-splits-dates.md)）。
2. **日期取自页面，不取自我们的时钟。** hero 数字本身不带日期，我们读的是页面自己的
   数据集日期选择器的上界（录播里是 `2026-10-05`，比"今天减一天"早三天）。替数据源
   断言一个它没说的日子，是本项目最贵的一类错；读不出日期时解析器**抛异常**，不给默认值。

跑真实抓取（`--live`）需要：`uv sync --all-extras`（装 playwright）+ 一个能起来的浏览器。
本机实测 playwright 自带的 chromium 没装、系统 Chrome 在，所以本仓库的配置是
`MINING_BROWSER_CHANNEL=chrome`；也可以改成 `uv run playwright install chromium` 后用自带的。
**缺浏览器时它响亮报错、绝不降级成"LME 无数据"** —— 静默降级会把我们的环境问题
写成数据源的结论，把排查引向一个根本没坏的网站。

#### 储量：为什么 Pilbara 用的是演示材料，而不是那份技术报告（实测）

题面举例的 Pilbara 锂矿（Pilgangoora），其 2017 年技术报告在 ASX 上的直链**已失效**
（实测 **404**），公司官网又整站在 Cloudflare 后面（实测 **403**）。**没有编一条链接**，
改用同一家公司公开可下载的 **CET 演讲材料**：它第 36 页原样印着 "Mineral Resource as at
30 June 2022" 的 JORC 分类表，且该页脚注（3.5 Mt Li₂O / 71 Mlb Ta₂O₅）与表内数字自洽、
第 6 页正文的一句概述又能与合计行对上 —— 三处互相印证，见 `tests/test_resources.py`
第 2 组。

**出身必须说清楚**：它是**公司自己的演讲材料转引年报**，不是独立技术报告。这一条写进了
登记表的 `title`，会随引用块一起进产物，读者一眼能看到自己拿到的是什么。

**表里的数字目前是"解析器的输出"，不是"已核实的事实"。** 每份冻结记录都带一个
`human_verified` 字段，在当前提交里**全部是 `false`** —— 在有人对着 PDF 逐行核过之前，
回放测试证明的是"解析器没有回归"，**不是**"这些数字对"（PRD §12 的 ground truth 纪律）。

### 术语声明

题面把 Indicated / Inferred 称作"储量"，这是笔误 —— 它们是**资源量（Resource）**，与 Proven / Probable 的**储量（Reserve）**是不同类别。本项目的处理：产出物节标题沿用题面的「储量数据」，但节内数据严格按真实类别标注。详见 [`CONTEXT.md`](CONTEXT.md)。

### 风险规则：只留能逐字引到权威原文的

**规则集被收窄过，收窄本身是这份交付的一部分。** 「风险信号」这个词只有在**每条规则的判据都是权威原文里的一句话**时才不作废，否则它会退化成"随便什么观察"。

- 规则集冻结在 [`docs/risk-rules.md`](docs/risk-rules.md)：4 条规则，`verbatim` 一律从 **JORC 2012**、**ASX Listing Rules Ch.5**、**NI 43-101（CSA Notice 版）** 三份权威文件里**逐字抄**来，不改写、不翻译；每份文件给了 URL + 字节数 + sha256，评审人可自行下载比对。
- **够不上逐字引的，降级为"提示"而不是信号**，并且必须写明"为什么它不是信号"。产物里这是**两个不同字段**（`RiskSignal` / `Hint`），不是同一列表里的两种语气。
- 三处如实记下的局限：`pypdf` 提取会吃掉 `ff`/`fi` 连字（引用时逐条核对过上下文）；GN31 那份没留档、**事后无从按哈希复验**，因此只作旁证、不作 `source_url`；PRD 说"ASX LR 5.16 的法定警示句"**是对的**，但"合资格人署名"那组要求其实在 5.22。

## 交付物

| 文件 | 内容 |
|---|---|
| [`RUN.md`](RUN.md) | 题面点名的 5 分钟通道：clone → `docker compose up` → 产物在哪 |
| [`Dockerfile`](Dockerfile) / [`docker-compose.yml`](docker-compose.yml) | 单服务、跑完即退、零凭证零网络的容器通道 |
| [`mcp-config.json`](mcp-config.json) | 把三个 server 挂进 Claude Desktop / Cursor（与题面同名放根目录） |
| [`CONTEXT.md`](CONTEXT.md) | 领域术语表，产出物与代码的用词一律以此为准 |
| [`docs/risk-rules.md`](docs/risk-rules.md) | 风险规则集的逐字原文、出处与哈希（工单 02 的取证记录） |
| [`docs/adr/`](docs/adr/) | 九条关键取舍的完整记录 |
| [`.env.example`](.env.example) | 全部环境变量与语义；**任何密钥只走环境变量**，`.env` 不入库 |

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
