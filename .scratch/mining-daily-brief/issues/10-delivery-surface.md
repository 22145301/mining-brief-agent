# 10: 交付面

**What to build:** 陌生人 clone 下来 5 分钟内跑出日报，并且知道这个系统的数据边界在哪。

`docker compose up` 只起**一个** `brief` 服务（跑完即退，不是常驻服务）。它之所以成立，是因为回放模式**不需要任何 API key、不联网、结果确定**（冻时钟 + 按输入哈希取录播）——所以没有凭证的人也跑得出日报。

**Blocked by:** 04, 05, 07

**Status:** ready-for-agent

**Category:** enhancement

- [ ] `docker compose up` 单条命令跑完整链路，日报落在挂载出来的目录里
- [ ] 容器路径不需要任何 API key、不联网，同一输入两次跑结果一致
- [ ] 镜像默认 slim；浏览器进可选 extra，缺浏览器时明确报错而非静默降级
- [ ] `RUN.md` 是题面点名的 5 分钟通道：clone → `docker compose up` → 产物在哪，随后才是三条本地命令
- [ ] `README.md` 是门面：项目是什么、架构一页、装 / 跑 / 测三条命令、CI badge、指向 `docs/adr/`
- [ ] README 第一屏显眼处指向 `RUN.md`，两者**不复制内容**
- [ ] 数据源取舍如实声明：Platts IODEX / Mysteel / SMM / Fastmarkets 全是付费墙；LME 实时价需机构注册，只能用官网延迟收盘价；铜的备选 SHFE 未采用及原因；铁矿石是"知难而选的妥协项"（主流铁矿公司走 20-F、不出 NI 43-101）
- [ ] 术语声明记一笔：题面把 Indicated / Inferred 称作"储量"是笔误，产出物节标题沿用题面措辞、节内严格区分资源量与储量
- [ ] 风险规则集的收窄如实声明（只保留能逐字引到权威原文的）
- [ ] 一条"零配置冷启动"用例：不设任何环境变量、不联网，跑通并产出日报
