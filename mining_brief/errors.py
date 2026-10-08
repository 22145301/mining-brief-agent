"""跨层的异常词汇表。

这里只放**需要被多层识别**的异常。区分它们的，是"错了该怪谁"：

- `ReplayMiss` —— 怪**我们自己**：回放录播里没有这份数据。开发期的不变量被打破了，
  必须响亮地失败。一份"看起来正常、其实在说源故障"的日报，比一次崩溃危险得多：
  它会让人去查一个根本没坏的网站。
- `ToolCallFailed` —— 怪**工具链**：进程起不来、协议握手失败。按 ADR-0006，这是
  fetch 节点该兜住的东西，降级成信封、第 6 节如实记录。

这条分界必须**跨进程**成立：adapter 跑在 MCP server 里，图跑在客户端。MCP 协议
本身不传异常类型，所以 `ReplayMiss` 的消息带一个固定哨兵串，客户端那边认它
（见 `agent/toolkit.py`）。这是唯一一处靠字符串传递语义的地方，所以哨兵是常量、
两边都引用同一个名字，而不是各写各的字面量。
"""

from __future__ import annotations

REPLAY_MISS_SENTINEL = "「回放数据缺失」"
"""跨 MCP 进程边界识别 `ReplayMiss` 的标记。**不要改它的一半。**"""


class MiningBriefError(RuntimeError):
    """本项目的异常基类，便于 CLI 边界一次性区分"我们自己的错"与别的错。"""


class ReplayMiss(MiningBriefError):
    """回放时找不到需要的数据。

    **不许被降级信封吸收，也不许回退真实网络。** 悄悄降级会让"离线确定性"变成
    薛定谔的绿；悄悄联网则会让"回放"这个词失去意义（ADR-0002 / ADR-0009）。
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"{REPLAY_MISS_SENTINEL}{message}")


class ToolCallFailed(MiningBriefError):
    """一次工具调用失败了（工具自己报错，或传输层断了）。

    与 `ReplayMiss` 的区别：这个是可以降级的 —— 它描述的是"这次没取到"，
    不是"我们的录播集不全"。
    """
