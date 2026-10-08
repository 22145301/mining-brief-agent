# 10: 交付面

**What to build:** 陌生人 clone 下来 5 分钟内跑出日报，并且知道这个系统的数据边界在哪。

`docker compose up` 只起**一个** `brief` 服务（跑完即退，不是常驻服务）。它之所以成立，是因为回放模式**不需要任何 API key、不联网、结果确定**（冻时钟 + 按输入哈希取录播）——所以没有凭证的人也跑得出日报。

**Blocked by:** 04, 05, 07

**Status:** done

**Category:** enhancement

- [x] `docker compose up` 单条命令跑完整链路，日报落在挂载出来的目录里
- [x] 容器路径不需要任何 API key、不联网，同一输入两次跑结果一致
- [x] 镜像默认 slim；浏览器进可选 extra，缺浏览器时明确报错而非静默降级
- [x] `RUN.md` 是题面点名的 5 分钟通道：clone → `docker compose up` → 产物在哪，随后才是三条本地命令
- [x] `README.md` 是门面：项目是什么、架构一页、装 / 跑 / 测三条命令、CI badge、指向 `docs/adr/`
- [x] README 第一屏显眼处指向 `RUN.md`，两者**不复制内容**
- [x] 数据源取舍如实声明：Platts IODEX / Mysteel / SMM / Fastmarkets 全是付费墙；LME 实时价需机构注册，只能用官网延迟收盘价；铜的备选 SHFE 未采用及原因；铁矿石是"知难而选的妥协项"（主流铁矿公司走 20-F、不出 NI 43-101）
- [x] 术语声明记一笔：题面把 Indicated / Inferred 称作"储量"是笔误，产出物节标题沿用题面措辞、节内严格区分资源量与储量
- [x] 风险规则集的收窄如实声明（只保留能逐字引到权威原文的）
- [x] 一条"零配置冷启动"用例：不设任何环境变量、不联网，跑通并产出日报

---

## 完成情况

### 落了什么

- `Dockerfile`（单阶段、slim）+ `docker-compose.yml`（单服务、`name:` 显式）+ `.dockerignore`。
- `RUN.md`：题面点名的 5 分钟通道；README 第一屏指向它，两份文件**不重复正文**。
- README 补齐：CI badge、风险规则收窄声明、「开发闸门」四条命令、交付物表（Dockerfile /
  compose / risk-rules / `.env.example`）、回放只认录过输入这一条代价。
- `.env.example` 补 `MINING_FIXTURE_ROOT`（09 号工单引入、此前漏登记）。
- `tests/test_cli.py::test_cold_start_needs_no_environment_variables_at_all`：子进程、
  清空环境变量、cwd 不在仓库内。

### 实测记录

容器通道（跑完即退，产物落在挂载目录）：

```
$ docker compose build
 Image mining-brief:local Built
$ docker image ls mining-brief:local --format '{{.Size}}'
411MB

$ rm -f briefs/*.md && docker compose up
brief-1 | event='brief.start'  data_mode='replay' llm_mode='replay' now='2026-10-08T17:01:57.311481+00:00'
brief-1 | event='brief.written' path='/out/brief-2026-10-08.md'
brief-1 | event='brief.done' citations=9 refusal=False sections=6
brief-1 exited with code 0
$ sha256sum briefs/brief-2026-10-08.md
0928bd75d0d1056e704350eb040c76f43c9bf5ad4525eb9ac4701277b3120edf
```

**不联网**：把 compose 的网络摘掉重跑，产物哈希不变（`--network none`）。

```
$ docker run --rm --network none -v "D:/cxb/矿产/briefs:/out" mining-brief:local
/out/brief-2026-10-08.md
$ sha256sum briefs/brief-2026-10-08.md
0928bd75d0d1056e704350eb040c76f43c9bf5ad4525eb9ac4701277b3120edf
```

**同一输入两次跑一致**：上面 compose 与 `--network none` 两次、以及更早的两次，四次
哈希相同（去 black、重锁 `uv.lock` 之后又验了一次，仍相同 —— 依赖变化不该改产物）。

