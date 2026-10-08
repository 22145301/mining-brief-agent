# 05: 储量 · PDF server 与资源量抽取

**What to build:** "储量数据"一节能抽出一张资源量表——每个数字标类别（Measured / Indicated / Inferred / Proven / Probable）、标报告体系（NI 43-101 还是 JORC）、能追到 PDF 第几页。

这是三个源里最后一个被填上的，因此**跨源故障隔离的完整验证也落在这里**：三个源都在位之后，才谈得上"任一源挂掉，简报照样出"。

**Blocked by:** 01

**Status:** needs-human

**Category:** enhancement

- [x] `extract_resources` 返回资源量表：项目、品种、报告体系、报告标题、报告日期、行（类别 / 吨位 / 品位 / 品位单位 / 含金属量）、页码引用
- [x] JORC 与 NI 43-101 两套体系走**同一条**解析路径，只在返回值里标明体系（两者共用 Measured / Indicated / Inferred 分类词）
- [ ] **⛔ 人工核对卡点（agent 独自做不完，需使用者在场）**：冻结的 ground truth 必须由**真实下载的 PDF 跑解析器后人工核对**得出，**不得引用二手摘要数字**——否则测试就是自证
      —— 已做到"真下载 + 真解析 + 整理成待核清单"（见下），**核对本身没有做**：`human_verified` 仍是 `false`。这一格按约定留 `[ ]`。
- [x] 回放模式比冻结值；`network` 标记的用例真下载真解析（完整 PDF 不入库：约 130 MB 且受版权保护，仓库只存抽好的 JSON）
- [x] **R2 处置落实**：若 Pilbara 的 JORC 直链拿不到，该矿山降级为"数据缺失"由第六节如实记录，**不阻塞本票收尾**
      —— 直链确实拿不到（404 + 403，见下），但**没有降级成"数据缺失"**：改用同公司公开的 CET 材料。偏离了本格的**字面**处置，理由是那个处置的前提是"没有可用的公开文件"，而实测有。
- [x] 本源的故障 fixture 就位
- [x] **A7 完整验证**：三个源（新闻 / 价格 / 储量）全部在位后，人为让任一源故障，断言简报仍产出且第六节列出该缺失
- [x] 日报"储量数据"一节有真实数据；节内严格区分**资源量**与**储量**，不混用（题面把 Indicated / Inferred 称作"储量"是笔误，节标题沿用题面措辞但节内按真实类别标注）

## 实现记录

### 交付了什么

| 文件 | 内容 |
|---|---|
| `mining_brief/config/reports.py` | **新增**：报告登记表（`ReportSource` / `ReportColumn`）—— 两份报告的列序、单位、量纲换算、表头标记、页码提示；`source_by_pdf_url` |
| `mining_brief/datasources/resources.py` | **新增**：三层结构（PDF 字节 → 逐页文本 `pages_from_pdf_bytes`；逐页文本 → `ResourceTable` 的**纯函数** `parse_resource_table`；adapter 只编排）；`FrozenResourceSource` / `LiveResourceSource` / `build_resource_source`；`PdfSupportMissing(LoudFailure)`；`FrozenExtractMissing(ReplayMiss)` |
| `mining_brief/servers/runtime.py` | `resources()` 接上 `ResourceAdapter`，冻结目录 `fixture_root / "resources"` |
| `mining_brief/config/archive.py` | Pilgangoora 的 `report_url` 指向 CET 材料；R2 的处置理由写在字段旁 |
| `scripts/extract_resources.py` | **新增**：下载 → 抽文本 → 解析 → 冻结成 JSON（含页原文），**永不**替人翻 `human_verified` |
| `fixtures/resources/*.json` | **新增**：两份冻结抽取结果（3383 B / 3794 B） |
| `tests/test_resources.py` | **新增**：28 例，四组（解析器 / 交叉核对 / 冻结纪律 / 故障路径）+ 2 例 `network` |
| `tests/conftest.py` | 加 `fault_url` 夹具：按**状态**（503）而不是按顺序取故障样本 |
| `tests/test_e2e_slice.py` | 储量节从"缺得明明白白"改成"接上了、数字带出处"；A7 的三条参数化用例不再需要临时补直链 |
| `tests/test_price_tool.py` | 用共享的 `fault_url`，删掉原来那个按顺序取的局部助手 |
| `README.md` / `mineral_pdf_server.py` | 数据源表改"已接入"；新增"为什么 Pilbara 用的是演示材料"小节；工具 docstring 写清"这是解析器的输出"这条纪律 |

