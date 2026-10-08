"""图的拓扑 —— 一句话说完的形状：

    START → parse_intent → resolve_entities → check_scope
                                                  │
                        ┌─────────────────────────┴─────────────────────────┐
                        │ 拒答                                                │ 有范围
                        ▼                                                    ▼
                     render                            ┌─────────┬──────────┬───────────┐
                        │                           fetch_news fetch_prices fetch_resources
                        │                             └─────────┴──────────┴───────────┘
                        │                                                     │
                        │                                             compute_signals
                        │                                                     │
                        │                                                 assemble
                        │                                                     │
                        │                                                  narrate
                        │                                                     │
                        │                                             verify_citations
                        └─────────────────────────────────────────────────────┤
                                                                              ▼
                                                                            render → END

两个刻意的地方：

1. **三路扇出是静态的**（`add_conditional_edges` 一次性给出三个目标），不是运行
   时按节点返回值决定的。图脊的形状应该能一眼看出来。
2. **拒答与正常路径汇入同一个 `render` 节点**。拒答不是异常，它同样有产物
   （一份说清"为什么不行"的文件），只是没有六节而已。给它单开一条旁路会让
   "产物"这个概念裂成两个。
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mining_brief.agent import nodes
from mining_brief.agent.state import BriefState

#: 节点名 → 实现。顺序即阅读顺序。
NODE_TABLE = {
    "parse_intent": nodes.parse_intent,
    "resolve_entities": nodes.resolve_entities,
    "check_scope": nodes.check_scope,
    "fetch_news": nodes.fetch_news,
    "fetch_prices": nodes.fetch_prices,
    "fetch_resources": nodes.fetch_resources,
    "compute_signals": nodes.compute_signals,
    "assemble": nodes.assemble,
    "narrate": nodes.narrate,
    "verify_citations": nodes.verify_citations,
    "render": nodes.render,
}

#: 三路并行取数。顺序按 PRD §5.1 的节序排，与并发无关。
FAN_OUT = ("fetch_news", "fetch_prices", "fetch_resources")

#: langgraph 的图是四参数泛型 `(StateT, ContextT, InputT, OutputT)`。本项目不用
#: 运行时 context、也不做输入/输出转换，所以三个槽位都填同一个 `BriefState`。
#: 写成别名是为了让"这四个参数其实是同一件事"一眼可见。
Graph = CompiledStateGraph[BriefState, None, BriefState, BriefState]


def build_graph() -> Graph:
    graph: StateGraph[BriefState, None, BriefState, BriefState] = StateGraph(BriefState)

    for name, node in NODE_TABLE.items():
        graph.add_node(name, node)

    graph.add_edge(START, "parse_intent")
    graph.add_edge("parse_intent", "resolve_entities")
    graph.add_edge("resolve_entities", "check_scope")

    graph.add_conditional_edges("check_scope", nodes.route_after_scope, [*FAN_OUT, "render"])

    # 三路汇入同一节点：三条边都在同一个 superstep 里完成，`compute_signals`
    # 因此拿得到三份结果。
    for fetch in FAN_OUT:
        graph.add_edge(fetch, "compute_signals")

    graph.add_edge("compute_signals", "assemble")
    graph.add_edge("assemble", "narrate")
    graph.add_edge("narrate", "verify_citations")
    graph.add_edge("verify_citations", "render")
    graph.add_edge("render", END)

    return graph.compile()


@lru_cache(maxsize=1)
def default_graph() -> Graph:
    """编译一次、复用。图是不可变的，重复编译只是浪费。"""
    return build_graph()
