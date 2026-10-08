"""储量数据源：从技术报告 PDF 里抽资源量 / 储量表（工单 05）。

分三层，与价格那条链路同构（ADR-0003）：

1. **PDF 字节 → 逐页文本**（`pages_from_pdf_bytes`，唯一碰 pypdf 的地方）；
2. **逐页文本 + 登记表 → `ResourceTable`**（`parse_resource_table`，**纯函数**，
   拿抽好的文本就能单测，不需要 PDF、不需要网络）；
3. **adapter 只做编排**。

回放模式下 fixture 是**已抽好的 JSON**，不是 PDF 本身（ADR-0001）：二进制不入库
（约 10–130 MB 且受版权保护）。所以默认路径覆盖的是"读冻结 JSON → `ResourceTable`"
这一段，"真下载真解析"归 `@pytest.mark.network` 用例。

**关于 ground truth 的一句话必须写在这里**：冻结 JSON 是解析器的**输出**，人核对之前
它不是事实，只是"解析器当时读出来的东西"。`FrozenExtract.human_verified` 字段就是
为这件事存在的 —— 在它变成 `true` 之前，回放用例证明的是"解析器没有回归"，
**不是**"这些数字对"。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from mining_brief.config.reports import REPORT_SOURCES, ReportSource, source_by_pdf_url
from mining_brief.contracts import (
    FetchStatus,
    PageRef,
    RawResponse,
    ResourceCategory,
    ResourceExtract,
    ResourceRow,
    ResourceTable,
)
from mining_brief.datasources.fetchers import Fetcher
from mining_brief.errors import LoudFailure, ReplayMiss

DEFAULT_RESOURCE_DIR = Path("fixtures/resources")


# ---------------------------------------------------------------------------
# 1. PDF 字节 → 逐页文本
# ---------------------------------------------------------------------------


class PdfSupportMissing(LoudFailure):
    """没装 PDF 解析依赖。

    与"这份 PDF 读不出表"是两件完全不同的事：前者是我们的环境不对（要炸穿，
    让人去装 `--extra pdf`），后者是这份文件的问题（降级成"抽不到"，如实记）。
    混成一句话，就会出现"以为报告没数据，其实是没装库"。
    """


def pages_from_pdf_bytes(body: bytes) -> tuple[tuple[int, str], ...]:
    """逐页抽文本，**带上页码**（1 起）。

    页码不是附赠品：`PageRef` 的全部意义就是让人能翻到那一页自己核（User Story 17）。
    丢了页码，产物里的数字就只能靠信。
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 取决于环境是否装了 extra
        raise PdfSupportMissing(
            "需要 PDF 解析，但 pypdf 没装。请 `uv sync --all-extras`（或 `--extra pdf`）。"
        ) from exc

    import io

    reader = PdfReader(io.BytesIO(body))
    return tuple((index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages))


# ---------------------------------------------------------------------------
# 2. 逐页文本 → ResourceTable（纯函数）
# ---------------------------------------------------------------------------

#: 法定类别词 → 枚举。**只有这五个**，小写匹配。
#:
#: 判据是"这一行的第一个词是不是法定类别词"。这不是偷懒：题面要求的正是"每个数字
#: 标类别"，而 PDF 里表格没有结构，唯一稳定可用的锚就是这些法定词 —— 它们不能
#: 被随意改写（JORC Clause 12 / NI 43-101 s.2.3 都对用词有硬要求，见
#: `docs/risk-rules.md` 的 R5）。
_CATEGORY_BY_TOKEN: dict[str, ResourceCategory] = {
    "measured": ResourceCategory.MEASURED,
    "indicated": ResourceCategory.INDICATED,
    "inferred": ResourceCategory.INFERRED,
    "proven": ResourceCategory.PROVEN,
    "probable": ResourceCategory.PROBABLE,
}

_NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")

#: 换算后保留的小数位。`33_380_000 × 1e-6` 在二进制浮点下是 `33.379999999999995`，
#: 直接印出去会让人以为我们算出了十三位有效数字。6 位远超任何一份报告的有效位数
#: （吨位给到百万吨级、品位给到两位小数），同时又不会把 `107.991` 这类真值切掉。
_VALUE_DECIMALS = 6


def _as_float(token: str) -> float | None:
    """千分位逗号会去掉；`-`、`–`、空、以及任何非纯数字都判为"不是数字"。

    判为 `None` 而不是 0 是要紧的：资源量表里 `-` 的意思是"这一类为零/未估算"，
    把它读成 0 就会在日报上印出"推断资源量 0 百万吨"—— 一个假得毫无破绽的数字。
    """
    cleaned = token.replace(",", "").replace(" ", "").strip()
    if not _NUMERIC.fullmatch(cleaned):
        return None
    return float(cleaned)


