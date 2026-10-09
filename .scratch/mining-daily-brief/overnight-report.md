# 夜间自主实现报告

**窗口：** 10-09 00:58 → 03:30（commit 时间戳为准）
**基线：** `028a0f2`（写交接提示词）
**结束：** 11 张工单全部走完 —— **10 张 `done`、1 张 `needs-human`**（05 的资源量数字必须由人对着 PDF 核，见"需要人做的三件事"第 1 条）。

一句话：**每一张票都留下了真跑过的命令与真输出**；两处"当时判定做不到"的验收项在天亮前补上了；一处**只有人能做**的核对没有假装做完。

```
总测试：246 条（默认套件 235 + stdio 9 + network 2）
全量闸门：ruff check ✅ / ruff format --check ✅（66 文件）/ mypy ✅（63 文件，strict）
默认套件：235 passed, 11 deselected
stdio 档：9 passed（真子进程走 stdio 传输）
一键通道：docker compose up → brief-2026-10-08.md，sha256 0928bd75d0d1056e…
```

---

## 一、工单总表

| 票 | 状态 | commit | 最硬的那条证据（详情见第二节） |
|---|---|---|---|
| 00 工程骨架 | `done` | `b6235c7` | `ruff/mypy/pytest` 三档装好，`--help` / `--version` 有反应 |
| 01 最小端到端切片 | `done` | `8d34b03` | 一句话进 → 六节日报出，`59 passed`，产物 stdout 只有路径 |
| 02 风险规则原文级引用 | `done` | `bef6dc0` | 三份权威文件重下比对字节数+sha256 一致；5 条规则逐字核到条款号 |
| 03 价格 GFEX / DCE | `done` | `b239188` + `9092476` | 跨源核对 117300 / 121540 / 409678 逐项相同；DCE 官网 412（实测） |
| 04 价格 LME 走无头浏览器 | `done` | `618ada5` + `9092476` | httpx/curl 403、真 Chrome 200；铜 14415.0 / 2026-10-05 / 延迟披露 |
| 05 储量 PDF 抽取 | `done` | `a9be316` + 2026-10-09 那次（见 §九） | 真下载真解析 2 份 PDF 通过；**2026-10-09 人工核对完毕，`human_verified` 已翻 True** |
| 06 拒答与未覆盖 | `done` | `b63f581` | 8 座矿 3 品种逐条实测直链（404/403/连接失败各一） |
| 07 风险信号引擎 | `done` | `fa5c520` | 引擎按冻结规则集实现；`inspect.getsource` 断言源码里没有 try/except |
| 08 每节 LLM 导读 | `done` | `ab36f38` | 编造数字只丢那一节导读，其余五节保留（否定用例） |
| 09 stdio 冒烟与宿主挂载 | `done` | `6110cb6` + `22ab0bc` | 真子进程 9 条；`claude mcp list` 三个 ✔ Connected |
| 10 交付面 | `done` | `e5502e5` + `8f09eae` | `docker compose up` 退出码 0；`--network none` 重跑哈希相同 |

另有 4 个收口/修复 commit，都不是新功能：`8e8c1c0`（ruff format 恢复全绿）、`22ab0bc`（stdio 用例编码）、
`e9f2742`（格式化只留 ruff + CI 加 stdio）、`72508e4`（产物换行符 LF）、`9092476`（补 03/04 半格）。

---

## 二、逐票：真实命令与真实输出

### 00 工程骨架 · `b6235c7`

```
$ uv run mining-brief --help        → 退出码 0，输出里含「矿权日报」
$ uv run mining-brief --version     → mining-brief 0.1.0
$ uv run ruff check . / uv run mypy . / uv run pytest -q   → 三档均在后续每票复跑
```

判断：关掉 ruff 的 `RUF001/002/003`（ambiguous-unicode）—— 全仓库注释与文案一律中文，
全角标点是**正确写法**而不是笔误，这三条规则在这里是纯噪音。`brief` 子命令留给 01。

### 01 最小端到端切片 · `8d34b03`

```
$ uv run pytest -q        → 59 passed
$ uv run mypy .           → Success: no issues found in 51 source files
$ uv run mining-brief brief "给我生成一份关于 Pilbara 锂矿的今日简报"
  → 退出码 0；stdout **只有**一行产物路径（PRD §5.3）
  → briefs/brief-2026-10-08.md：6 节、7 条引用
$ scripts/record_llm.py   → 真实 DeepSeek 录下 3 条 parse_intent + 2 条 resolve_entities
```

判断：跨 MCP 边界的异常类型会丢，于是新增 `errors.py` 把 `ReplayMiss`（**不可降级**）与
`ToolCallFailed`（可降级）分开，跨进程用哨兵串识别。另一处偏离：00 号票写的是
`mining-brief "<请求>"`，实际做成 `mining-brief brief "<请求>"`（09 要加 stdio 入口，子命令更好扩展）
—— 改的是 README，不是 CLI 形状。

### 02 风险规则原文级引用 · `bef6dc0`

三份权威文件**重新下载并逐字节比对**（不是凭记忆写条款号）：

| 文件 | 字节数 | sha256（前 12） | 重下复验 |
|---|---|---|---|
| JORC Code 2012 | 1 548 341 | `48b4a257b4f9` | ✅ 一致 |
| ASX Listing Rules Ch.5 | 2 046 053 | `36945498b515` | ✅ 一致 |
| NI 43-101（CSA Notice 副本） | 914 001 | `82cc29e680ac` | ✅ 一致 |

产出 `docs/risk-rules.md`：**5 条规则（R1–R5）+ 5 条降级提示 + 5 条整条排除**，
每条规则的 `verbatim` 是从原文里 grep 出来的字串，核到 JORC Clause 9 / 12、ASX LR 5.16.4–5.16.6 / 5.22、
NI 43-101 s.2.1 / s.2.2(a)–(d) / s.2.3(1)(a) / s.2.3(2)(a) / s.2.3(3)(a) / s.2.4。
本票**不写代码**。

