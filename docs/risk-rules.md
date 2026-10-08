# 风险规则清单（原文级）

> 本文件是工单 02 的产出物，由工单 07 实现为触发逻辑。**规则集冻结在这里**；
> 07 号工单只实现、不增删。往规则集里加任何一条，都必须先在本文件里补上它的
> 逐字原文与可点开的出处 —— 这是"风险信号"这个词不被稀释成"随便什么观察"的
> 全部保障（PRD §5.2 硬规则 1、spec.md §风险提示的规则来源）。

## 0. 纪律

三条硬约束，缺一条这份清单就不作数：

1. **只用逐字原文。** 每条规则的 `verbatim` 一律是从下列三份权威文件里**抄**来的
   句子，不改写、不概括、不补标点、不翻译。中文只用于规则的**说明**，不用于 `verbatim`。
2. **出处必须能点开。** 每条给出 URL，并在 §1 给出该文件的 sha256 与字节数 ——
   评审人可以自己下一份、比哈希，确认我们读的是同一份文件。
3. **引不到就降级。** 够不上逐字引权威原文的观察，只能作为**提示**出现，并且必须
   写明"为什么它不是信号"。提示与信号在产物里是**两个字段**（`RiskSignal` /
   `Hint`），不是同一列表里的两种语气。

## 1. 三份权威文件（已实地取得，非转述）

三份都**下载到了本地并逐字提取**。下表可用于复验：URL 重新下载后 sha256 应当一致。

| 简称 | 文件 | URL | 字节数 | sha256 |
|---|---|---|---|---|
| JORC 2012 | Australasian Code for Reporting of Exploration Results, Mineral Resources and Ore Reserves, 2012 Edition | <https://www.jorc.org/docs/JORC_code_2012.pdf> | 1548341 | `48b4a257b4f997f1b9db1b493d5a7f7b2f08decd547b85e03761a6618b1187d6` |
| ASX LR Ch.5 | ASX Listing Rules, Chapter 5（在 ASX 官方咨询稿 `listing-rules-chapter-5-consolidated-consultation-response.pdf` 中的合并全文） | <https://www.asx.com.au/content/dam/asx/about/regulations/public-consultations/2021/listing-rules-chapter-5-consolidated-consultation-response.pdf> | 2046053 | `36945498b5155165ad1281f5839164746db0af34603ab6cd8dd9854dcd60590f` |
| ASX GN31 | ASX Listing Rules Guidance Note 31 — Reporting on Mining Activities | <https://www.asx.com.au/documents/rules/gn31_reporting_on_mining_activities.pdf> | 166253 | 见下"未记哈希"说明 |
| NI 43-101 | CSA Notice: Repeal and Replacement of National Instrument 43-101（含 Instrument 与 Companion Policy 全文） | <https://nssc.novascotia.ca/sites/default/files/docs/csanotice_43-101new08042011.pdf> | 914001 | `82cc29e680ac249fcc38b1a07b17b5cdf568b6ea171903aff1c5af9dea13f248` |

**哈希可复验（我自己复验过）**：上表三份均在 2026-10-09 于本机**重新下载**并比对，
字节数与 sha256 逐位一致（命令见 §7）。所以"出处可点开"不是承诺，是已验证的事实。

**取证方式与它的局限（必须一起读）：**

- PDF 文本是用 `pypdf` 提取的。**提取会丢字符**：JORC 那份把 `ff`/`fi` 连字吃掉过
  （出现 `E ective` = `Effective`），NI 43-101 的 Nova Scotia 另一副本则**整篇丢空格**
  （`Pursuantto`）—— 那一份因此被弃用，改用 CSA Notice 那份（它提取正常）。
- 本文件里的每条 `verbatim` 都是**逐字符核对过上下文**后才抄下来的；
  引文里不出现上述伪影。
- 引号在原文里是弯引号 `’`。本文件保留弯引号形态，不替换成直引号。