def _row_from_line(line: str, column_count: int) -> tuple[ResourceCategory, list[float]] | None:
    """一行文本 → （类别，N 个数字），不是数据行就返回 `None`。

    **要求恰好 `column_count` 个数字**，多一个少一个都不认。这条严格性是这个解析器
    最要紧的防线：同一页上往往还有别的表（PMET 那份第 41 页就另有一张"铯带"表，
    同样以 `Indicated` / `Inferred` 开头，只是少一列）。靠列数把它们分开，
    比靠"表头在哪一行"稳 —— 文本抽取后表头与数据行的先后顺序并不可靠。
    """
    tokens = line.split()
    if len(tokens) != column_count + 1:
        return None
    category = _CATEGORY_BY_TOKEN.get(tokens[0].strip(":：.,").lower())
    if category is None:
        return None
    values = [_as_float(token) for token in tokens[1:]]
    if any(value is None for value in values):
        return None
    return category, [value for value in values if value is not None]


def _row_to_contract(
    category: ResourceCategory, values: Sequence[float], source: ReportSource
) -> ResourceRow:
    """按登记表声明的列序，把数字放到契约字段上。

    吨位与品位从**声明**取单位、从**页面**取数字。这个分工是刻意的：单位错了（比如
    把 `Mt` 读成 `t`，差一百万倍）是这一层最容易犯又最难发现的错，所以它由人声明、
    由人核对；解析器不猜单位。
    """
    tonnage = grade = contained = None
    grade_unit = None
    for column, value in zip(source.columns, values, strict=True):
        scaled = round(value * column.scale, _VALUE_DECIMALS)
        if column.role == "tonnage":
            tonnage = scaled
        elif column.role == "grade":
            grade = scaled
            grade_unit = column.unit
        elif column.role == "contained":
            contained = scaled

    return ResourceRow(
        category=category,
        tonnage_mt=tonnage,
        grade=grade,
        grade_unit=grade_unit,
        contained=contained,
    )


def find_total_row(pages: Sequence[tuple[int, str]], source: ReportSource) -> list[float] | None:
    """找出页面上那行 `Total` 的吨位 —— **供交叉核对用，不进产物**。

    为什么值得单独写一个函数：它是这张卡片上唯一一个**不是解析器算出来的**参照物。
    各分类行相加若等于页面自己给的合计，说明我们读的是同一张表、同样的列 ——
    这正是价格那条链路用"GFEX 官方 vs 新浪转载"做的跨源核对，只是这里的两边都在
    同一页上。没有它，回放用例只能证明"解析器这次和上次读得一样"。

    `Total` 不是一个法定类别词（JORC Clause 12 要求公开报告只使用法定术语，而
    "Total" 只是排版上的合计），所以它**不能**进 `rows` —— 进去就会让
    "各类别相加"变成"各类别 + 合计"，翻倍。这里只把它取出来做比对。
    """
    for _page_number, text in pages:
        if source.header_marker.lower() not in text.lower():
            continue
        for line in text.splitlines():
            tokens = line.split()
            if len(tokens) != len(source.columns) + 1:
                continue
            if tokens[0].strip(":：.,").lower() != "total":
                continue
            values = [_as_float(token) for token in tokens[1:]]
            if any(value is None for value in values):
                continue
            numbers = [value for value in values if value is not None]
            tonnage_index = next(
                (i for i, column in enumerate(source.columns) if column.role == "tonnage"), None
            )
            if tonnage_index is None:
                continue
            scale = source.columns[tonnage_index].scale
            return [round(value * scale, _VALUE_DECIMALS) for value in numbers]
    return None


