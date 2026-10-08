# 09: stdio 冒烟与宿主挂载

**What to build:** 三个 MCP server 能真的挂进 Claude Desktop / Cursor 手玩，并且 stdio 传输本身有一条会失败的测试守着。

这一刀补的是 ADR-0001 里**刻意接受的取舍**：默认路径走的是进程内协议连接，不覆盖 stdio 传输本身（进程边界、协议编码）。这条取舍的代价正是由本票补上——一个冒烟用例加一次真实的宿主挂载。

**Blocked by:** 04, 05

**Status:** ready-for-agent

**Category:** enhancement

- [ ] 仓库根目录的 `mcp-config.json` 与题面同名，Claude Desktop / Cursor 能直接识别并挂载
- [ ] 一条 stdio 冒烟用例：**真起子进程**、走 stdio 传输、把每个 server 的每个工具都调通
- [ ] 冒烟用例单独标记，不进默认离线套件（否则每条本地测试都要管进程启停与清理）
- [ ] 每个工具的返回类型注解即 outputSchema，宿主里能看到结构化参数与返回值
- [ ] 工具描述写清"何时用、返回什么"，人在宿主里不问文档也能上手
- [ ] stdout 只走协议，日志一律走 stderr（否则协议线被日志污染）
- [ ] 手工验证记录一次：在宿主里实际调用每个工具，结果与工具级用例一致