**未记哈希的一个例外**：GN31 是用 `curl -L` 抓下来的，当时未同时落盘留档，事后无
从按哈希复验。它的作用仅是**旁证**（确认 `5.16.4/.5/.6` 确实规定"临近且同等显著的
法定警示句"），而 `verbatim` 一律取自已记哈希的 ASX LR Ch.5 正文。**工单 07 不得
引用 GN31 作为 `source_url`。**

**PRD 措辞的一处精确化（不是改写）**：PRD/spec 写"ASX Listing Rule 5.16 的法定警告句"。
经核对，**这是对的** —— `5.16.4`、`5.16.5`、`5.16.6` 各自规定了警示句原文。同时补一句
PRD 未写明的：**"合资格人署名"那组要求不在 5.16，而在 5.22**（`5.16` 管的是
`production target`）。两者不要混引。

## 2. 规则集

五条。每条四项：**规则 / 触发条件 / 逐字原文 / 出处**。

> **触发条件的写法约定**：`applies(state)` / `triggered_by(state)` 是**纯函数**，只读
> `BriefState`（ADR-0006/0007）。而 `BriefState` 里**没有文章正文** —— 只有
> `news.items[*]`（`title` / `summary` / `source` / `published_at` / `category`）与
> `resources.table`。所以下面的触发条件**只写在这个可见面上**：写得再好、正文里
> 一眼可辨的条件，只要读不到正文就不算数，只能进 §4 的提示。这是本清单收窄的
> 真实原因，不是为了省事。

---

### R1 — 推断资源量不得与其他类别相加

**规则**：简报的储量一节若同时列出 Inferred 与（Indicated 或 Measured），必须点明
"推断资源量不得与其他类别相加"这条法定口径。这是媒体与营销材料最常犯的错
（把三类加起来当一个"总资源量"）。

**触发条件**

- `applies`：`state["resources"].table is not None` **且** `rows` 里同时存在
  `category == INFERRED` 与 `category ∈ {INDICATED, MEASURED}`；**且**
  `table.standard` 为 `NI_43_101`。
- `applies` 为假时该条不出现（储量节为空 → 不触发，符合"上游降级时该节留空是正常路径"）。
- `triggered_by`：形如 `"储量表含 Inferred 与 Indicated（NI 43-101，<report_title>）；两者不得相加"`。
- **为什么按 `standard` 分流**：这条的口径是 NI 43-101 的。JORC 体系下的对应物是
  Clause 12（见 R5），两者的"不得混用"是同一个意思但**不是同一句话**，混引会引错。
  分流同时也是工单 07 可断言的地方：给一张 `standard=NI_43_101` 的表 → R1 出现、
  R5 不出现；给一张 `standard=JORC` 的表 → 反之。

**逐字原文**（NI 43-101, Part 2, s. 2.2）

> An issuer must not disclose any information about a mineral resource or mineral reserve
> unless the disclosure (a) uses only the applicable mineral resource and mineral reserve
> categories set out in sections 1.2 and 1.3; (b) reports each category of mineral resources
> and mineral reserves separately, and states the extent, if any, to which mineral reserves
> are included in total mineral resources; (c) does not add inferred mineral resources to the
> other categories of mineral resources; and (d) states the grade or quality and the quantity
> for each category of the mineral resources and mineral reserves if the quantity of contained
> metal or mineral is included in the disclosure.

- 其中 `(c)` 是这条规则的核心句；`(b)` 是"分列"的依据。**两句都要引**，只引 `(c)`
  会让读者以为是禁止相加，而通读 `(b)(c)` 才知道要求是"分列 + 说明包含关系"。
- **出处**：<https://nssc.novascotia.ca/sites/default/files/docs/csanotice_43-101new08042011.pdf>（CSA Notice，2011-04-08，Instrument 正文 Part 2）

---

### R2 — 未分类的数量或品位不得披露

**规则**：新闻里出现一个**没有类别**的矿化数字（"品位 1.5% Li₂O"、"矿化 2000 万吨"
之类，而同句不含任何法定类别词），这是被明文禁止的披露形态。触发后应提示读者：
该数字缺少类别，按规则本不应在公开披露里单独出现，需回到一手公告核对。

