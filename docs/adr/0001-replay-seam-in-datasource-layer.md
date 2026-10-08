# 回放模式真走 MCP 协议，但默认不起子进程；fixture 落在 server 内部的数据源层

生成简报的默认（回放）模式照常调用三个 MCP server、照常走 MCP 协议（用 SDK 的**进程内协议连接**），`--live` 与回放只差一个环境变量（`MINING_DATA_MODE`），由 server 内部的数据源层决定读 fixture 还是抓网络。调用方（LangGraph 图）在两种模式下**一行都不用改**。

stdio 传输（真起子进程）由两处验证：一个冒烟用例，以及 `mcp-config.json` 挂进 Claude Desktop / Cursor —— 后者本来就是题面要求的交付项。

## Considered Options

- **默认也起 stdio 子进程**：连传输层都被默认回归覆盖，最真实。否决原因是成本不成比例 —— 会让每个端到端测试都要管子进程的启停、超时与清理，而"走 MCP 协议"与"起子进程"是**两件可以分开的事**（SDK 的进程内连接同样走完整协议，请求响应照常序列化，只是传输层换成内存流）。
- **client 侧假 transport**（把录下来的工具返回值喂给假 MCP client，连 server 代码都不跑）：跑得更快，但默认路径会跳过抓取与解析两层 —— 而这恰恰是断言最密的地方。收益砍半。
- **默认直接调 Python 函数，MCP server 只作演示外壳**：最简单最快。否决，因为默认 `pytest` 完全不经过 MCP，PRD §6.4"MCP 不是装饰"这条主张就无法在默认路径上自证 —— 只能说"`--live` 时确实走"。

## Consequences

- 默认路径**不覆盖 stdio 传输本身**（进程边界、协议编码）。这是刻意接受的取舍，用冒烟用例 + 宿主挂载两项补上。
- PDF server 的 fixture 是**已抽好的 JSON**而非 PDF 本身（PRD §10：二进制不入库，约 130 MB 且受版权保护）。所以默认路径覆盖的是"读冻结 JSON → `ResourceTable`"这一段，"真下载真解析"归 `@pytest.mark.network` 用例（PRD §13 R4）。
- 工具级单测与端到端测试都走同一个进程内连接，因此 A2 那批断言不需要任何进程管理代码。
