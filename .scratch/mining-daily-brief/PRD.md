# PRD — 矿权日报 Agent

| | |
|---|---|
| 版本 | v1 · 2026-10-08 |
| 对应题面 | `面试题目.docx` 题 #2（MCP 协议 · 矿权日报 Agent） |
| 状态 | 需求已冻结，待实现 |

---

## 1. 一句话定义

输入一句自然语言，输出一份**每个事实都能回溯到原始来源**的 Markdown 矿权日报。

---

## 2. 目标与非目标

### 2.1 目标

| | 目标 | 怎么算达成 |
|---|---|---|
| G1 | 跑通题面示例句"给我生成一份关于 Pilbara 锂矿的今日简报" | 端到端用例断言通过 |
| G2 | 3 个 MCP server 各自可独立调用、独立测试 | 每个 server 有工具级单测 |
| G3 | 所有事实可回溯 | 简报里每个 `[n]` 都能落到真实工具返回值 |
| G4 | 默认离线可复现，`--live` 走真实网络 | `pytest` 默认不联网全绿 |

### 2.2 非目标（本轮明确不做）

| | 不做 | 理由 |
|---|---|---|
| N1 | 预测、估值、投资建议 | 无数据支撑，且题面要的是"日报" |
| N2 | 自由问答 | 单一意图；开放问答会退化成聊天机器人（见 §4.2） |
| N3 | 矿权登记簿级别的权威数据 | 没有公开免费源，硬接就是编 |
| N4 | 全市场覆盖 | 档案 8 个矿山；超出即明确拒答，不幻觉 |

---

## 3. 用户与使用场景

公司内部使用者（矿业 / 投资方向，非技术背景）。

场景：每天早上说一句话，拿到一份能直接读、能点开溯源、**缺什么也明说**的简报。

---

## 4. 输入契约

### 4.1 参数槽位

一句话进系统后，只被用来抽三个槽位：

```
{ commodity?: "lithium" | "copper" | "iron_ore"
  mine?:      "<档案条目 id>"
  window_days?: int }
```

- **抽取方式**：LLM 做封闭分类（把话语映射到槽位），**不生成实体**。
- **缺省**：`window_days` = 7；`commodity` / `mine` 未指定 → 覆盖档案全部（按品种分节）。
- **实体解析**：用户口中的矿山名（中文别称、英文名、代码）→ 档案条目。**匹配不上就记为"未覆盖"，绝不编造。**

### 4.2 拒答规则

| 情形 | 行为 |
|---|---|
| 意图不是"出简报"（如"预测明年锂价"） | 拒答，**回显听懂的部分** + 列出可用句式 |
| 矿山 / 品种不在档案 | 明确说"未覆盖"，并列出档案内可选项 |
| 参数无法解析 | 降级为缺省值，并在"数据完整性"节记一笔 |

拒答文案必须可断言。示例：

> "预测明年锂价"超出本系统能力——本系统不做预测，只汇总已发生的数据。
> 支持的句式例如：`出份锂的日报`、`看看 Pilbara 最近 7 天`

---

## 5. 输出契约

### 5.1 章节结构

题面要求的 4 节 + 引用源链接是**硬性**；ⓐ 标记的两节是本项目**额外增加**的，不替代任何题面要求。

| # | 章节 | 来源 |
|---|---|---|
| 1 | 矿权动态 | ⓐ 增补（题面标题是"矿权日报"，但没给对应数据源） |
| 2 | 新闻摘要 | 题面要求 |
| 3 | 储量数据 | 题面要求 |
| 4 | 价格走势 | 题面要求 |
| 5 | 风险提示 | 题面要求 |
| 6 | 数据完整性 | ⓐ 增补（本次覆盖了什么、缺了什么、为什么缺） |
| — | 引用源链接 | 题面要求 |

### 5.2 三条硬规则

1. **逐字引用**：URL / 标题 / 时间戳必须从工具返回值**原样**进入引用块。模型**不得**转述后再补链接。
2. **引用可验证**：每个事实标 `[n]`，`[n]` 必须能在来源清单里找到对应条目。由代码校验，不通过即报错。
3. **时间分层**：每节标题旁标该节数据的截止时间。抬头写明"各节数据截止时间不同"——因为 LME 只有延迟价、GFEX 有当日价、储量报告可能是几年前的，这是数据的真实形态，不掩饰。