**触发条件**

- `applies`：存在 `news.items[*]`，其 `title + summary` 的**同一句**内
  （以 `。！？；.!?;` 切句）同时满足：(i) 出现数量/品位形态（例如
  `\d+(\.\d+)?\s*(Mt|Mtpa|万吨|亿吨|吨|%|g/t)`）；**且** (ii) 该句**不含**任一法定
  类别词（`inferred` / `indicated` / `measured` / `proven` / `probable` /
  资源量 / 储量 / mineral resource / ore reserve，不区分大小写）。
- `triggered_by`：原样引出那一句（**不加工、不截断到失真**），并注明来源 `source` 与 `published_at`。
- **已知的误报面**：`g/t` 也会命中金矿化描述、`%` 会命中回收率/持股比例。这条宁可
  误报 —— 但误报的产物形态是"提示这一句缺类别"，读起来仍是正确的提醒。工单 07
  须把这条的误报行为用一条**否定用例**钉住（见下）。

**逐字原文**（NI 43-101, Part 2, s. 2.3(1) 的 (a)）

> (1) An issuer must not disclose
> (a) the quantity, grade, or metal or mineral content of a deposit that has not been
> categorized as an inferred mineral resource, an indicated mineral resource, a measured
> mineral resource, a probable mineral reserve, or a proven mineral reserve;

**出处**：同 R1。

---

### R3 — 经济分析含推断资源量时须带法定措辞

**规则**：新闻提到初步经济评估（PEA）时，法定措辞里的三个要素——"初步性质"、
"含推断资源量且其地质推测性过强因而不适用经济考量"、"不保证实现"——必须同现。
触发即提示读者核对一手公告是否带全这三句。

**触发条件**

- `applies`：存在 `news.items[*]`，其 `title + summary` 命中
  `\bPEA\b` / `preliminary economic assessment` / `初步经济评估` / `预可行性`
  （不区分大小写）。
- `triggered_by`：引出命中的那一句 + 来源。
- 触发频率预期**很低**（PEA 是阶段性事件）。这正是它有价值的原因：低频 + 高实质。

**逐字原文**（NI 43-101, Part 2, s. 2.3(3) 的 (a)）

> Despite paragraph (1)(b), an issuer may disclose the results of a preliminary economic
> assessment that includes or is based on inferred mineral resources if the disclosure
> (a) states with equal prominence that the preliminary economic assessment is preliminary in
> nature, that it includes inferred mineral resources that are considered too speculative
> geologically to have the economic considerations applied to them that would enable them to
> be categorized as mineral reserves, and there is no certainty that the preliminary economic
> assessment will be realized;

**出处**：同 R1。

---

### R4 — 生产目标须附临近且同等显著的法定警示句

**规则**：新闻提到产量目标（production target）时，须带 ASX 规定的警示句。触发即
提示读者：若该主体在 ASX 上市，一手公告里这句必须"临近且同等显著"——放在脚注或
别处的通用免责声明**不算数**。

**触发条件**

- `applies`：存在 `news.items[*]`，其 `title + summary` 命中
  `production target` / `产量目标` / `产出目标`（不区分大小写）。
- `triggered_by`：引出命中的那一句 + 来源 + （若可知）该主体是否为 ASX 上市主体。
- **限 ASX 主体**这一条在实现上要克制：`BriefState` 里没有"该新闻主体在哪上市"
  的结构化字段。工单 07 若无法从 `scope` 可靠判定，就**不要**假装判定了 ——
  直接在 `triggered_by` 里写明"若该主体在 ASX 上市"，把它作为**提醒**而非断言。
  这是本清单里唯一一条 `triggered_by` 带条件从句的规则，刻意如此。

**逐字原文**（ASX Listing Rule 5.16.4）

> There is a low level of geological confidence associated with inferred mineral resources
> and there is no certainty that further exploration work will result in the determination of
> indicated mineral resources or that the production target itself will be realised

- 原文在规则里是被引号包住的整句（句末无句点，在引号内）。这里的 `verbatim` 与
  规则文本**逐字一致**，未补句点。
