"""跨层的异常词汇表。

这里只放**需要被多层识别**的异常。区分它们的，是"错了该怪谁"：

- `ReplayMiss` —— 怪**我们自己**：回放录播里没有这份数据。开发期的不变量被打破了，
  必须响亮地失败。一份"看起来正常、其实在说源故障"的日报，比一次崩溃危险得多：
  它会让人去查一个根本没坏的网站。
- `ToolCallFailed` —— 怪**工具链**：进程起不来、协议握手失败。按 ADR-0006，这是
  fetch 节点该兜住的东西，降级成信封、第 6 节如实记录。

`ReplayMiss` 与 `BrowserUnavailable` 是"怪我们自己"的两副面孔：前者是"我们的录播
集不全"，后者是"我们的运行环境缺浏览器"。二者的共同点是**都不许被降级信封吸收**
（降级会让一次环境故障伪装成"这个数据源没数据"），所以它们共用一个基类
`LoudFailure` —— 该响亮失败的错，捕获方一次就能认全。

这条分界必须**跨进程**成立：adapter 跑在 MCP server 里，图跑在客户端。MCP 协议
本身不传异常类型，所以每个 `LoudFailure` 的消息带一个固定哨兵串，客户端那边认它
（见 `agent/toolkit.py`）。这是唯一一处靠字符串传递语义的地方，所以哨兵是常量、
两边都引用同一个名字，而不是各写各的字面量。
"""

from __future__ import annotations

REPLAY_MISS_SENTINEL = "「回放数据缺失」"
"""跨 MCP 进程边界识别 `ReplayMiss` 的标记。**不要改它的一半。**"""

BROWSER_UNAVAILABLE_SENTINEL = "「无头浏览器不可用」"
"""跨 MCP 进程边界识别 `BrowserUnavailable` 的标记。**不要改它的一半。**"""


class MiningBriefError(RuntimeError):
    """本项目的异常基类，便于 CLI 边界一次性区分"我们自己的错"与别的错。"""


class LoudFailure(MiningBriefError):
    """**不许被降级信封吸收**、也不许重试的一类错 —— 错了该怪我们自己。

    两个成员：`ReplayMiss`（录播集不全）与 `BrowserUnavailable`（环境缺浏览器）。
    把它们收在一个基类下，是因为捕获点要表达的是同一件事："这不是数据源的问题，
    别把它降级成'数据缺失'。" 分开写两份 `except` 迟早会漏掉一处，而漏掉的那一处
    正好就是"数据缺失伪装成源没数据"的事故现场。
    """


class ReplayMiss(LoudFailure):
    """回放时找不到需要的数据。

    **不许被降级信封吸收，也不许回退真实网络。** 悄悄降级会让"离线确定性"变成
    薛定谔的绿；悄悄联网则会让"回放"这个词失去意义（ADR-0002 / ADR-0009）。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"{REPLAY_MISS_SENTINEL}{message}")


class BrowserUnavailable(LoudFailure):
    """需要无头浏览器，但这台机器上装不起来（缺 playwright 或缺浏览器二进制）。

    这条**必须响亮**：静默降级成"无数据"会让铜价缺失看起来像"LME 今天没发布"，
    把人送去查一个根本没坏的交易所。与 `ReplayMiss` 同一处置 —— 参见工单 04 的
    验收第 5 条与 ADR-0006 的边界（"工具自己坏了"不在此列）。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"{BROWSER_UNAVAILABLE_SENTINEL}{message}")


class ToolCallFailed(MiningBriefError):
    """一次工具调用失败了（工具自己报错，或传输层断了）。

    与 `ReplayMiss` 的区别：这个是可以降级的 —— 它描述的是"这次没取到"，
    不是"我们的录播集不全"。
    """