**换一句话问**（也是这两句让 09 号工单记的"拒答"路径在容器里可复现）：

```
$ docker compose run --rm brief mining-brief brief "帮我预测一下明天铜价会涨吗"
event='brief.done' citations=0 refusal=True sections=0
$ head -3 briefs/brief-2026-10-08.md
# 无法生成矿权日报
## 我听懂了什么
我听懂了：铜；时间窗口 7 天。

$ docker compose run --rm brief mining-brief brief "看看 Escondida 铜矿最近 3 天"
event='brief.done' refusal=True
「Escondida」不在本系统的矿权档案里 —— 这是**未覆盖**，不是「这座矿不存在」。
档案内可选项：矿山 Pilgangoora、Mount Marion、Wodgina、Kamoa-Kakula、Quellaveco、
Los Pelambres、Gudai-Darri、Eliwana；矿种 锂、铜、铁矿石。
```

零配置冷启动（子进程、环境变量表清空、cwd 不在仓库内）：

```
$ env -u MINING_LLM_API_KEY uv run pytest -q tests/test_cli.py
3 passed, 2 warnings in 4.31s
```

全量闸门（与 CI 四条一致）：

```
$ uv run ruff check .            → All checks passed!
$ uv run ruff format --check .   → 66 files already formatted
$ uv run mypy                    → Success: no issues found in 63 source files
$ uv run pytest -q               → 234 passed, 11 deselected, 4 warnings in 17.57s
$ uv run pytest -q -m stdio      → 9 passed, 236 deselected, 4 warnings in 18.28s
```

### 三处判断

1. **CI 的格式化闸门从 black 换成 ruff format（去 black）。** 这是**这一票里最该被追问的
   取舍**，因为它同时改了 `pyproject.toml` / `uv.lock` / `ci.yml`。理由是一次实测：
   black 与 ruff format 对**推导式里的三元表达式**给出不同结果（black 要在里面再裹一层
   括号，ruff 不要），把任一方的输出交给另一方都会被打回。两个都挂不是"更严格"，是
   **没有唯一答案** —— CI 结论取决于谁先跑。留 ruff 是因为它同时是 lint 与 format 的唯一
   配置源。分歧的原始形态和实测过程写在 `pyproject.toml` 那段注释里，评审人可自行复核。
   （顺带把 stdio 那一档也加进了 CI：它不发网络请求，守的正是"挂进宿主取不到数据"这类
   最容易在别人机器上翻车的路径。）
2. **`RUN.md` 里"换一句话问"的例子原本是错的，改成已录播的样例句。** 初稿随手写了
   `"看看 Kamoa-Kakula 铜矿最近 3 天"`（Kamoa-Kakula 确实在档案里），但回放只认录过的
   输入 —— 实测这条命令报 `LLMReplayMiss`。**文档里的命令必须真跑过**，于是：
   例子换成两条已录播的句子（一句越界拒答、一句未覆盖拒答），并把"回放只认录过的话、
   缺录播时明确报错而不回退真实调用"写成 RUN.md 与 README 上的一句话。
   没有为它去重录 LLM：重录会把既有三条样例句的响应一起刷掉，产物与已验哈希全部作废，
   而收益只是多一句可离线问的话 —— 不值，且此刻换掉录播等于把已验证的东西重新变成未验证。
3. **拒答会覆盖上一次的产物文件名。** 拒答与日报都写 `brief-<数据时点>.md`，所以
   `docker compose run` 一次拒答会盖掉 `briefs/` 里的日报。这是**如实记下的既有行为**，
   没有偷偷改名去掩盖：文件名由 PRD §5.3 的命名约定与冻时钟共同决定，改它属于动契约。
   RUN.md 里给出规避方式（`--out briefs/refusals`）。

### 边界

- **`OWNER/REPO` 占位没替换**：仓库当前没有 git remote（还没推上去），badge 的 URL 只能
  留占位，README 里写明这是**全仓库唯一需要替换的地方**、何时替换。
- **Docker 通道只验到 Windows + Docker Desktop**（engine 29.7.2 / compose v5.5.1）。
  Linux 上按理一致（基础镜像是 debian slim），但没有第二台机器可验。