def parse_resource_table(
    pages: Sequence[tuple[int, str]], source: ReportSource
) -> ResourceTable | None:
    """逐页文本 + 登记表 → 一张资源量表。**抽不到就返回 `None`**。

    抽不到**不是错误**：一个项目可能压根没报告、报告里可能只有正文没有表、版式也可能
    改过。返回 `None` 让调用方如实记"数据缺失"，比抛异常好 —— 抛异常会把"这份文件
    里没有表"变成一次链路故障，而它其实是这条链路正常工作的结果。

    抽到**半张表**才是灾难，所以每一处不肯定的地方都选择放弃整张表：
    - 表头标记不在这一页 → 这页不算；
    - 行里的数字个数与声明的列数不符 → 这行不算。
    """
    for page_number, text in pages:
        if source.header_marker.lower() not in text.lower():
            continue

        rows: list[ResourceRow] = []
        refs: list[PageRef] = []
        for line in text.splitlines():
            parsed = _row_from_line(line, len(source.columns))
            if parsed is None:
                continue
            category, values = parsed
            rows.append(_row_to_contract(category, values, source))
            refs.append(PageRef(label=f"{source.title} · {category.value} 行", page=page_number))

        if not rows:
            # 这一页有标记却没有一行合格 —— 说明我们认错了页，或者行结构变了。
            # 继续往后找，但**不**把这张半成品交出去。
            continue

        refs.append(
            PageRef(
                label=f"{source.title} · 表头（{source.header_marker}）",
                page=page_number,
            )
        )
        return ResourceTable(
            pdf_url=source.pdf_url,
            report_title=source.title,
            report_date=source.report_date,
            standard=source.standard,
            project=source.project,
            commodity=source.commodity,
            rows=tuple(rows),
            page_refs=tuple(refs),
        )
    return None


# ---------------------------------------------------------------------------
# 3. 冻结抽取值（回放）与真下载（实时）
# ---------------------------------------------------------------------------


class FrozenExtractMissing(ReplayMiss):
    """回放时找不到某个 PDF 的冻结抽取结果。

    响亮失败，理由与 `FixtureMissing` 相同：悄悄降级成"数据缺失"会让人去查一份
    根本没问题的报告（ADR-0002 / ADR-0009）。
    """


class ResourceSource(Protocol):
    async def extract(self, pdf_url: str) -> tuple[ResourceTable | None, str | None]:
        """返回（表, 失败说明）。两者必有一个是 `None`。"""
        ...


@dataclass(frozen=True)
class FrozenExtract:
    """一份已抽好的结果 + 它自称的出身。

    `human_verified` 是这张卡片上最重要的一栏：`False` 表示这些数字**只被人以外
    的东西读过一遍**，回放用例因此只能证明"解析器没回归"，不能证明"数字对"。
    """

    pdf_url: str
    pdf_sha256: str
    pdf_bytes: int
    parsed_at: str
    human_verified: bool
    table: ResourceTable | None

    pages: tuple[tuple[int, str], ...] = ()
    """解析时用过的那几页的**原文**（只有含表头标记的那几页，通常一两页）。

    为什么把这几页的文本也冻进来，而不是只冻结果：只冻结果的话，离线能测的最多是
    "读到的东西与上次一样"，解析器本身一行都没被跑过。有了这几页原文，
    `parse_resource_table` 就能在离线下被**重跑**并断言它重现出 `table` —— 这才
    是"解析器没有回归"的真正证据。

    为什么不干脆只冻文本、用时再解析：那样 `table` 就不是冻结值而是派生值了，
    ADR-0002 的"回放比冻结值"当场失效 —— 解析器一改，回放结果跟着变，
    而它本该是那条不许动的基线。
    """

    @property
    def note(self) -> str:
        if self.human_verified:
            return "已人工核对"
        return "未经人工核对 —— 由解析器输出冻结而来，仅用于回归，不构成事实"


def load_frozen_extracts(root: Path | str = DEFAULT_RESOURCE_DIR) -> tuple[FrozenExtract, ...]:
    """把 `fixtures/resources/*.json` 全读出来。"""
    directory = Path(root)
    if not directory.exists():
        return ()
    extracts: list[FrozenExtract] = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text("utf-8"))
        table_payload = payload.get("table")
        page_text: Mapping[str, str] = payload.get("page_text") or {}
        extracts.append(
            FrozenExtract(
                pdf_url=str(payload["pdf_url"]),
                pdf_sha256=str(payload["pdf_sha256"]),
                pdf_bytes=int(payload["pdf_bytes"]),
                parsed_at=str(payload["parsed_at"]),
                human_verified=bool(payload["human_verified"]),
                table=ResourceTable.model_validate(table_payload) if table_payload else None,
                pages=tuple(sorted((int(n), str(t)) for n, t in page_text.items())),
            )
        )
    return tuple(extracts)