### 03 价格 · GFEX 与 DCE · `b239188`（+ 天亮前补记 `9092476`）

```
$ uv run pytest -q    → 93 passed
$ uv run mypy .       → Success: no issues found in 55 source files
```

跨源核对（2026-10-08，同一合约的两种来源）：

| | GFEX 官方（碳酸锂主力 2701） | 新浪财经（碳酸锂 lc0） |
|---|---|---|
| 收盘 | 117300 | 117300 |
| 结算 | 121540 | 121540 |
| 持仓量 | 409678 | 409678 |

DCE 官网 WAF 实测：`urllib` / `curl` / **真 Chrome（Playwright `channel="chrome"`）一律 HTTP 412**。
两次有界尝试后停手，铁矿石改走新浪财经转载的 DCE `i` 合约（只改 `config/` 一行登记，
`exchange` 仍记 `DCE`，引用块的 `publisher` 记新浪财经）。

**补记**：本票原留了一格 `[ ]`（"价格一节含锂与铁矿石两项"），理由是当时档案里只有
Pilgangoora，单矿请求的范围推不出铁矿石。06 把档案补到 8 座矿后这个前提没了，天亮前用
"一句话不指定矿山与品种"补上（新录一句真实录播 + 一条端到端用例）：

```
$ uv run mining-brief brief "给我生成一份今日简报" --out briefs/wide-local
- 铜 14415.0 USD/吨（LME CA 3-month，2026-10-05，延迟披露） [21]
- 铁矿石 682.5 元/吨（DCE I0，2026-10-08，当日） [22]
- 锂 117300.0 元/吨（GFEX lc2701，2026-10-08，当日） [23]

$ uv run pytest -q tests/test_e2e_slice.py -k whole_archive   → 1 passed
$ sha256sum（本地与容器同一句产物）                            → 880fb7af67314cca…（两处相同）
```

**有一半没做到，是数据如此**：验收项写"两项截止时间互不相同"，而锂与铁矿石同为 2026-10-08
—— 10-01…10-07 国庆休市，GFEX 与 DCE 的最近交易日就是同一天。硬凑两个日期才是编数据。

### 04 价格 · LME 走无头浏览器 · `618ada5`（+ 天亮前补记 `9092476`）

三方式实测（同一页 `lme-copper`）：

```
httpx / urllib（含浏览器 UA）  → HTTP 403
curl（直连）                   → HTTP 403
Playwright 起真 Chrome         → HTTP 200，读到 14415.00
```

录播（真跑过，含故障 fixture）：

```
$ uv run python scripts/fetch_fixtures.py --only lme --browser-channel chrome --proxy http://127.0.0.1:7897 --throttle 0
  ok https://www.lme.com/en/metals/non-ferrous/lme-copper -> fixtures/prices/copper-lme-hero.html (289106 bytes)
$ uv run python scripts/fetch_fixtures.py --only faults --throttle 0
  ok [HTTP 503] https://httpbin.org/status/503 -> fixtures/faults/upstream-503.html (0 bytes)
  ok [HTTP 403] https://www.lme.com/en/metals/non-ferrous/lme-aluminium -> fixtures/faults/lme-blocked.html (5656 bytes)
```

回放侧（`tests/test_price_lme.py` 25 例）：

```
copper    status=ok  value=14415.0  as_of=2026-10-05  delayed=True  fallback=True
lithium   status=ok  value=117300.0 as_of=2026-10-08  delayed=False fallback=True
iron_ore  status=ok  value=682.5    as_of=2026-10-08  delayed=False fallback=True
```

判断：**延迟 ≠ 回退**，是两个字段、分别断言。`as_of` 取自页面自己的数据集日期选择器上界
（录播里 2026-10-05，比"今天减一天"还早三天），不取系统时钟；读不出日期时解析器**抛异常**，不给默认值。
另外新增 `LoudFailure` 基类（`ReplayMiss` / `BrowserUnavailable`），所有 catch 点统一改成
`except LoudFailure: raise` —— **缺浏览器时响亮报错，绝不降级成"LME 无数据"**。

### 05 储量 · PDF server 与资源量抽取 · `a9be316` — **`needs-human`**

```
$ uv run pytest -m network -p no:cacheprovider -v        → 2 passed, 147 deselected in 19.61s

pilgangoora-cet-2022.json: 9 747 460 B / 44 页, sha256 84ababf6…, 表在第 36 页, human_verified=False
  Measured 19.0Mt@1.4%→0.3 Mt Li₂O；Indicated 187.0Mt@1.2%→2.2；Inferred 99.0Mt@1.1%→1.0
pmet-shaakichiuwaanaan-2025.json: 5 714 740 B / 48 页, sha256 ffc6ca43…, 表在第 41 页, human_verified=False
  Indicated 107.991Mt@1.4%→3.75 Mt LCE；Inferred 33.38Mt@1.33%→1.09
```

（上面两句 `human_verified=False` 是**当夜那次运行的如实输出，不追改**。2026-10-09 人工
核对完成后两份都已翻成 `True` —— 过程见 §九。）

R2 的直链按交接要求**各试一次就停**：ASX 2017 技术报告直链 → **HTTP 404**；
公司官网 `pilbaraminerals.com.au` → **HTTP 403**（整站 Cloudflare）。**没有编链接**，
改用同公司公开可下载的 CET 演讲材料第 36 页（那页原样印着 JORC 分类表，且页脚注、第 6 页正文
与合计行三处互相印证），并在登记表的 `title` 里写明它是"公司演讲材料转引年报"，不是独立技术报告。

**没做的那一步（这就是 `needs-human` 的原因）**：把解析结果整理成待核清单**做到了**，
**核对本身没有做** —— 每份冻结记录的 `human_verified` 仍是 `false`。所以回放测试证明的是
"解析器没有回归"，**不是**"这些数字对"。