- **同族但不同句**：`5.16.5`（基于勘探目标）与 `5.16.6`（**完全**基于推断资源量）各有
  各自的警示句，`5.16.6` 那句还多出"不应被投资者单独依赖"等两句。本清单**只冻结
  `5.16.4`**，因为"基于 proportion"这一档覆盖面最广；`5.16.5` / `5.16.6` 的原文已一并
  核对并存档，工单 07 若要细分，须先把那两条也补进本文件（而不是在代码里现抄）。

**出处**：ASX LR Chapter 5，规则 5.16.4（<https://www.asx.com.au/content/dam/asx/about/regulations/public-consultations/2021/listing-rules-chapter-5-consolidated-consultation-response.pdf>）

---

### R5 — 公开报告只能使用法定术语

**规则**：同一句话里把资源量类词与储量类词当同一件事用（最常见的形态：
把 `Inferred` / `Indicated` 说成 "reserve" / "储量"），违反 JORC 的术语强制。触发即
指出该句，并引原文。

**触发条件**

- `applies`：存在 `news.items[*]`，其 `title + summary` 的**同一句**内同时出现
  (i) 资源量类词（`inferred` / `indicated` / `measured` / `资源量`）与
  (ii) 储量类词（`ore reserve` / `proven` / `probable` / `reserve` / `储量`），
  且该句中资源量类词出现在储量类词**之前**（"Inferred ... reserve" 这个顺序才是
  混称；"reserve ... indicated" 常见于合规的对比表述）。
- `triggered_by`：原样引出那一句 + 来源。
- **这是本清单里唯一一条"负向"规则** —— 它报的是**信息源**的错，不是我们的。
  因此它在产物里的措辞必须说清是"来源如此表述"，不能让读者以为我们在指控某公司。
- 触发频率预期很低（真错才触发）。低频是它的优点：这一节一旦有内容，读者会认真读。
- `standard` 分流：这条引 JORC 原文。NI 43-101 体系下语义相同但不引这句
  （`s.2.2(a)` 是它的加拿大对应物，见 R1 的引文）。

**逐字原文**（JORC 2012, Clause 12）

> Public Reports dealing with Exploration Results, Mineral Resources or Ore Reserves must
> only use the terms set out in Figure 1.

- 这句短、边界清楚，是"术语强制"的**唯一**成文依据，不需要旁的句子陪衬。
- **配套要读的概念**（不引用，只作实现说明）：Figure 1 画的是 Exploration Results /
  Mineral Resources / Ore Reserves 三档的包含关系，`Inferred` 属中间档，**不是**储量。

**出处**：<https://www.jorc.org/docs/JORC_code_2012.pdf>（JORC Code 2012 Edition, Reporting Terminology）

## 3. 每座矿山的触发预期

> **前提必须先说清**：PRD §8 规划了 8 座矿山，而**`config/archive.py` 目前只有一条**
> （Pilgangoora / Pilbara Minerals / lithium / JORC）。因此下表的右四列在本仓库当前
> 状态下**无法被端到端观测** —— 工单 07 写 S1 用例时只能用 Pilgangoora 这一行走
> JORC 路径（R5），NI 路径要用**单元用例**（构造一张 `standard=NI_43_101` 的表）来断言。
> 这一点已写进交接报告的"需要人做的事"。
>
> 下表的"可能/不可能"是**结构性推断**（由该矿的**报告体系**与公开披露形态推出），
> **不是**我们对这 8 座矿的一手核实数据。请勿把它当成事实引用。