### 5.3 落盘

写到 `out/<日期>-<scope>.md`，**并把路径打到 stdout**（不往 stdout 吐全文——那样文件就没法被测试断言了）。

---

## 6. 架构

### 6.1 三个 MCP server（签名照题面，不自创）

#### `mining-news-mcp`

| 工具 | 签名 | 返回 |
|---|---|---|
| `search` | `search(query: str, days: int) -> NewsItem[]` | 见下 |
| `fetch_article` | `fetch_article(url: str) -> Article` | 全文 |

```python
NewsItem = { title, url, source, published_at, summary, category }
# category: "mining_rights" | "general"  ← 关键词规则分流，不是模型判断
Article  = { url, title, source, published_at, text }
```

#### `mineral-pdf-mcp`

| 工具 | 签名 | 返回 |
|---|---|---|
| `extract_resources` | `extract_resources(pdf_url: str) -> ResourceTable` | 见下 |

```python
ResourceTable = {
  pdf_url, report_title, report_date,
  standard,      # "NI 43-101" | "JORC"
  project, commodity,
  rows: [ { category,      # Measured|Indicated|Inferred|Proven|Probable
            tonnage_mt, grade, grade_unit, contained } ],
  page_refs,     # 每个数字来自 PDF 第几页
}
```

> **注**：题面写的是抽 "NI 43-101" 储量，但题面举例的 Pilbara 走 JORC。JORC 2012 与 NI 43-101 **共用 Measured/Indicated/Inferred 分类词**，因此解析器统一处理两套体系，并在返回值里标明 `standard`。

#### `lme-price-mcp`

| 工具 | 签名 | 返回 |
|---|---|---|
| `get_price` | `get_price(commodity: str, date: str) -> PricePoint \| NotFound` | 见下 |
| `get_trend` | `get_trend(commodity: str, days: int) -> PricePoint[]` | 序列 |

```python
PricePoint = {
  commodity, exchange, symbol,      # 三所 adapter：LME / GFEX / DCE
  value, currency, unit,
  as_of,                            # ISO8601
  delayed: bool,                    # LME 为 true（延迟一日收盘）
  source_url,
}
```

### 6.2 Agent 编排（LangGraph）

```
                    ┌─ fetch_news ──────┐
parse_intent → resolve_entities → check_scope ─┼─ fetch_prices ─────┼→ compute_signals → assemble → narrate → verify_citations → render
                    └─ fetch_resources ─┘
                                    │
                              (不在覆盖内 → 拒答 → END)
```

| # | 节点 | 谁在决策 | 干什么 | 失败时 |
|---|---|---|---|---|
| 1 | `parse_intent` | **LLM** | 一句话 → 三个槽位 | 降级为缺省值 |
| 2 | `resolve_entities` | **LLM + 档案** | 矿名 → 档案条目；对不上记"未覆盖" | 同上 |
| 3 | `check_scope` | 纯函数 | 不在覆盖内 → 拒答 → END | — |
| 4a | `fetch_news` | MCP 工具 | 窗口内新闻 + 关键词分流 | 记 `coverage_gaps`，简报继续 |
| 4b | `fetch_prices` | MCP 工具 | 三所 adapter | 同上 |
| 4c | `fetch_resources` | MCP 工具 | PDF 储量表 | 同上 |
| 5 | `compute_signals` | 纯函数 | 规则引擎 → 风险信号（带证据引用） | 记错，该节留空 |
| 6 | `assemble` | 纯函数 | 搭六节骨架，**逐字引用块由代码塞入** | — |
| 7 | `narrate` | **LLM** | 只写每节一句导读；输入是已冻结数据 | 降级为不写导读 |
| 8 | `verify_citations` | 纯函数 | `[n]` 必须指回真实工具返回值 | 不通过 → 报错 |
| 9 | `render` | 纯函数 | 写文件 + 打印路径 | — |

**三个关键形状：**

