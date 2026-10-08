"""把一次请求从"一句话"推到"一个文件"。

这一层是**唯一知道要装配哪些部件**的地方：settings → LLM 客户端、toolkit、
回放时钟 → 图 → 落盘。节点与图都不知道自己跑在哪种模式下。

`--live` 与默认回放的差别全在 `Settings` 上（ADR-0003 / ADR-0009），这里一行
都不用改 —— 这不是巧合，是那两个开关存在的目的。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mining_brief.agent.graph import Graph, default_graph
from mining_brief.agent.llm import LLMClient, LLMRecorder, build_llm_client
from mining_brief.agent.render import write_brief
from mining_brief.agent.state import BriefState
from mining_brief.agent.toolkit import ToolKit, default_toolkit
from mining_brief.config.logging import get_logger
from mining_brief.config.settings import Settings
from mining_brief.contracts import BriefResult
from mining_brief.servers.runtime import Runtime

log = get_logger(__name__)


def resolve_now(settings: Settings, *, fixture_root: Path | str = "fixtures") -> datetime:
    """回放模式下的"现在"。

    刻意走 `Runtime` 而不是 `datetime.now()` —— 让"回放里没有系统时钟"这条规矩
    只有一个实现点，避免哪天有人在别处顺手写了个 `datetime.now()`。
    """
    return Runtime(settings, fixture_root=fixture_root).now()


async def run_brief(
    request_text: str,
    *,
    settings: Settings | None = None,
    fixture_root: Path | str = "fixtures",
    llm_root: Path | str = "fixtures/llm",
    toolkit: ToolKit | None = None,
    llm: LLMClient | None = None,
    graph: Graph | None = None,
    recorder: LLMRecorder | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> BriefResult:
    """跑完一次日报。

    `toolkit` / `llm` / `graph` 可注入，是为了让测试能换掉真实网络与模型，
    **而不是**为了让生产路径有多种走法 —— 默认值就是唯一的生产装配。
    """
    settings = settings or Settings.from_env()

    state: BriefState = {
        "request_text": request_text,
        "now": now or resolve_now(settings, fixture_root=fixture_root),
        "settings": settings,
        "llm": llm or build_llm_client(settings, fixture_root=llm_root, recorder=recorder),
        "toolkit": toolkit or default_toolkit(),
    }

    log.info(
        "brief.start",
        request=request_text,
        data_mode=settings.data_mode,
        llm_mode=settings.llm_mode,
        now=state["now"].isoformat(),
    )

    final: BriefState = await (graph or default_graph()).ainvoke(state)  # type: ignore[assignment]

    result = final["result"]
    assert result is not None, "render 节点必须产出 result"

    if write:
        resolved = write_brief(result)
        result = result.model_copy(update={"output_path": resolved})

    log.info(
        "brief.done",
        refusal=result.refusal is not None,
        sections=len(result.sections),
        citations=len(result.citations),
        path=result.output_path,
    )
    return result