class FrozenResourceSource:
    """回放：读冻结的抽取结果（ADR-0001）。**绝不回退真实网络**。"""

    def __init__(self, root: Path | str = DEFAULT_RESOURCE_DIR) -> None:
        self._by_url = {extract.pdf_url: extract for extract in load_frozen_extracts(root)}

    async def extract(self, pdf_url: str) -> tuple[ResourceTable | None, str | None]:
        extract = self._by_url.get(pdf_url)
        if extract is None:
            known = "\n  ".join(sorted(self._by_url)) or "(空)"
            raise FrozenExtractMissing(
                f"回放模式找不到这个 PDF 的冻结抽取结果：{pdf_url}\n"
                f"已有：\n  {known}\n"
                "缺就重跑 scripts/extract_resources.py —— **不回退真实网络**。"
            )
        return extract.table, None


class LiveResourceSource:
    """实时：下载 PDF → 逐页抽文本 → 解析。"""

    def __init__(self, fetcher: Fetcher, sources: Mapping[str, ReportSource] | None = None) -> None:
        self._fetcher = fetcher
        self._sources = dict(sources) if sources is not None else dict(REPORT_SOURCES)

    async def extract(self, pdf_url: str) -> tuple[ResourceTable | None, str | None]:
        source = source_by_pdf_url(pdf_url) or next(
            (s for s in self._sources.values() if s.pdf_url == pdf_url), None
        )
        if source is None:
            # 没有登记表就不知道表的列序 —— 硬猜列序等于编数字。如实说"没登记"。
            return None, (
                f"这份 PDF 没有登记在 config/reports.py 里，因此不知道它表的列序，"
                f"不做解析（{pdf_url}）。"
            )

        try:
            raw: RawResponse = await self._fetcher.fetch(pdf_url)
        except LoudFailure:
            raise
        except Exception as exc:
            return None, f"技术报告下载失败：{type(exc).__name__}"

        if not raw.ok:
            return None, f"技术报告返回 HTTP {raw.status}，本次未能取到。"

        try:
            pages = pages_from_pdf_bytes(raw.body)
        except PdfSupportMissing:
            # 我们的环境不对（没装 pypdf）—— 与"这份文件读不出来"是两件事，
            # 不许混成一句降级说明（见 `PdfSupportMissing` 的 docstring）。
            raise
        except Exception as exc:
            # 服务器回了个 200 但不是 PDF 的东西（错误页、登录跳转的 HTML）——
            # 这是**源侧**给了坏文件，如实降级，不炸穿。
            return None, (
                f"技术报告取回来了，但它不是能解析的 PDF（{type(exc).__name__}），"
                f"本次未能得到数据。"
            )

        return parse_resource_table(pages, source), None


def build_resource_source(
    *,
    data_mode: str,
    fetcher: Fetcher,
    resource_dir: Path | str = DEFAULT_RESOURCE_DIR,
    sources: Mapping[str, ReportSource] | None = None,
) -> ResourceSource:
    """按模式挑一个 `ResourceSource` —— 数据层里**唯一**出现模式判断的地方（ADR-0003）。"""
    if data_mode == "replay":
        return FrozenResourceSource(resource_dir)
    return LiveResourceSource(fetcher, sources)


# ---------------------------------------------------------------------------
# adapter：只做编排
# ---------------------------------------------------------------------------


class ResourceAdapter:
    """`mineral-pdf-mcp` 背后的业务逻辑。它不判断自己跑在哪种模式下。"""

    def __init__(self, source: ResourceSource) -> None:
        self._source = source

    async def extract_resources(self, pdf_url: str, now: datetime) -> ResourceExtract:
        if not pdf_url.strip():
            raise ValueError("pdf_url 不能为空")

        table, failure = await self._source.extract(pdf_url)
        if failure is not None:
            return ResourceExtract(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=failure,
                retrieved_at=now,
                table=None,
            )
        if table is None:
            # 这里**不**用 EMPTY。EMPTY 的含义是"源可达，且我们成功地判定确实没有
            # 符合范围的数据"——而"打了开一份报告却认不出它的表"绝大多数时候是
            # **我们**读不出来（版式变了、列数变了），不是这份报告真的没有资源量。
            # 记成 EMTPY 就等于把我们的解析失败说成"这个项目没有资源量"，
            # 那正是 ADR-0005 花力气分开这两种情形的理由。
            return ResourceExtract(
                status="degraded",
                source_status=FetchStatus.UNAVAILABLE,
                reason=(
                    "这份技术报告里没有抽到资源量 / 储量表 —— 版式可能已改，"
                    "或它本来就不含表。已取到文件但未得到任何一行合格数据。"
                ),
                retrieved_at=now,
                table=None,
            )
        return ResourceExtract(
            status="ok",
            source_status=FetchStatus.OK,
            retrieved_at=now,
            table=table,
        )