### 06 拒答与未覆盖 · `b63f581`

档案从 1 座补到 **8 座矿 / 3 个品种**，7 条直链逐条实测：

| 矿山 | 结果 |
|---|---|
| Kamoa-Kakula | 下载成功：2026-03-31 版 NI 43-101，HTTP 200，**36 169 167 B**，`%PDF-1.7`，sha256 前 12 位 `29c81fcf304d` |
| Quellaveco / Los Pelambres | 候选直链实测 **404** |
| Gudai-Darri | **403**（`riotinto.com` 整站 Cloudflare） |
| Eliwana | 连接失败（`fmgl.com.au` 不可达） |
| Mount Marion / Wodgina | 公司不单独发项目级报告，资源量声明在年报里 |

**Kamoa-Kakula 那份 36 MB 报告没有登记**：表头标记、列序、页码需要人读文件后写死
（见 `config/reports.py` 的声明式列定义），本轮没做 —— 登记一个抽不出表的链接，
产物只会说"没登记"，不如如实说"数据缺失"。

### 07 风险信号引擎 · `fa5c520`

规则集按 02 冻结的清单实现，**不自行增删**；测试直接读 `docs/risk-rules.md` 的 `### R\d+`
标题，断言 `RULES` 逐位相等；`test_the_engine_never_catches_anything` 用 `inspect.getsource`
断言引擎源码里**没有** `try:` / `except ` / `retry` / `sleep(`（ADR-0006：纯函数节点不捕获、不重试）。
实现中真的漏过一项（触发时没带出处），被上面的用例逼出来并修掉。

### 08 每节 LLM 导读 · `ab36f38`

```
$ uv run pytest -q tests/test_e2e_slice.py    → 含两条否定用例通过
```

两条各自钉一件事：**模型全线失败** → 六节全无导读，第六节记一笔"哪些节没有导读"
（此前这笔记录写进了没人再读的 `state["notes"]`，会**静默消失**，已修）；
**只在一节编数字** → 只有那一节丢导读，其余五节保留。

### 09 stdio 冒烟与宿主挂载 · `6110cb6` + 修复 `22ab0bc`

```
$ uv run pytest -q -m stdio     → 9 passed（真子进程、真 stdio、真协议帧）
$ claude mcp list
mining-news-mcp:  uv run --directory D:/cxb/矿产 mining-news-mcp  - ✔ Connected
lme-price-mcp:    uv run --directory D:/cxb/矿产 lme-price-mcp    - ✔ Connected
mineral-pdf-mcp:  uv run --directory D:/cxb/矿产 mineral-pdf-mcp  - ✔ Connected
  （用完已 `claude mcp remove` 还原，你的配置保持原样）
```

**修复 `22ab0bc`（值得单独说）**：`test_the_fixture_root_does_not_depend_on_the_working_directory`
在本机**必挂** —— 子进程 stdout 是管道，Windows 上按 locale（cp936）编码，而仓库路径带中文，
父进程按 utf-8 解码的那个线程先炸，报出来的是 `proc.stdout is None`。已给子进程加 `-X utf8`。
**交代清楚**：09 号票当时记的是 `9 passed`，今天复现出 `1 failed` —— 这条用例此前是否真的跑过、
在什么环境下跑过，我无法还原。现在的样子是本机可稳定复现的。

### 10 交付面 · `e5502e5`（+ `72508e4` 换行符 + `8f09eae` 记录）

```
$ docker compose build           → Image mining-brief:local Built（411MB）
$ docker compose up              → brief-1 exited with code 0
  event='brief.done' citations=9 refusal=False sections=6
$ sha256sum briefs/brief-2026-10-08.md
  0928bd75d0d1056e704350eb040c76f43c9bf5ad4525eb9ac4701277b3120edf
$ docker run --rm --network none -v …:/out mining-brief:local   → 同一 sha256（不联网也成立）
```

**收尾时撞出来并修掉的一个真 bug（`72508e4`）**：`write_text` 没钉 `newline`，
Windows 下落出 CRLF（4850 B）、容器里落出 LF（4720 B）—— 而 README 与 RUN.md 都写着
"本地跑与容器跑逐字节相同"。**那句话在 Windows 上是假的**。改成 `newline="\n"` 后两种环境同哈希。
`fixtures/**` 不动：`.gitattributes` 里 `-text` 是 ADR-0002 要求的逐字节原样往返。

**CI 的格式化闸门从 black 换成 ruff format（`e9f2742`）**：black 与 ruff format 对**同一份文件**
给出不同结果（推导式里的三元表达式，black 要在里面再裹一层括号，ruff 不要），
把任一方的输出交给另一方都会被打回。两个都挂不是"更严格"，是**没有唯一答案** ——
CI 结论取决于谁先跑。实测记录写在 `pyproject.toml` 的注释里，评审人可自行复核。
顺带把 stdio 那一档加进 CI（它不发网络请求，守的正是"挂进宿主取不到数据"这类路径）。

---

## 三、需要人做的三件事（按优先级）

**1. 核对工单 05 的资源量数字（唯一一个我没有资格替你勾的验收项）。**
**✅ 2026-10-09 已做完** —— 使用者对着两份 PDF 的真实页面逐行核过，5 行数字与两处
生效日全部相符，`human_verified` 已翻 `True` 并带上核对人与时间。全过程见 §九。
核对清单（留着备查）：
- CET 材料**第 36 页**：Measured 19 Mt / 1.4% / 0.3 Mt Li₂O；Indicated 187 Mt / 1.2% / 2.2；
  Inferred 99 Mt / 1.1% / 1.0（页上合计行 `Total 305 1.1 105 0.6 3.5 71`）