| 矿山（PRD §8） | 矿种 | 报告体系 | R1（NI，表内 Inferred+Indicated） | R2（未分类数字） | R3（PEA） | R4（生产目标） | R5（术语混称） |
|---|---|---|---|---|---|---|---|
| Grota do Cirilo（Sigma Lithium） | 锂 | NI 43-101 | 可能（有 Inferred 与 Indicated 并存） | 可能 | 可能 | 不适用（非 ASX 主体） | 引 JORC 原文**不适用**；见下 |
| Shaakichiuwaanaan（PMET） | 锂 | NI 43-101 | 可能 | 可能 | 可能 | 可能（TSX/ASX 双重上市） | 不适用 |
| **Pilgangoora（Pilbara Minerals）** | 锂 | **JORC** | 不适用（非 NI 体系） | 可能 | 可能 | 可能（ASX: PLS） | **可能，且这是当前唯一可端到端断言的路径** |
| Kamoa-Kakula（Ivanhoe） | 铜 | NI 43-101 | 可能 | 可能 | 可能 | 不适用（非 ASX 主体） | 不适用 |
| Mantoverde（Capstone） | 铜 | NI 43-101 | 可能 | 可能 | 可能 | 不适用 | 不适用 |
| Copper World（Hudbay） | 铜 | NI 43-101 | 可能 | 可能 | 可能 | 不适用 | 不适用 |
| Bloom Lake（Champion Iron） | 铁矿石 | NI 43-101 | 可能 | 可能 | 可能 | 可能（ASX/TSX 双重上市） | 不适用 |
| Chichester + Western Hub（Fortescue） | 铁矿石 | JORC（年报形态） | 不适用 | 可能 | 可能 | 可能（ASX: FMG） | 可能 |

**读表须知**

- "可能"= 该规则**结构上有机会**触发，取决于当天的新闻内容；**不是**"一定会触发"。
- "不适用"= 该规则的**权威来源**与这座矿的报告体系不对应（NI 规则不引 JORC 矿、
  JORC 规则不引 NI 矿），因此这条规则不应由该矿的数据触发。
- R2 / R3 / R4 与报告体系无关（它们看的是**新闻文本**而非储量表），所以在所有行都是"可能"。
- **没有任何一行是"一定触发"** —— 这一节在第 7 号工单实现后，**默认产物是"本次未触发"**。
  这是预期行为，不是失败：触发需要当天新闻恰好命中，而命中是低频的。

## 4. 降级为「提示」的观察（`Hint`，不进风险信号）

以下观察**看着像风险**，也确实值得提一句，但够不上"逐字引权威原文"，因此只能进
`Hint`，且必须写明 `why_not_a_signal`。

| 观察 | 为什么不是信号 |
|---|---|
| 资源量/储量类新闻**没有**具名合资格人（Competent/Qualified Person） | 我们手上的 `news.items[*]` 只有 RSS 的 `summary`，**天然不载署名**。按这条判定，几乎每条资源类新闻都会命中 —— 那不是信号，是噪声。要真判定必须读一手公告全文，而 `BriefState` 里没有正文（文章页只有 `ArticleLookup` 这条独立工具路径，不进图）。**升级条件**：若将来把文章正文并入 `BriefState`，这条可提升为信号，届时引 JORC Clause 9 / ASX LR 5.22 / NI 43-101 s.2.1。 |
| 某公司**未按期发布**年度资源量更新 | 引不到"必须每年更新"的逐字条款（JORC Clause 15 涉及年报披露，但其义务主体与触发时点与我们的"日报"形态不同）。**不引。** |
| 项目**延期**、**暂停**、**许可被拒** | 属于经营事件，没有任何披露规则规定这类事件必须带何种措辞。无原文可引。 |
| 矿产品**价格大幅波动** | 价格本身不是披露合规问题。价格节已经用事实呈现（含 `delayed` / 回退标注），不需要再包一层"风险"话术。 |
| 高管**离职**、董事会**变动** | 无对应披露措辞要求可引。 |

**提示与信号在产物里必须是两处**（工单 07 的验收第 3 条）：`RiskSignal` 有 `verbatim`
与 `source_url`，`Hint` 只有 `text` 与 `why_not_a_signal`。**提示不得出现在"风险信号"里**，
产物里两个词也不得混用。

## 5. 因引不到原文而被排除的观察

与 §4 的区别：§4 是"够得上提一句但不够当信号"，这里是**整条不做**，并记原因。