### 实测：两份报告都真下载、真解析（非示意）

```bash
uv run pytest -m network -p no:cacheprovider -v
```
```
tests/test_resources.py::test_the_real_pdf_still_parses_to_the_frozen_table[pilgangoora-cet-2022] PASSED [ 50%]
tests/test_resources.py::test_the_real_pdf_still_parses_to_the_frozen_table[pmet-shaakichiuwaanaan-2025] PASSED [100%]
=============== 2 passed, 147 deselected, 4 warnings in 19.61s ===============
```

这条用例真的下载（状态 200 + `%PDF` 魔数）、核对 **sha256 与冻结记录逐字符相同**、再用同一次下载的字节重跑解析器断言与冻结表**逐字段相等**。

冻结记录读回（可重跑）：

```bash
uv run python -c "..."   # 见下文清单里的完整命令
```
```
pilgangoora-cet-2022.json: 9747460B/44页 sha256=84ababf60f74… 表在第36页 human_verified=False
    Measured 19.0Mt@1.4%->0.3；Indicated 187.0Mt@1.2%->2.2；Inferred 99.0Mt@1.1%->1.0
pmet-shaakichiuwaanaan-2025.json: 5714740B/48页 sha256=ffc6ca4351b9… 表在第41页 human_verified=False
    Indicated 107.991Mt@1.4%->3.75；Inferred 33.38Mt@1.33%->1.09
```

### ⛔ 待人工核对清单（这一格没有被跳过，只是没被人做过）

**要核的东西**：上面那 5 行数字，对着这两份 PDF 逐行看。开工前先读
`fixtures/resources/*.json` 的注释字段 —— 它们各自记着自己是从哪份文件、哪一页读出来的。

| # | 文件 / 页 | 类别 | 吨位 | 品位 | 含金属量 | 页上应该同时能看到 |
|---|---|---|---|---|---|---|
| 1 | `Talk-6-Holmes_Pilgangoora-Exploration-Geology.pdf` **第 36 页** | Measured | 19 Mt | 1.4 % Li₂O | 0.3 Mt Li₂O | 合计行 `Total 305 1.1 105 0.6 3.5 71` |
| 2 | 同上 | Indicated | 187 Mt | 1.2 % Li₂O | 2.2 Mt Li₂O | 同上 |
| 3 | 同上 | Inferred | 99 Mt | 1.1 % Li₂O | 1.0 Mt Li₂O | 同上 |
| 4 | `PMET_Site_Visit_September_2026_Final_to_lodge-1.pdf` **第 41 页** | Indicated | 107.991 Mt | 1.4 % Li₂O | 3.75 Mt LCE | `Effective Date of the MREs is June 20, 2025`；`Mineral Resources are not Mineral Reserves` |
| 5 | 同上 | Inferred | 33.38 Mt | 1.33 % Li₂O | 1.09 Mt LCE | 同上 |

**另需人拍板的三件事**（都不是"数字对不对"，是"我们这样解读对不对"）：

1. **两份报告的 PDF 都没入库**（ADR-0001，体积 + 版权）。核对时请自己按 `pdf_url` 下载；
   `pdf_sha256` 是给这件事用的 —— 你下到的那份如果不是这个哈希，说明源站换过文件。
2. **`report_date` 是人从页面上抄的**，解析器不读它：CET 的 `2022-06-30` 来自表头那句
   `Mineral Resource as at 30 June 2022`；PMET 的 `2025-06-20` 来自第 41 页那句
   `Effective Date of the MREs is June 20, 2025`。**核对时请确认这两个日期确实是"资源量生效日"**
   —— 它们会作为引用块的时间戳进产物，抄错了就是一个看起来很正常的错日期。
3. **产物上的储量数字目前不携带"是否已核对"这一位**（`human_verified` 只在冻结文件里，
   `ResourceExtract` 信封上没有它）。要不要把它提到产物上（让日报自己写出"这批数字未经人工
   核对"）是一个**设计决定**，我没有替你做 —— 见下「判定五」。

