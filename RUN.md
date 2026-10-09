# 5 分钟跑出第一份日报

这条路**不需要任何 API key、不联网、结果确定** —— 默认模式是回放：数据读 `fixtures/`
里逐字节存下的真实响应，LLM 读 `fixtures/llm/` 里录下的真实响应，时钟取 fixture 锚点
（所以产物日期是数据时点，不是今天）。详见 [ADR-0001](docs/adr/0001-replay-seam-in-datasource-layer.md)
与 [ADR-0002](docs/adr/0002-fixture-stores-raw-responses-frozen-clock.md)。

## 一条命令

```bash
git clone <本仓库> && cd <本仓库>
docker compose up
```

跑完即退（**不是常驻服务**，别用 `up -d`）。日志末尾那行 `event='brief.done'` 就是成功。

## 产物在哪

```
./briefs/brief-2026-10-08-pilgangoora-7d.md
```

`brief-<日期>-<范围>.md`，两段各有一个意思：

- **日期**是**数据时点**（fixture 锚点），不是你跑它的那天 —— 同一输入两次跑，
  这个文件逐字节相同（换行符钉死成 LF，所以在 Windows 上本地跑与在容器里跑**也是同一串字节**）。
- **范围**是这份日报覆盖的矿山与窗口（`pilgangoora` = Pilbara 那一座，`7d` = 新闻窗口 7 天；
  整个档案写作 `all`）。文件名回答的是"**这是什么**"，不是"我哪天按的回车" —— 所以
  **同一天问不同的问题不会互相覆盖**，各落各的文件。

想换个问题，就问另外三句**已录播**的样例句 —— 三句落三个文件，都在 `./briefs/` 下：

```bash
# 什么矿山、什么品种都不指定 → 范围是**整个档案**：8 座矿、3 个品种
docker compose run --rm brief mining-brief brief "给我生成一份今日简报"

# 看边界的两句：一句越界（不做预测）、一句未覆盖（不在档案内）
docker compose run --rm brief mining-brief brief "帮我预测一下明天铜价会涨吗"
docker compose run --rm brief mining-brief brief "看看 Escondida 铜矿最近 3 天"
```

后两句是**拒答**，产物是两页说明文（"我听懂了什么 / 为什么这次不行"）。拒答没有范围
可用，文件名取请求文本的短哈希（`brief-2026-10-08-refused-<8 位>.md`）—— 两次**不同**的
越界请求因此也不会互相覆盖。想按人来读，把 `--out` 换成别的目录即可。

第一句值得一看：价格那一节同时出现锂 / 铜 / 铁矿石三行，**三个数据时点各自标注** ——
铜是 `2026-10-05` 且写明"延迟披露"（LME 只给延迟收盘价），锂与铁矿石是 `2026-10-08` 当日。
三个不同来源的价格能并排站在一起且各说各的时点，是这份产物最该被检验的地方。

（`docker compose run` 的 `brief` 是**服务名**，后面那串才是命令。）

**回放模式只认录过的话。** 换一句没录过的，它**不会**偷偷去调真实模型 —— 直接报
`LLMReplayMiss` 并列出该节点已有的录播键，这是 ADR-0009 的刻意设计（回放不回退真实调用，
否则"确定性"就成了"通常确定"）。要问新鲜的，两个办法：加 `--live`（要 key、要联网），
或者按 `scripts/record_llm.py` 重录一批样例句。**内置的三条样例句就是全部离线可问的话。**

## 不装 Docker 的话：三条本地命令

需要 [uv](https://docs.astral.sh/uv/)（它会自己把 Python 与依赖备齐）。

```bash
uv sync --all-extras                                          # 装（含浏览器与 PDF 解析两个可选 extra）
uv run mining-brief brief "给我生成一份关于 Pilbara 锂矿的今日简报"   # 跑
uv run pytest                                                 # 测（默认离线、确定性）
```

跑完 stdout 上只有一行：产物路径。看它，或者 `cat` 出来。

## 想看它连真网络

```bash
# 两个开关分开：数据层与 LLM 层各自 replay | live（ADR-0009）
uv run mining-brief brief --live "给我生成一份关于 Pilbara 锂矿的今日简报"
```

要配 `MINING_LLM_API_KEY`（LLM 层）、要联网、铜价那条还要装浏览器
（`uv run playwright install chromium`，或 `MINING_BROWSER_CHANNEL=chrome` 用系统 Chrome）。
变量清单在 [`.env.example`](.env.example)。**缺浏览器时它响亮报错，不会降级成"LME 无数据"**。

## 边界

- **同一个范围重跑会覆盖上一次** —— 这是有意的：范围一样、数据一样，两份产物本来就
  该是同一份。想留多份实时快照（`--live` 一天跑几遍，拿到的是几张不同的世界快照，文件名
  里带运行时刻）就指定目录：`... brief "…" --live --out live-briefs/am`。**不同**范围
  之间从不互相覆盖。
- 拒答也写文件（`refused-<短哈希>`），所以它**不会**盖掉你的日报。
- 系统只认自带档案里的 8 座矿山；不在其中的会**明确说"未覆盖"并列出可选项**，不会编一座矿出来。
- 覆盖范围、数据源取舍与已知缺口见 [README](README.md#数据源与取舍如实声明)。