| 被排除的观察 | 排除原因 |
|---|---|
| "储量**下调**了" | 减少本身不违规。真正相关的是"重大变化须重新披露"（NI 43-101 s.2.2 的 `materially changed` 表述在 ASX LR 5.8 里出现），但那是**披露时点**义务，且需要把"上一次披露的数"和"这一次的数"都拿到才能判定 —— 我们的日报只看到当天窗口，看不到上一次。**无原文 + 无数据，两条都不满足。** |
| "**品位低**所以项目不经济" | 经济性是合资格人的判断，不是文本可判定的事实。引不到任何"品位低于 X 即须警示"的条款（不存在这样的条款）。**这是典型的"看着像洞察，其实是编"。** |
| "该矿**位于**某风险司法辖区" | 无披露规则要求按辖区打风险分。若要做，必须自带一份权威的辖区评级来源——本项目没有，也不该现造。 |
| "新闻里**没有**提到环保/社区" | 否定式判断，且无"必须提及"的逐字依据。 |
| "矿权**到期日**临近" | 需要结构化的权证数据（我们只有新闻与价格），且找不到"到期前 N 天须警示"的条款。 |

**一句话总结这条纪律**：一条规则要么能引到原文、要么就明说"这一条我做不了"。
**凑数的规则比没有规则更糟** —— 它会让整个"风险信号"字段失去可信度。

## 6. 与 PRD / spec 的出入

- **无实质冲突。** PRD §9 已预告"规则集将收窄至能逐字引到原文的条目"，本清单正是
  那次收窄的结果：5 条信号 + 5 条提示，其余整条排除（§4、§5）。
- **一处精确化**（见 §1 末）：`5.16` 确实规定警示句（PRD 措辞成立），但"合资格人署名"
  在 `5.22`。PRD 未写明这一点，本文件补上。
- **一处新增的依赖**：R1/R3 的口径是 NI 43-101、R5 的是 JORC，因此规则集**依赖矿山
  的 `reporting standard`**。这要求 `ResourceTable.standard` 在实现里是可靠的
  （当前它由 `config/archive.py` 的档案条目决定）。若将来换矿而标准标错，规则会引错
  法条。

## 7. 怎么自己再验一遍

```bash
# 1. 取三份权威文件（哈希应与 §1 一致）
curl -L -o jorc2012.pdf        https://www.jorc.org/docs/JORC_code_2012.pdf
curl -L -o ch5.pdf             "https://www.asx.com.au/content/dam/asx/about/regulations/public-consultations/2021/listing-rules-chapter-5-consolidated-consultation-response.pdf"
curl -L -o ni43101-csa.pdf     https://nssc.novascotia.ca/sites/default/files/docs/csanotice_43-101new08042011.pdf
sha256sum jorc2012.pdf ch5.pdf ni43101-csa.pdf

# 2. 提取文本（NI 那份需要 cryptography 解 AES；JORC / ASX 不需要）
uv run --with pypdf --with cryptography python -c "
from pypdf import PdfReader
import sys
for src, dst in [('jorc2012.pdf','jorc.txt'), ('ch5.pdf','ch5.txt'), ('ni43101-csa.pdf','ni.txt')]:
    r = PdfReader(src)
    open(dst,'w',encoding='utf-8').write('\n'.join(p.extract_text() or '' for p in r.pages))
    print(dst, len(r.pages))
"

# 3. 逐条核对本文件的 verbatim
grep -n "must only use the terms set out in Figure 1"                          jorc.txt
grep -n "does not add inferred mineral resources to the other categories"      ni.txt
grep -n "too speculative geologically"                                          ni.txt
grep -n "low level of geological confidence associated with inferred mineral"   ch5.txt
```

**已知的提取伪影**：JORC 那份会吃掉 `ff`/`fi` 连字（`E ective`），ASX 那份会在词中插入
多余空格（`ta rget`、`res ult`）。核对时请按"字母序列一致"比对，不要按"含空白字符的
完全相等"比对 —— 本文件的 verbatim 已经去过这些伪影，本体用词未动。

---

*本文件冻结于工单 02。工单 07 只实现、不增删规则。*