- PMET 技术报告**第 41 页**：Indicated 107.991 Mt / 1.4% / 3.75 Mt LCE；Inferred 33.38 Mt / 1.33% / 1.09
- 文件：`scripts/extract_resources.py` 能重跑；两份 PDF 的 URL、字节数、sha256 都在 `config/reports.py`

**2. 拍板工单 07 记下的那处文档冲突：R5 是否按报告体系分流？**
`docs/risk-rules.md` §2 里 R5 的触发条件**字面没写**"限 JORC 范围"，但同节 R1 注释、R5 注释、
§3 逐矿预期表**三处**都暗示按体系分流。我采纳了分流（三处对一处；且给一座 NI 43-101 的矿引
JORC Clause 12 是实打实引错法条），代价是 `ArchiveEntry.standard` 要重新加回来。
**如果你的原意是"R5 不分流"，改回来只是删一个条件。** 我没动文档。
**（补：天亮前那份独立的 JORC 条款核查支持"分流"这一侧 —— 见 §8.3。）**

**3. 推 GitHub 并替换 badge 的占位。**
`OWNER/REPO` 是全仓库**唯一**的占位（README 里注明）。CI 我**只在本地把四条命令都跑过**，
**没在 GitHub 上跑过**（没有 remote）—— 推上去后请看一眼 Actions：
新增的 stdio 一步在 ubuntu 上是首次执行。

---

## 四、我没做的 / 我不确定的

**没做**
- ~~05 的人工核对（唯一一个 `needs-human`，就是上面第 1 条）。~~ —— **2026-10-09 已做完**，
  见 §九。这一条从"没做"里划掉，是因为它现在真的做了，不是因为报告要好看。
- ~~**`--live` 的完整链路从没跑过**：`mining-brief brief --live "<一句话>"` 一次都没执行。
  两个开关的 live 侧**分别在录数据/录 LLM 时真跑过**（真 API、真抓取、真 Chrome 过 Cloudflare），
  但"一句话 + 实时数据 + 实时模型"串起来的那条路没有证据。~~ —— **2026-10-09 已首次跑通**，
  见 §十。前半句（Pilbara 那句）成立；**铜与铁矿石那两条路径仍未验**，见 §10.4。