核对完之后要做的事：把 `fixtures/resources/*.json` 里
`human_verified` 改成 `true`，填 `human_verified_by` / `human_verified_at`。
`tests/test_resources.py::test_the_frozen_extract_says_it_is_not_human_verified_yet`
**会因为这个改动而红** —— 那是故意的：它逼你回来把这条测试改成"已核对"的版本，
而不是让"未核对"的状态在无人察觉的情况下被继承下去。

### 判定一：表的结构由**人声明**，解析器只做两件事

PDF 表格没有机器可读的 schema。同一个项目换一年、换一家评估机构，列序、单位、表头措辞
都会变。硬写"通用表格识别"是假装这件事已经解决。所以 `config/reports.py` 声明
`columns`（顺序 = 页面上从左到右），解析器只负责：**认出"以法定类别词开头、后面跟着
恰好 N 个数字"的行**，再按声明的列序映射。

- 判据是那 5 个法定类别词（`measured` / `indicated` / `inferred` / `proven` / `probable`）：
  JORC Clause 12 与 NI 43-101 s.2.3 都对用词有硬要求，所以这是页面上唯一**不会被随意改写**
  的锚。这条依赖直接写在 `_CATEGORY_BY_TOKEN` 上方。
- 声明与页面不符时**返回抽不到**，不凑一张看起来合理的表。

### 判定二："恰好 N 个数字"是这份解析器最要紧的防线

PMET 第 41 页上有**两张**表：锂的 6 列、铯带的 5 列，后者同样以 `Indicated` / `Inferred`
开头。分开它们的只有列数。靠"表头在第几行"认表是认不住的 —— 抽完文本之后表头与数据行的
先后顺序并不可靠。这条在 `test_a_second_table_on_the_same_page_is_separated_by_column_count`
里把两张表的原文都摆出来断言。

同理有 `-` 不能读成 0：读成 0 会在日报上印出"推断资源量 0 百万吨"，一个假得毫无破绽的数字。

### 判定三：`Total` 行**不进** `rows`，只用来交叉核对

`Total` 不是法定类别词（它只是排版上的合计），进 `rows` 会让"各类别相加"变成
"各类别 + 合计"，翻倍。但它是这张卡片上唯一**不是解析器算出来的**参照物，所以单独取出来
做比对 —— 效果等同于价格那条链路里"GFEX 官方 vs 新浪转载"的跨源核对，只是这里两边同页。

CET 第 36 页还有两处**页作者自己写的**旁证与合计行互相印证：第 6 页正文那句
`305M tonnes grading 1.1% Li2O, 105 ppm Ta2O5 and 0.6% Fe2O3`，和第 36 页脚注
`containing 3.5 M tonnes of Li2O and 71 M pounds of Ta2O5`。三处对上，说明我们读的是
同一张表、同样的列。

### 判定四："认不出表"记 `UNAVAILABLE`，**不**记 `EMPTY`

`EMPTY` 的含义是"源可达，且我们**成功地判定**确实没有符合范围的数据"。而"打开一份报告却
认不出它的表"绝大多数时候是**我们**读不出来（版式变了、列数变了），不是这份报告真的没有
资源量。记成 `EMPTY` 就等于把我们的解析失败说成"这个项目没有资源量" —— 那正是 ADR-0005
花力气分开这两种情形的理由。

### 判定五：`human_verified` 没有进产物（**这是一个缺口，不是设计**）

冻结文件里每份记录都带 `human_verified`，但 `ResourceExtract` 信封上没有对应的字段，
所以日报上的储量数字**眼下不携带"是否已核对"这一位**。我没有为此改正式契约 ——
契约是冻结的线格式，为了记一件事就往里加一个字段是要付代价的，而且今晚也没人复核这个
改动。**缺口是明摆着的**，写在这里、写进 `mineral_pdf_server.py` 的 docstring，交由人决定。

### 判定六：R2 的处置 —— 不编链接，改用同公司的公开材料（**偏离本票字面要求**）

实测（各一次，不反复重试）：

| 目标 | 结果 |
|---|---|
| ASX 上的 2017 年 Pilgangoora 技术报告直链 | **HTTP 404** |
| 公司官网（`pilbaraminerals.com.au`） | **HTTP 403**（整站 Cloudflare） |

本票的字面处置是"该矿山降级为数据缺失"。**没有那样做**，理由是那个处置的前提是"没有别的
公开文件可用了"，而实测有：公司自己在 CET 演讲材料里公开了第 36 页那张 JORC 分类表。