1. **4a / 4b / 4c 并行**（LangGraph superstep）。它们互不依赖，且各自需要独立的超时、重试、失败降级。**这是"为什么用图而不是顺序脚本"的全部答案。**
2. **模型只出现在 1、2、7**，其中 7 的输出还被 8 卡着。其余全是纯函数。
3. **任一 fetch 挂掉，简报照样出**——那一节标"数据缺失"并计入第 6 节。**失败路径是一等公民，不是 try/except 兜底。**

### 6.3 每个节点的准入纪律

> 每个节点都必须回答：**"为什么它必须是一个节点，而不是上一行的一行代码？"**

答不上来的就不是节点。

### 6.4 为什么用 MCP，而不是直接写函数调用（面试必问）

我们的图直接调 MCP 工具，**LLM 不做工具选择**。这看起来像"把 MCP 当 RPC 用"，答案是三条：

1. **工具契约独立可测**：每个 server 有自己的 schema 和单测，与业务逻辑解耦。
2. **同一批 server 零改动挂进 Claude Desktop / Cursor**——这是能**当场演示**的收益，也是题面明确要求的交付项（`mcp-config.json`）。
3. **传输层与业务解耦**：stdio 换 SSE 不用动业务代码。

而"LLM 不做工具选择"本身是**设计主张**，不是缺陷：日报的数据采集是固定流程，把工具选择交给模型只会引入不确定性。

---

## 7. 数据源与取舍（如实声明）

| 数据 | 采用的源 | 状态 |
|---|---|---|
| 新闻 | mining.com RSS、公司官网 | 直取（需浏览器 UA） |
| 铜价 | LME 官网 | **可抓，但只有延迟一日收盘价**（Cloudflare，须真实页面导航） |
| 锂价 | GFEX 广期所碳酸锂 | 直取 |
| 铁矿石价 | DCE 大商所铁矿石 | 直取 |
| 储量 | 各公司公开技术报告 PDF | 直取 |

**得不到的，在 README 里写明，不装：**

- **Platts IODEX / Mysteel / SMM / Fastmarkets**（铁矿石与锂的行业标准价）**全部付费墙**。
- **LME 实时/API 需机构注册**，我们只能用官网延迟收盘价。
- SHFE 沪铜是更即时的替代，但 `lme-price` 这个 server 名是题面定的，故铜主用 LME、SHFE 记入 ADR 作备选。

---

## 8. 矿权档案

**8 个矿山 / 3 个矿种**（题面示例的 Pilbara 必须在列）

| 矿种 | 公司 | 项目 | 报告体系 |
|---|---|---|---|
| 锂 | Sigma Lithium (NASDAQ: SGML) | Grota do Cirilo | NI 43-101 |
| 锂 | PMET Resources (TSX/ASX: PMET) | Shaakichiuwaanaan | NI 43-101 |
| 锂 | **Pilbara Minerals / PLS (ASX: PLS)** | **Pilgangoora** | **JORC**（题面示例） |
| 铜 | Ivanhoe Mines (TSX: IVN) | Kamoa-Kakula | NI 43-101 |
| 铜 | Capstone Copper (TSX: CS) | Mantoverde | NI 43-101 |
| 铜 | Hudbay Minerals (TSX/NYSE: HBM) | Copper World | NI 43-101 |
| 铁矿石 | Champion Iron (ASX/TSX: CIA) | Bloom Lake | NI 43-101 |
| 铁矿石 | Fortescue (ASX: FMG) | Chichester + Western Hub | JORC（形态为年报，非独立 TR） |

每条档案含：`id / 公司 / 项目 / 矿种 / 交易所代码 / 中文别称 / 技术报告 URL / 报告日期`。

**备选**：Lithium Americas — Thacker Pass（其在 EDGAR 上的技术报告形态是 HTML exhibit 而非独立 PDF，混入会让解析层多一条分支，暂不纳入）。

**已知取舍（面试可讲）**：铁矿石正规 NI 43-101 标的极少——主流铁矿公司（BHP / Rio / Vale）走 20-F，不出具 NI 43-101；Fortescue 是"知难而选"的妥协项。

---

## 9. 风险提示（规则驱动）

**约束（硬）**：规则必须来自**权威公开内容**，不得自行编造。

**当前状态**：⚠️ 未完成。已收集的素材只到"摘要级"引用，不足以支撑逐字引用。**规则集将收窄**至能逐字引到原文的条目（JORC 2012 / NI 43-101 的法定披露要求、ASX Listing Rule 5.16 的法定警告句），其余降级为"提示"，不进入"风险信号"。

