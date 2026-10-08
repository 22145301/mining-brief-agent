# 07: 风险提示 · 规则引擎落地

**What to build:** 日报的"风险提示"一节有内容，且每条风险信号都能读到它依据的**权威原文**。

规则集来自 02 的核对结果——本票只实现引擎，**不新增也不删减规则**。这是"风险信号"这个词不被稀释成"随便什么观察"的全部保障。

**Blocked by:** 01, 02

**Status:** done

**Category:** enhancement

- [x] 规则引擎按 02 冻的规则集实现，规则与代码一一对应，不自行增删
      —— 不是靠自觉：`tests/test_risk_rules.py::test_the_engine_implements_exactly_the_frozen_rule_set`
      直接读 `docs/risk-rules.md` 的 `### R\d+` 标题，断言 `[r.rule_id for r in RULES]`
      与之**逐位相等**。另有三条盯住出处纪律：每条 `verbatim` 必须**是**文档那段
      `>` 引文里的字串（`test_every_verbatim_is_the_one_frozen_in_the_document`）、
      每条 `source_url` 必须出现在 §1 那张**记了 sha256** 的表里、任何一条都不许引
      GN31（文档说了它是旁证、不可复验）。
- [x] 每条风险信号含三项：触发的规则、**逐字引用**的权威原文、出处 URL
      —— 实现里**真的漏过第三项**：`_risks_section` 渲染了规则名、触发说明和原文，
      却没带出处。是 `test_a_triggering_rule_reaches_the_document_with_its_verbatim`
      断言产物里应出现 `nssc.novascotia.ca` / `asx.com.au` 时把它逼出来的。已修。
- [x] 引不到原文的条目降级为"提示"，**不出现在"风险信号"里**（两个词在产物里是分开的）
      —— `HintRule` **结构上**就没有 `verbatim` / `source_url` 字段
      （`test_the_hints_carry_no_verbatim_field_at_all`）。不是省字段：做成"引文可以为空"
      的风险信号，等于在同一个字段里容许两种东西。
- [x] 规则引擎是**纯函数**：不重试、**不捕获异常**（ADR-0006）
      —— `test_the_engine_never_catches_anything` 用 `inspect.getsource` 断言源码里
      没有 `try:` / `except ` / `retry` / `sleep(`。跑一遍只能证明"这次没抛"。
- [x] 没触发任何规则时该节明说"本次未触发"，**不留空白**让人误读成"没有风险"
- [x] 语言纪律：`储量` 与 `资源量` 不混用，术语一律以 `CONTEXT.md` 为准
- [x] 触发路径与未触发路径各有一条端到端用例（切面 S1），另加一条"给一段没有原文支撑的观察，断言它只出现在提示里"的否定用例（切面 S3）

**实施中发现并处置的一处文档冲突（未改文档，写在这里）：**

`docs/risk-rules.md` §2 里 R5 的**触发条件**本身没写"限 JORC 范围"，但同一节的
R1 注释、R5 注释，以及 §3 的逐矿预期表**三处**都暗示 R5 是**按报告体系分流**的。
采纳了分流（三处对一处；且给一座 NI 43-101 的矿引 JORC Clause 12 是实打实的引错法条）。
代价是 `ArchiveEntry.standard` 这个字段要重新加回来 —— 它记的是"**这座矿**按哪套体系
披露"，与卡片上的"**这份文件**里那张表是哪套体系"是两件事，消费者也不同（规则引擎按
前者分流、解析器按后者标注）。`tests/test_archive.py` 有一条盯着两处在同时存在时不许
漂移。**这条留待早上确认**：如果原意是"R5 不分流"，改回来只是删一个条件。

**顺带指出但**未**处理的：**
R4 的 `触发条件` 带一个条件从句（"若该主体在 ASX 上市"），因为"这个主体是不是 ASX
上市"我们判不了。所以它写成**提醒**而不是断言 —— 判不了就不假装判定。
`docs/risk-rules.md` 里 R4 的 verbatim 句末没有句点，代码里也**不许**补一个
（`test_r4_carries_its_conditional_clause_instead_of_asserting` 钉住了这一条）。