**代价与风险说清楚**：这是**公司自己的演讲材料转引年报**，不是独立技术报告。所以
`config/reports.py` 的 `title` 里写明了出身（"CET 演讲材料，资源量引自 2022 年报"），
它会随引用块一起进产物 —— 读者一眼能看到自己拿到的是什么，不需要去翻代码。

顺带一提：404 那份错误页（170 KB 的 HTML）**没有入库**。理由是它会稀释"清单里的每一条
都是一次真实抓取"这件事，而通用那条录下来的 503 已经覆盖了同一条代码路径。

### 判定七：页原文也冻进 fixture（只冻结果的话，解析器一行都跑不到）

冻结文件里除了 `table`，还有 `page_text`：**含表头标记的那几页原文**（CET 冻了第 6、36 页，
PMET 冻了第 41 页）。三条路各自的代价：

1. **只冻结果** → 离线能测的最多是"读到的东西和上次一样"，`parse_resource_table` 一行都没跑过；
2. **只冻文本、用时再解析** → `table` 从冻结值变成派生值，ADR-0002 的"回放比冻结值"当场失效
   （解析器一改，回放结果跟着变，而它本该是那条不许动的基线）；
3. **两个都冻**（选了这条）→ 离线能断言"解析器在两次读之间没有漂"，且 `table` 仍是冻结值。

### 判定八：`PdfSupportMissing` 炸穿，不降级

"没装 pypdf"和"这份 PDF 读不出表"是两件完全不同的事：前者是**我们的环境**不对（要让人去
装 `--extra pdf`），后者是这份文件的问题（如实记"抽不到"）。混成一句降级说明，就会出现
"以为报告没数据，其实是没装库"。所以它继承 `LoudFailure`，穿过 MCP 边界一路抛到调用方。

同时补上了工单 04 遗留的那一条：`LiveResourceSource.extract` 里 `except LoudFailure: raise`
先于 `except Exception` 出现（`prices.py` / `news.py` / `nodes.py` 已有同样一支）。

### 判定九：测试的容差按**页面自己的精度**定，且给这把尺子配一条"还有没有牙"的测试

`含量 = 吨位 × 品位` 对 CET 三行只在一个末位单位内成立：页面把"含量"印到小数点后一位，
而它是由**未取整的**吨位与品位算出来的（`0.266` 印成 `0.3`、`2.244` 印成 `2.2`、`1.089`
印成 `1.0`）。把容差收到更紧就是拿页面自己的取整当我们的算错，那种假失败比没有断言更糟。

但"放宽了容差"这件事本身需要证据，所以另写了
`test_the_loose_contained_check_still_has_teeth`：把同一份冻结数据按**挑反**的方式重算一遍，
断言三行**都被抓住**，并把这个余量最紧的一行（`Inferred`：越界 0.11，门槛 0.1）**量出来** ——
给未来改容差的人一条警戒线（调到 0.15 以上，这一行就悄悄失去检出能力，而那条例行断言照样全绿）。

写这条的时候抓到我自己的一个错：注释里我先写的是"Inferred 那行挑反了也抓不住"，
那是**只换了一边**算出来的，真把两边对调是 0.11、抓得住。是测试把这个错误当场顶了出来。

### 遗留（交给后续工单）

1. **06**：档案补到 8 座矿山 → 储量与价格的品种都会跟着长出来。
2. **`run_brief` 没有把 `fixture_root` 传给 MCP server 的 `default_runtime()`**，后者用的是
   相对路径 `fixtures`。当前无碍（pytest 从仓库根跑，且灌 fixture 的那几个测试都显式覆盖了
   runtime），但这是一个**潜伏的坑**：从别的目录调用 `run_brief` 会读到错误的 fixture 根。
   与本票同源的问题（工单 01 留下），留给 10 号工单统一收。
3. **产物的储量数字不携带"是否已核对"这一位** —— 见判定五，是一个待拍板的设计决定。
4. **PMET 那份的 `header_marker` 是"NI 43-101 Mineral Resource Statement"**，而它出现在该文件
   的 14 页里（`category_pages` 记了是哪几页）。当前靠"这一页要有合格的 N 列行"筛出第 41 页，
   够用；但换个版本时**先看 `category_pages`**，别信页码。