**待办**：完成规则条的原文级引用核对后，本节补齐为 R1–Rn 清单，每条含 `规则 / 触发条件 / 引用的权威原文 / 出处 URL`。

---

## 10. 双模式与录播

| 模式 | 触发 | 数据来源 | 用途 |
|---|---|---|---|
| 默认（回放） | 无参数 | fixture | 确定性测试、CI |
| 实时 | `--live` | 真实网络 | 证明真能抓 |

- **数据层录播**：fixture 含**抓取时间戳**，每源 **30 天**跨度。
- **LLM 层录播**：`parse_intent` / `resolve_entities` / `narrate` 的响应也录制，保证离线确定性。
- **fixture 不提交 PDF 二进制**（合计约 130 MB，且属受版权保护的公司文件）。仓库只存：抽好的 JSON + `sources.json`（URL / SHA256 / 抓取时间）+ 一键抓取脚本。

---

## 11. 工程化映射

| CLAUDE.md 要求 | 落实 |
|---|---|
| 一键可运行 | `docker compose up` 单条命令；README 写清安装/运行/测试三条命令 |
| 依赖显式锁定 | `pyproject.toml` + lock 文件 |
| 分层结构 | `servers/`（MCP）/ `agent/`（编排）/ `datasources/`（抓取）/ `config/` |
| 测试 | 每个 server 工具级单测 + 端到端 golden case |
| 配置外置 | `.env.example`；密钥不入库 |
| 错误处理与日志 | 统一异常 + 结构化日志；**禁裸 `print`** |
| Lint / 类型 | Ruff + Black + mypy（mypy 同时充当 server 返回契约的书面化） |
| CI | GitHub Actions 跑 lint + test，README 挂 badge |
| 容器 | `Dockerfile` 默认 slim；**浏览器进可选 extra**（LME 需要），缺浏览器时明确报错不静默降级 |
| ADR | `docs/adr/`，把本次需求的每个取舍落成文 |

---

## 12. 验收标准（补题面缺失的量化指标）

题面的交付清单全是文件名，**没有任何可验证的指标**。以下为本项目自设的验收断言：

| 编号 | 断言 |
|---|---|
| A1 | 题面示例句"给我生成一份关于 Pilbara 锂矿的今日简报"能端到端产出完整简报 |
| A2 | 3 个 server 的每个工具各有单测，`pytest` 默认离线全绿 |
| A3 | 简报中每个 `[n]` 都能在来源清单里找到对应条目（`verify_citations` 通过率 100%） |
| A4 | 引用块内的 URL / 标题 / 时间戳与工具返回值**逐字符相同** |
| A5 | 给定一条 fixture 新闻，`category` 分流结果符合预期（矿权 vs 普通） |
| A6 | 给定固定 PDF，`extract_resources` 输出与冻结的 ground truth 完全一致 |
| A7 | 任一 fetch 源人为故障时，简报仍产出，且第 6 节列出该缺失 |
| A8 | 越界请求（如"预测明年锂价"）返回拒答文案，且文案含可用句式示例 |
| A9 | 未覆盖矿山被明确拒绝，**不产生任何实体幻觉** |

> **ground truth 的来源纪律**：A6 的冻结值必须由**真实下载的 PDF 跑解析器后人工核对**得出，**不得**引用二手摘要数字——否则测试就是自证。

---

## 13. 已知缺口与风险

| | 缺口 | 影响 | 处置 |
|---|---|---|---|
| R1 | 风险规则的原文级引用未完成 | §9 无法冻结 | 实现前专门做一轮，规则集宁窄勿编 |
| R2 | Pilbara 的 JORC PDF 直链待验证 | A1 依赖 | 验证进行中。**已决定：若拿不到直链就暂停该项、不再阻塞流程**，届时降级为该矿山"数据缺失"，由第 6 节如实记录 |
| R3 | LLM 层录播需真实调用一次 DeepSeek | 离线确定性 | 首次实现时录制，之后回放 |
| R4 | 完整 PDF 不入库 → 解析器无法离线验证 | 测试覆盖 | 单列 `@pytest.mark.network` 用例做真下载真解析 |