- Kamoa-Kakula 那份 36 MB NI 43-101 未登记 → 8 座矿里 7 座的储量是"数据缺失"。
- `--network none` 只验了容器；Linux 主机上的本地运行没验过（只有 Windows）。
- Cursor 侧的 `${workspaceFolder}` 替换没实机验过（只验了 Claude Code）。
- ~~三个研究 agent（lithium / copper / ironore）我发过消息，**始终没有回复**~~ ——
  **这句在写完报告之后就不成立了**：它们在天亮前回信了。核实结果与我据此做了什么，
  见文末 **[附录](#八附研究-agent-回信交付之后)**。当时确实没回复，报告如实写了当时的状态。
- 本报告之外，我没有动 `PRD.md`、`spec.md`、`CONTEXT.md`、`docs/adr/` 里的任何一个字（`git log` 可查）。

**不确定**
- 09 号票当时那句 `9 passed` 是在什么环境下得到的（见第二节 09 的"交代清楚"）。
- `_RENDER_SETTLE_MS = 4000`（等 LME 前端填数的静置时间）是**起点值**，本机够用，慢机器上可能不够。
- 风险规则的**误报面**：`g/t` 会命中金矿、`%` 会命中回收率 —— 已有否定用例，但真数据上的表现没测。
- CI 的 badge 在 GitHub 上长什么样，没见过。

---

## 五、与 ADR / PRD / spec 冲突，我按判断处理了的地方

| 处 | 我做了什么 | 是否改了文档 |
|---|---|---|
| PRD 说"ASX LR 5.16 的法定警示句" | 成立；但**"合资格人署名"那组要求在 5.22 而非 5.16** —— 写进 `docs/risk-rules.md` | 未改 PRD（精确化，不是改写） |
| R5 是否按体系分流（见上第 2 条） | 采纳"分流"，`ArchiveEntry.standard` 加回来 | **未改 `docs/risk-rules.md`**，冲突原文留在工单 07 |
| R2 的 Pilbara JORC 直链 404 | 试一次就停，改用同公司 CET 演讲材料；出身写进登记表 `title`，随引用块进产物 | 未改 PRD |
| 铁矿石不用 DCE 官网（412） | 改走新浪财经转载，`publisher` 如实记新浪；README 写明理由 | 未改 PRD |
| 01 号票写的 CLI 形状跑不通 | 对齐实现改 README（`mining-brief brief "…"`） | 改 README |
| 08 的降解记录写进死路 | 改成在第六节追加一条事实（**行为更正确**，不是绕过） | — |
| CI 的 black 与 ruff format 互相打回 | **去 black、留 ruff format**，分歧原文写进 `pyproject.toml` | 改 CI / pyproject |
| 产物换行符 | 钉死 LF（`newline="\n"`） | — |
| 接地校验会**误杀**中文归纳 | 本次整档案那句的"新闻摘要"导读被拒（模型写了"石墨"，而事实是英文标题）。**没有放宽校验** —— 第六节如实写下"该节没有导读"，这是**已知局限**不是 bug | — |

---

## 六、环境变更（我动过的东西）

- **Docker Desktop 引擎**：我起过（`docker desktop start`）用来验容器通道，**现在仍在运行**。
  不想留着就 `docker desktop stop`。
- **MCP 宿主配置**：为验 09 挂过三个 server 到 Claude Code，**用完已 `claude mcp remove` 还原**。
- **网络**：走过本机代理 `127.0.0.1:7897`（LME/PDF/DeepSeek 的录播各一次）。
- **DeepSeek 额度**：本夜真实调用若干次（01 号票 5 次、04/05 的抓取不走 LLM、天亮前补录 1 句 8 次），
  都是为**录播**，金额上可以忽略。
- 仓库里**没有**任何密钥进过 commit（`.env` 被 gitignore，`.env.example` 只有变量名与语义）。

---

## 七、复现我这些话的最短路径

```bash
uv sync --all-extras
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
uv run pytest -q -m stdio
uv run mining-brief brief "给我生成一份今日简报" --out briefs/wide   # 三品种价格那一节
docker compose up && sha256sum briefs/brief-2026-10-08.md            # 0928bd75d0d1056e…
```

---

## 八、附：研究 agent 回信（交付之后）

我在写报告时发出去的研究 agent，在天亮前陆续回信了（含一份很扎实的 JORC 条款核查）。
**它们是同行会话，不是权威** —— 所以我没有直接采信，而是拿**手边同一份正本**自己重跑了一遍。
结论先给：**没有一处需要改动已交付的东西；有若干条是对我已交付内容的独立佐证。**

### 8.1 先证明"读的是同一份文件"

agent 报的是 MD5，我 §1 记的是 sha256。两边都没有的可比项，先对齐字节：

```
$ wc -c .scratch/jorc-src/jorc2012.pdf          → 1548341
$ md5sum    .scratch/jorc-src/jorc2012.pdf      → d475e3a58110bb8a6a25fd785468b27c
$ sha256sum .scratch/jorc-src/jorc2012.pdf      → 48b4a257b4f997f1b9db1b493d5a7f7b2f08decd547b85e03761a6618b1187d6
```

**三方吻合**：agent 的 MD5 与我本地一致，我的 sha256 与 `docs/risk-rules.md` §1 表里记的**逐位一致**。
所以下面的复核是在**同一串字节**上做的。

### 8.2 我逐条自查的结果（不是转述）

| agent 的说法 | 我自己在同一份正本上的复核 | 结论 |
|---|---|---|
| JORC 2012 正本里 `production target` **0 命中** | `grep -c -i "production target" jorc2012.txt` → **0**（连 `_raw` 抽本也是 0） | ✅ 证实 |
| "生产目标警示句"属 **ASX LR Ch.5 / GN31**，不属 JORC | JORC Clause 3 指南第 142 行自己写着：`Code associated with Public Reports that are addressed specifically within the listing rules.` | ✅ 证实 |
| `caution` 只出现在 Clause 21 指南 / Clause 34 指南 / Clause 38 | 命中恰为第 709、787、1032、1124、1127 五行 | ✅ 证实 |
| JORC 是否存在"不得把 Inferred 转成储量"的条款 | Clause 21（第 675 行）：`must not be converted to an Ore Reserve` | ✅ 存在 |
| 2012 版仍现行？（agent 说**它没核实**） | **我自己查了** `jorc.org/code-update/`：截至 **2026 年 8 月**最后一次更新，新版仍在评审，原文 `Once the Code is finalised … after an agreed transition period, operation of the new Code will commence.` —— **尚未生效** | ✅ 2012 版仍是现行版本 |
| 2012 版生效日 | 正本第 10–11 行：`E ective 20 December 2012 and mandatory from 1 December 2013`（`E ective` 的连字伪影见 §1，原文为 `Effective`） | ✅ 证实 |

### 8.3 这些回信**没有**改变什么 —— 因为我的规则集本来就是对的

最该说明的一点：agent 那条"生产目标警示句不在 JORC"的结论，看着像是要改 R4，
**其实它佐证了 R4**：

- R4 的 `逐字原文` 引的是 **ASX Listing Rule 5.16.4**，**不是** JORC；
- `docs/risk-rules.md` §1 也明写着「`5.16` 管的是 `production target`」。

也就是说，我在冻结规则集时就已经把"生产目标"归到了 ASX 名下。**一个独立的第三方核查，
读了同一份字节，得出了同一个归因** —— 这比我自己说"我核过了"更有说服力，可以放心经得起追问。

同理，R5 引 JORC Clause 12 也是对的（第 429–430 行逐字在）。R5 的 `standard` 分流
（JORC 规则不套 NI 矿）由此也站得更稳：Clause 12 是 JORC 自家的术语条款，套到一座
NI 43-101 的矿上确实是**引错法条**。

### 8.4 顺带查出来三处，我**一个字都没动**，留给你定

1. **§7 的复验命令在 JORC 上会漏。** `grep -n "must only use the terms set out in Figure 1" jorc.txt`
   在本机抽本上**返回空** —— 因为该句跨两行（第 429 行 `… must only use the`，第 430 行 `terms set out in Figure 1.`）。
   引文本身是逐字的，**是那条复验命令不严谨**。§1 只警告了连字与空格伪影，没警告换行。
   一行字的修法（把 grep 换成 `grep -A1 "must only use"` 或跨行匹配），我没动 ——
   `risk-rules.md` 是工单 02 的冻结产出。
2. **R1 的中文说明把 JORC 的对应物指成了 Clause 12。** agent 查到的 JORC Clause 26 更贴
   （第 815 行 `Categories must not be reported in a combined form unless details for the individual…`、
   第 822 行 `Mineral Resources must not be aggregated with Ore Reserves.`）—— 那才是"不得混列/相加"。
   这是**说明文字**里的交叉引用不准，不涉及任何 `verbatim`，所以不影响产物正确性，
   但评审人若较真会问到。同样没动。
3. **档案扩展候选**：三个 agent 各给了十几座矿 + 已下载成功的 PDF 直链（锂 6 份、铜 5 份、铁矿石 6 份）。
   看着很诱人，但**采纳会改动 `commodity_in_scope` → 产物哈希与已录播的 LLM 响应全部作废**，
   不是我在你睡着时该单方面做的决定。清单原样留着等你。
   而且它们**未经我逐条核实**，agent 自己就自查出若干问题：力拓 Simandou 与 Vale 那两份实际是
   **S-K 1300** 而非 JORC（agent 填的 `standard` 列自己标了不准）、若干中文公司名是**音译非官方**、
   Mary River 只有 **Wayback 快照**、Vizcachitas 的资源量表是**位图**抽不出文本。

   **处置（10-09 早上）**：清单已整理成同目录的
   [`archive-expansion-candidates.md`](archive-expansion-candidates.md) 备查 —— **未采纳**，
   任何一行都没进 `config/archive.py`。那份文件每行都带"体系 / 可抽性 / 直链稳定性"三项
   待核标注（含两处 S-K 1300 被 agent 误填成 JORC），并写明扩档案要重录 LLM、重验产物哈希的代价。

### 8.5 一个意外收获：对工单 06 的独立佐证

铜那路 agent 自己去下载了 Kamoa-Kakula 的报告，报回来：

```
36,169,167 字节  sha256 前 12 位 29c81fcf304d
```

与工单 06 记下的**逐位相同**（`36 169 167 B` / `29c81fcf304d`）。**一个独立会话、另一次下载、
同一个哈希** —— 这是"那次真下载过、不是编的"的一份外部证明。这条我没法自己给自己开，
来了正好补上。

### 8.6 我没做的

- **没有回复这些 agent**，也没有据它们改动任何文档、规则或代码。
- 候选矿山清单**逐条未核实**，只做转述（且已标注 agent 自查出的瑕疵）。
- 上述 8.4 的三处全部**保持原状**，等你在早上定夺 —— 与 R5 那处冲突同一处理方式：
  冲突进报告，不动冻结文档。

---

## 九、追记：工单 05 的人工核对闭合（2026-10-09）

这一节是交付**之后**补的，记的是 §三 第 1 条那件"我没有资格替你勾"的事 —— 它做完了。

### 9.1 谁、怎么核的

使用者本人，对着两份 PDF 的**真实页面**（不是 JSON 里那份 `page_text`）逐行看：

- **Pilgangoora / CET 材料第 36 页**：Measured 19 Mt @1.4% → 0.3 Mt Li₂O、Indicated 187 @1.2% → 2.2、
  Inferred 99 @1.1% → 1.0 —— 与冻结表逐行相符。
- **PMET 第 41 页**：Indicated 107.991 Mt @1.40% → 3.75 Mt LCE、Inferred 33.38 Mt @1.33% → 1.09 —— 相符。

### 9.2 核对中途提出的一个疑问（**不是错**，记下来免得下一个人再问一遍）

> **问**：PMET 的吨位页面印的是 `107,991,000`，JSON 里却是 `107.991` —— 小数点是你加的吗？

是设计，不是错。`ResourceRow.tonnage_mt` 的单位按契约就是**百万吨**
（`contracts/resources.py:52` 的 docstring），登记表为这一页声明了 `scale=1e-6`
（`config/reports.py:119`，注释里逐字抄了页面表头 `Tonnes(t) …`）。107,991,000 ÷ 1e6 = 107.991。

对照 Pilgangoora：那页表头写的是 `Mdmt`（百万干吨），所以那一列用默认的 `scale=1.0`，
19 就是 19。**同一个字段、两个页面单位，靠人声明而不是靠猜** —— 这正是
`_row_to_contract` 那段注释（"单位错了差一百万倍，所以它由人声明、由人核对，解析器不猜单位"）
要防的那类错。

顺带一条比单位更强的内证：PMET 第 41 页自己在分类行**上方**印着小计（文本抽取后顺序是反的）——

```
101,828,000 + 6,163,000 = 107,991,000   ← 与我们要的 Indicated 行相加自洽
 13,898,000 + 19,482,000 =  33,380,000   ← 与 Inferred 行相加自洽
```

这条不依赖行序、只依赖数，与 `find_total_row` 那套"拿页面自己印的东西对表内相加"同一个意思。

### 9.3 动了什么（六个字段 + 三份文档 + 一条测试）

| 文件 | 改动 |
|---|---|
| `fixtures/resources/pilgangoora-cet-2022.json` | `human_verified` `false→true`、`human_verified_by`、`human_verified_at` |
| `fixtures/resources/pmet-shaakichiuwaanaan-2025.json` | 同上 |
| `tests/test_resources.py` | 守卫用例 `..._says_it_is_not_human_verified_yet` → `..._records_who_verified_it`；`test_flipping_the_verified_flag_changes_only_the_note` 改为**两个方向都验** |
| `README.md` | "全部是 `false`"那段改成"已核对"，并写清这个字段不是装饰 |
| `mining_brief/servers/mineral_pdf_server.py` | docstring 改成"没核过就必须 `false`、核过才允许 `true` 且要带核对人" |
| `.scratch/.../issues/05-resource-extraction-pdf.md` | `Status: needs-human → done`；⛔ 一格勾上；补「收尾：人工核对的闭合」 |
| 本报告 | §一 表内那一行、§二 的 `human_verified=False` 输出块（**加注，不追改**）、§三 第 1 条、§四 第一条 |

改 JSON 用脚本原地做（`re.subn`）：这两份是 **CRLF** 文件，过编辑器很容易把行尾翻成 LF、
让 diff 显示"整份文件都改了"。`git diff --numstat` 的结果是**每个文件恰好 3 行 + / 3 行 −**。

**没动的**：`PRD.md`、`spec.md`、任何 ADR、`config/reports.py` 的列声明与换算系数、
`scripts/extract_resources.py` 的行为（它**仍然**每次把字段写回 `false`），以及两侧冻结的
`table` 数字本身。

### 9.4 守卫还咬不咬人 —— 验过了，不是推测

`human_verified` 一旦被核过，最容易发生的事是**有人重跑 `extract_resources.py`**（它按纪律
把字段写回 `false`）**而没有重新核对**，于是"已核对"这个状态无声无息地倒退。所以守卫留在
`True` 这一头，并真的喂了一次 `false` 看它炸不炸：

```
$ uv run pytest tests/test_resources.py -k records_who     # 先把 PMET 那份按回 false
>       assert extract.human_verified is True
E       AssertionError: assert False is True
tests\test_resources.py:425: AssertionError
FAILED tests/test_resources.py::test_the_frozen_extract_records_who_verified_it[pmet-shaakichiuwaanaan-2025]
================= 1 failed, 1 passed, 28 deselected in 0.76s ==================

$ uv run pytest tests/test_resources.py -k records_who     # 还原后
2 passed, 28 deselected in 0.17s
```

一条红、另一条（Pilgangoora）照样绿 —— 参数化确实按份生效，不是一起红。

### 9.5 此刻的全量闸门

```
$ uv run ruff check .            → All checks passed!
$ uv run ruff format --check .   → 66 files already formatted
$ uv run mypy                    → Success: no issues found in 63 source files
$ uv run pytest -q               → 235 passed, 11 deselected, 4 warnings in 16.03s
```

用例数仍是 235：守卫那条是**改名 + 改断言**，不是新增或删除，两个参数项都还在。

### 9.6 一件仍待你拍板的事（没有因为这次核对而消失）

工单 05 判定五那个缺口依然开着：**产物上的储量数字不携带"是否已核对"这一位**
（`ResourceExtract` 信封上没有 `human_verified`）。两份现在都核过了，所以这个缺口的后果
比昨夜轻 —— 但"日报读者不知道这批数字是否已核对"这件事本身没变。要不要提到正式契约上，
仍是一个要付代价的决定，留给你。

---

## 十、追记：`--live` 全链路首次跑通（2026-10-09）

§四 里那句"**`--live` 的完整链路从没跑过**"已经不成立了 —— 这一节记它怎么变成立的。
原话加删除线保留，因为那时它是真的。

### 10.1 结果

```
$ uv run mining-brief brief --live "给我生成一份关于 Pilbara 锂矿的今日简报" --out live-briefs
event='brief.written' path='live-briefs\brief-2026-10-09.md'
event='brief.done' citations=9 refusal=False sections=6
exit 0
```

**首次执行就通过**，没踩到任何坑：6 节齐、9 条引用、没有拒答、退出码 0。

### 10.2 "它真的是实时的吗" —— 这不能靠退出码回答

一次成功的运行既可能是实时，也可能是**悄悄回退成了回放**。判据取自
`mining_brief/servers/runtime.py:51`：

```python
if self.settings.data_mode == "replay":
    return self.store.anchor_at      # 冻时钟 2026-10-08T17:01:57+00:00
return datetime.now(UTC)             # 真实时钟
```

`now` **当且仅当** `data_mode == "live"` 时才是真实时间，而 `now` 会一路印进第 5、6 节的
「数据时点」。实测那两节印的是 `2026-10-09T03:07:33+00:00`（= 运行时刻），回放版同一节印的
是冻锚点。**所以这一行本身就是"数据层确实切到了 live"的证据**，不必再去翻 `brief.start`。

两处旁证：

- 产物文件名是 `brief-2026-10-09.md`（真实数据时点），回放那句是 `brief-2026-10-08.md`；
- 各节那几句 `>` 导读**措辞与回放版不同** —— 回放模式下 LLM 响应是逐字节重放的，
  只有真调了模型才会换一句话。两次运行、同样的输入、不同的措辞，这条最直接。

### 10.3 一个值得记下来的观察：实时数据与回放**逐字相同**

把两份产物并排看，**数据部分完全一致**：7 条新闻连同各自时间戳（最新
`2026-10-08T12:49:00+00:00`）、锂价 `117300.0`（GFEX lc2701，2026-10-08）、储量三行、
9 条引用 —— 全同。只有 LLM 那几句导读不一样。

这不是"实时路径偷偷读了 fixture"（10.2 已排除），而是**数据本身就没变**：

- 冻锚点是 `2026-10-08T17:01:57Z`，本次实时跑在 `2026-10-09T03:07:33Z`，**相隔约 10 小时**，
  都在同一个交易日窗口内，最近交易日同为 `2026-10-08`（国庆后第一个交易日）；
- 储量那份 PDF 是 2022 年的文件，不会变；
- 新闻窗口是"最近 7 天"，这 10 小时里没有新的匹配条目进来。

换个说法：**这份 fixture 相对现实是"新"的**。它和实时结果对得上账，不是因为巧合，
是因为录得够近。真要验"实时能取到新东西"，得隔几天再跑一次，或者换个更活跃的查询。

### 10.4 铜价与铁矿石：**2026-10-09 已跑，全通**

Pilbara 那句的范围只有锂，`价格（锂）：已取到 1 个数据点` —— 铜与铁矿石一次都没走到。
所以随后又真跑了**整档案**那句：

```bash
uv run mining-brief brief --live "给我生成一份今日简报" --out live-briefs
# exit 0, refusal=False, sections=6, citations=23
```

第 4 节三行齐全：

```
- 铜 14415.0 USD/吨（LME CA 3-month，2026-10-05，延迟披露） [21]
- 铁矿石 682.5 元/吨（DCE I0，2026-10-08，当日） [22]
- 锂 117300.0 元/吨（GFEX lc2701，2026-10-08，当日） [23]
```

**最要紧的是第一行。** LME 铜这条路要走真实页面导航过 Cloudflare，是全仓库唯一一个
`requires_browser=True` 的源，也是它当初逼出 `LoudFailure` 那条"缺浏览器就响亮报错、
不许降级成没数据"的纪律。它实时跑通了，而且 `延迟披露` 如实印在产物上 —— ADR-0004
要求它不被"回退到了更早的日期"混同，两个限定词在这里是分开的（`延迟披露` 有、
`回退自` 无）。

第 1 节也非空（`MACH Energy commits to responsible operation following court ruling`），
与回放版一致；第 6 节把 8 座矿里 7 座的储量缺失**逐条给出各自的理由**（"该公司不单独
发布项目级技术报告……"），不是一句笼统的"数据缺失"。

**实时与回放的数据部分再一次逐字相同** —— 三行价格连 `as_of`、`延迟披露`、引用 URL
全部一致。理由同 10.3：两次运行相隔 10 小时，同处一个交易日窗口。

### 10.5 第 1 节为空不是 bug（顺手澄清）

Pilbara 那句的第 1 节是空的（`本节没有取到任何数据`）。查过了：**回放版那句也是空的**，
而整档案那句**两边都非空**。原因是这一节只收「矿权动态」这一个类目的条目，Pilbara 那句
召回的 7 条全被归进了普通新闻。行为一致，与实时无关。

### 10.6 顺带修的一处

`--live` 首次真跑把 `live-briefs/` 暴露成了未跟踪文件 —— `.gitignore` 里只有 `briefs/`，
是我给的 `--out` 目录名漏了配套。已补（commit `d3c4f78`），并在注释里写明两者忽略的
**理由不同**：回放产物可复现，实时产物不可复现，后者留档等于把一次偶然的网络快照
伪装成仓库内容。

### 10.7 验证时撞到的一处不一致：铁矿石引用块的「发布方」（2026-10-09 已修）

比对实时与回放两份产物时发现的。它与实时/回放**无关**（两边印的是同一串），是**文档与
代码不一致**。

产物里 `[22]` 印的是：

```
**[22]**（价格）DCE I0

  DCE · 2026-10-08

  <https://finance.sina.com.cn/futures/quotes/I0.shtml>
```

而 `mining_brief/config/sources.py:130` 的注释写着：

> 引用块里 `publisher` 记的是新浪财经，不是 DCE：数据的**发布方**是谁就写谁。

**这个 `publisher` 字段并不存在。** `PriceSource`（`commodity` / `exchange` / `symbol` /
`currency` / `unit` / `quote_format` / `quote_url` / `page_url` / `delayed` /
`requires_browser`）没有它，`PricePoint`（`commodity` / `exchange` / `symbol` / `value` /
`currency` / `unit` / `as_of` / `delayed` / `source_url` / `requested_date`）也没有；
`mining_brief/agent/nodes.py:621` 传的是 `publisher=latest.exchange`，于是印出 `DCE`。

同处 `PriceSource.exchange` 的 docstring 还写着"注意它**不一定**等于数据的发布方，见
`PRICE_SOURCES` 的说明" —— 说明这个区分**被设计过**，只是没落进契约。

**事实层面没有错**：铁矿石那个数确实来自新浪转载的 DCE `i` 合约，`source_url` 也如实
指向新浪；工单 03 还做过交叉核对（GFEX 官方 `clearPrice` 与新浪 `s` 字段同为 121540）。
出问题的只是**命名**——同一条引用里发布方写 `DCE`、链接写 `新浪`，读者没法判断该信哪头。

两条路线，代价不同。**留给了使用者拍板，他选了改代码**（2026-10-09）：

1. **改代码** ✅ **选这条**：`PriceSource` 加 `publisher` 字段、`PricePoint` 加同名字段、
   三处解析器从 `source.publisher` 取、`nodes.py` 用 `latest.publisher`。忠于注释记下的
   原意，代价是要动一个冻结的契约（`PricePoint`）。
2. **改注释**：把 `sources.py:130` 改成如实描述**已实现**的约定（发布方 = 交易所，
   取数点由 URL 承载）。零代码改动，但等于承认"发布方"这个概念在产物上不表达。

选 1 的决定性理由是一条当时没注意到的自证：**`Citation.publisher` 的契约原文就是
「原样搬运工具返回值」**（`contracts/brief.py:110`）。工具根本不返回发布方，所以
`publisher=latest.exchange` 那一行搬的不是工具的返回值，是现场编的 —— 那条引用
**违背了它自己的契约**。这不是"要不要多一个字段"的取舍，是一个已经写在契约里、
代码却没做到的事。

#### 修完之后（收口记录）

- **新增 ADR-0010**（`docs/adr/0010-price-point-publisher-field.md`）：记这次契约加字段的
  理由与被否掉的三条路线。**同时改了 ADR-0004** —— 它写着 `requested_date` 是"对已冻结
  PRD 的**唯一一处**契约加字段"，这话现在不成立了，已改为"第一处"并加注指向 0010。
  （PRD §6.1 的 `PricePoint` 代码块同步补了 `publisher` 一行 + 一条指向 0010 的注。）
- **`publisher` 是必填项，没有默认值**。理由与单位（`ReportColumn.scale`）同源：发布方
  读不出来、写错了也不报错，只会在产物里安静地印一个错出处。三个源里只有铁矿石与
  `exchange` 不同 —— 一旦允许默认为 `exchange`，它**必然**被写错。
- **正文一字未动**：仍印 `DCE I0`（那是**合约**，读者靠它认行情），出处改成 `新浪财经`
  + 新浪链接（那是**发布方**）。顺带保住了回放 —— `narrate` 的 key 由 `narrative_payload`
  构造、只取 `fact.text`，不含 citation，所以六节 LLM 录播一个都没作废。
- **测试**：`tests/test_prices_section.py` 新增 `test_the_citation_names_the_publisher_not_the_exchange`
  （文档里直接引用产物里那串真实文字），`tests/test_price_parsers.py` 新增两条
  （每个源都必须声明非空发布方；铁矿石解析后 `exchange == "DCE"` 且 `publisher == "新浪财经"`）。
  **验过有牙**：把 `nodes.py` 改回 `latest.exchange`，这两条立刻红（`2 failed, 6 passed`），
  改回即绿。全套 `240 passed`（改前 235，+5）。
- **fixture 一个都没重录** —— 这正是 ADR-0002 选"存原始响应"而非"存归一化结果"的收益：
  契约加字段不影响任何录播。ADR-0002 里那句"类型一改 fixture 全废"这次没有应验。
