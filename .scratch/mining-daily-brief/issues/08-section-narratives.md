# 08: 导读：每节一句 LLM 导读

**What to build:** 日报每节开头多一句人话导读，读起来是成品而不是数据堆。

这是图里第 3 个、也是最后一个模型节点。它的特殊之处在于：输入是**已冻结的数据**，而且它的输出还要再过一道引用校验——模型在这条链上没有任何生成事实的机会。

**Blocked by:** 01

**Status:** done

**Category:** enhancement

- [x] 每节一句导读，输入是已冻结的该节数据，模型不参与任何事实生成
- [x] 导读的录播 key 按**输入数据**的规范化哈希索引（不是按 prompt 哈希，也不是按调用序号），缺 key 直接报错不回退真实调用（ADR-0009）
- [x] 模型调用失败时降级为**不写导读**，日报照常产出，并在"数据完整性"节记一笔
- [x] 导读里不出现任何不在该节数据里的数字或实体（断言）
- [x] 两个模式开关在这一层体现价值：改导读措辞时不必把数据层切到真实抓取
- [x] 一条端到端用例断言"每节都有导读"、一条断言"LLM 失败时无导读但日报仍出"

---

## 完成情况

### 落了什么

- `mining_brief/agent/narratives.py`：`narrative_payload()`（喂给模型的就是这一节的冻结数据，
  **刻意不含 `citation` 内部编号**）、`extract_lead()`、`lead_is_grounded()`。
- `nodes.narrate()`：六节各调一次，**只捕获 `LLMError`**（`LLMReplayMiss` 刻意不继承它，
  缺录播就一路炸到 CLI）。
- `render.py` 把 `lead` 渲染成每节标题下的引用块 —— 产物里真看得到（见下）。
- 端到端三条用例 + 单元九条（`tests/test_narratives.py`）。

### 验收对照

| 验收 | 证据 |
| --- | --- |
| 每节一句导读 | `tests/test_e2e_slice.py::test_every_section_carries_a_lead` |
| key 按输入数据哈希、缺 key 报错 | `tests/test_narratives.py::test_the_node_name_is_the_replay_key_prefix`、`tests/test_replay_discipline.py`（4 条） |
| 失败→无导读，日报照出，第六节记一笔 | `tests/test_e2e_slice.py::test_a_dead_narrator_costs_the_leads_and_nothing_else` |
| 越界的数字/实体被拦 | `tests/test_e2e_slice.py::test_an_invented_number_costs_only_that_one_section_its_lead`、`test_narratives.py` 的三组 |
| 两个开关分开 | `tests/conftest.py::settings`：`--record-llm` 只把 **LLM 层**切 live，数据层恒为 replay |
| 端到端两条 | 上面两条 + `test_a_lead_says_nothing_the_section_does_not_already_say` |

产物抽样（`uv run mining-brief brief "给我生成一份关于 Pilbara 锂矿的今日简报"`，
回放模式，实际文件 `briefs/brief-2026-10-08.md`）：

```
## 4. 价格走势
*数据时点：2026-10-08*
> 价格走势：2026-10-08，GFEX lc2701 锂 117300.0 元/吨。
- 锂 117300.0 元/吨（GFEX lc2701，2026-10-08，当日） [9]
```

### 三处需要人过目的判断

1. **重录从"跑脚本"变成"两条入口"。** 回放 key 落在**输入数据**上，而测试套件喂进去的数据
   是几十条用例各造各的（导读那一步尤其），`scripts/record_llm.py` 里那三句样例句复现不出来。
   于是加了 `pytest --record-llm`：让测试自己在 live 模式下跑一遍，录下的集合才恰好等于
   回放需要的集合。现在 `LLMReplayMiss` 的提示语同时点名两个入口。
   **代价**：`--record-llm` 那一轮有两处必然的红 —— `test_settings_default_to_replay_on_both_switches`
   （shell 里导出了 key）与 `test_a_replay_miss_kills_the_whole_run...`（那一轮模式是 live）。
   已把前者的 `monkeypatch.delenv("MINING_LLM_API_KEY")` 补上、把后者的 `llm_mode` 明写成
   replay，两条现在**在两种模式下都是绿的**。重录那一轮的绿因此可以只用 "not network and not stdio"
   之外的东西解释，不再有借口。
2. **接地闸门是"必要不充分"，写在 docstring 里而不是藏着。** 它拦得住凭空多出来的数字、
   外来的拉丁词（公司名/交易所）、外部日期；拦不住模型编一个**中文**实体名（字符串包含关系看不出来）。
   挡那一半靠的是"payload 只有这一节"加 prompt 的封闭性。
3. **`state["notes"]` 是死路，别往那儿写。** `assemble` 早就把六节搭好了，narrate 之后再往
   `notes` 里追加**没有任何节点会再读它** —— 第一版就是这么写的，"导读全线消失"在产物里
   于是长得和"一切正常"一模一样，是被 `test_a_dead_narrator_...` 逼出来的。现在落成
   第六节的一条事实。
