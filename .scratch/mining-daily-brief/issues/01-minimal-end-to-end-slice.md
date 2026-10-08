# 01: 最小端到端切片

**What to build:** 对系统说题面那句"给我生成一份关于 Pilbara 锂矿的今日简报"，拿到一份落在磁盘上的 Markdown 矿权日报：六节齐，新闻摘要一节有真内容且带可校验的引用，价格与储量两节如实标"数据缺失"，抬头写明各节数据截止时间不同。

这一刀把**图脊一次成型**：三个并发 fetch 边、各自兜底、六节装配、逐字引用塞入、引用校验、渲染落盘。价格与储量先用返回降级信封的桩占住这两条边——它们的作用是证明"源缺失时简报照样出"（验收断言 A7），不是占位待填。后面 03 / 04 / 05 只往桩里填工具，**不动图**，避免"先写成顺序再改并行"的返工。

**Blocked by:** 00

**Status:** done

**Category:** enhancement

- [x] 题面原句端到端跑通，产物落盘，路径打到 stdout（**不往 stdout 吐全文**——那样文件就没法被断言了）
- [x] 产出六节齐；新闻摘要有内容，价格与储量两节明确标注数据缺失，"数据完整性"节说明缺了什么、为什么缺
- [x] 三个 fetch 节点在同一 superstep 并发执行，各自独立超时与重试；任一返回降级信封都不掀翻整图
- [x] 引用块里的 URL / 标题 / 时间戳与工具返回值**逐字符相同**（不是"语义等价"）
- [x] 每个 `[n]` 都能在来源清单里找到对应条目；`verify_citations` 不通过即报错
- [x] 每节标题旁标注该节数据截止时间，抬头写明"各节数据截止时间不同"
- [x] 默认模式走 MCP 协议，但用 SDK 的进程内协议连接，不起子进程（ADR-0001）
- [x] `MINING_DATA_MODE` 与 `MINING_LLM_MODE` 两个开关独立可用，默认都是回放
- [x] 数据录播与 LLM 录播查不到 key 时**直接报错，绝不回退真实调用**（ADR-0009）；R3 要求的首次真实录制在这里发生
- [x] 回放用 fixture 锚点时间而非系统时钟；fixture 存逐字节原始响应 + `sources.json`
- [x] 矿权档案给出能解析题面那句的最小可用子集；匹配不上记为"未覆盖"，不编造实体
- [x] 一条端到端用例（切面 S1）+ 新闻工具的直连用例（切面 S2），默认离线全绿

**实现记录（供追问）：**

- **验收证据**：`uv run pytest -q` → `59 passed`；`uv run ruff check .` → `All checks passed`；
  `uv run black --check .` → `51 files would be left unchanged`；`uv run mypy .` →
  `Success: no issues found in 51 source files`。
- **产物**：`uv run mining-brief brief "给我生成一份关于 Pilbara 锂矿的今日简报"` → 退出码 0，
  stdout 只有 `D:\cxb\矿产\briefs\brief-2026-10-08.md`（6 节、7 条引用）。
- **R3 首次真实录制已发生**：`scripts/record_llm.py` 用真实 DeepSeek 调用录了 3 条
  `parse_intent` + 2 条 `resolve_entities`（见 `fixtures/llm/`）。`"Escondida"` 那条模型
  正确返回 `{"project": null}` 而不是编一个项目出来。
- **超出本票的最小意图、但被本票暴露出来的一个设计改动**：跨 MCP 边界时异常类型会丢，
  于是"我们的录播不全"和"数据源挂了"在调用方看来一模一样，两者都被降级信封吸收。
  新增 `mining_brief/errors.py` 把二者分开（`ReplayMiss` 不可降级 / `ToolCallFailed` 可降级），
  并用 `REPLAY_MISS_SENTINEL` 跨进程识别。回归测试在 `tests/test_replay_discipline.py`。
- **一处与原始写法的偏离（README）**：CLI 是 `mining-brief brief "<请求>"`（带子命令），
  00 号票写的 `uv run mining-brief "<请求>"` 跑不通。已改 README 对齐实现，未改 CLI 形状 ——
  09 号票还要往这个 app 上加 stdio 入口，子命令更好扩展。
