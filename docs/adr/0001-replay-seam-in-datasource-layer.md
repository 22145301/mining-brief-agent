# 回放模式真走 MCP 子进程，fixture 落在 server 内部的数据源层

生成简报的默认（回放）模式照常启动三个 MCP stdio 子进程、照常走 MCP 协议；回放与 `--live` 只差一个环境变量（`MINING_DATA_MODE`），由子进程内部的数据源层决定读 fixture 还是抓网络。调用方（LangGraph 图与 MCP client）在两种模式下**一行都不用改**。

## Considered Options

- **client 侧假 transport**（把录下来的工具返回值喂给假 MCP client，不起子进程）：跑得更快，但默认路径会跳过抓取与解析两层 —— 而这两层恰恰是断言最密的地方（关键词分流、储量表 ground truth、逐字引用）。收益砍半。
- **默认不起子进程，agent 直接 import 同一份 Python 实现**（MCP server 只作演示外壳）：最简单最快，但默认 `pytest` 完全不经过 MCP，PRD §6.4"MCP 不是装饰"这条主张就无法在默认路径上自证 —— 只能说"`--live` 时确实走"。

## Consequences

- 端到端用例需要管三个子进程的生命周期（启动、超时、清理）；工具级单测改用 MCP SDK 的 in-memory session，同进程不起子进程，因此只有端到端那**一个**用例承担这个成本。
- PDF server 的 fixture 是**已抽好的 JSON**而非 PDF 本身（PRD §10：二进制不入库，约 130 MB 且受版权保护）。所以默认路径覆盖的是"读冻结 JSON → `ResourceTable`"这一段，"真下载真解析"归 `@pytest.mark.network` 用例（PRD §13 R4）。
