"""储量数据源（工单 05）：解析器、交叉核对、冻结纪律、故障与 A7。

分四组，各自的"能证明什么"必须分清楚：

1. **解析器** —— 喂**真实页面的原文**（冻结在 `fixtures/resources/*.json` 的
   `page_text` 里），断言它重现出冻结的表。这证明的是"解析器没有回归"。
2. **交叉核对** —— 拿页面**自己印的**合计行、概述句、脚注去对表内各行相加的结果。
   这一组是唯一**不靠自证**的：两边都不是解析器算出来的。
3. **冻结纪律** —— `human_verified` 必须还是 `false`（人还没核过）、录播缺失必须
   响亮失败、`-` 不能被读成 0。
4. **故障路径** —— 源拒绝了、回的压根不是 PDF、报告里认不出表，各走各的处置。

第 1 组再强也**不构成"这些数字对"**：页原文与表都是同一个解析器先后读出来的。
这就是本票那条 ⛔ 人工核对卡点存在的原因，也是这个文件里没有任何一条断言可以
替代它的原因。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from mining_brief.config.archive import ARCHIVE
from mining_brief.config.reports import (
    PILBARA_CET,
    PMET_CV5_CV13,
    REPORT_SOURCES,
    ReportSource,
    source_by_pdf_url,
)
from mining_brief.config.settings import Settings
from mining_brief.contracts import (
    FetchStatus,
    RawResponse,
    ResourceCategory,
    ResourceKind,
    ResourceRow,
    ResourceTable,
)
from mining_brief.datasources.fetchers import FixtureFetcher
from mining_brief.datasources.fixtures import FixtureStore
from mining_brief.datasources.resources import (
    FrozenExtract,
    FrozenExtractMissing,
    FrozenResourceSource,
    LiveResourceSource,
    ResourceAdapter,
    build_resource_source,
    find_total_row,
    load_frozen_extracts,
    pages_from_pdf_bytes,
    parse_resource_table,
)
from mining_brief.errors import REPLAY_MISS_SENTINEL, BrowserUnavailable, LoudFailure, ReplayMiss

NOW = datetime(2026, 10, 8, 17, 1, 57, tzinfo=UTC)

#: 碳酸锂当量换算：Li2CO3(73.891) / Li2O(29.881)。用于 PMET 那份的"含金属量"核对 ——
#: 它的"含量"单位是 LCE 而不是 Li2O，所以恒等式里必须带这个系数。
LCE_FACTOR = 2.4728


def _resource_dir(fixture_root: Path) -> Path:
    return fixture_root / "resources"


def _payload(fixture_root: Path, source: ReportSource) -> dict[str, object]:
    path = _resource_dir(fixture_root) / f"{source.slug}.json"
    payload: dict[str, object] = json.loads(path.read_text("utf-8"))
    return payload


def _frozen(fixture_root: Path, source: ReportSource) -> FrozenExtract:
    """取出某份报告的冻结结果。**恰好一份**才算对 —— 多一份说明 URL 撞了。"""
    extracts = load_frozen_extracts(_resource_dir(fixture_root))
    found = [e for e in extracts if e.pdf_url == source.pdf_url]
    assert len(found) == 1, f"{source.slug} 的冻结结果不是恰好一份，找到 {len(found)}"
    return found[0]


def _index_of(source: ReportSource, role: str) -> int:
    for index, column in enumerate(source.columns):
        if column.role == role:
            return index
    raise AssertionError(f"{source.slug} 的登记表里没有 {role} 列")


def _index_by_name(source: ReportSource, name: str) -> int:
    for index, column in enumerate(source.columns):
        if column.name == name:
            return index
    raise AssertionError(f"{source.slug} 的登记表里没有名为 {name} 的列")


#: 页面把"含量"印到小数点后一位，所以"含量 = 吨位 × 品位"只在一个末位单位之内成立
#: （理由见 `test_contained_metal_tracks_tonnage_times_grade_when_the_units_match`）。
CONTAINED_PRECISION = 0.1


def _contained_disagreements(rows: Sequence[ResourceRow], precision: float) -> list[str]:
    """挑出**对不上**的行，返回它们的说明；空列表 = 全部通过。

    抽成一个函数是为了让"这个容差还抓不抓得住挑反"能被**真的跑一遍**
    （`test_the_loose_contained_check_still_has_teeth`），而不是只写在注释里。
    注释里的"会红"不是证据 —— 只有跑过才是。
    """
    bad: list[str] = []
    for row in rows:
        if row.tonnage_mt is None or row.grade is None or row.contained is None:
            bad.append(f"{row.category} 行缺字段，算不了")
            continue
        expected = row.tonnage_mt * row.grade / 100
        # 浮点尾巴只吸收到手：`abs(1.0 - 1.1)` 是 `0.10000000000000009`，不吸收就
        # 会在容差边界上假红。余下的余量才是页面自己的取整，不是我们的。
        if abs(row.contained - expected) > precision + 1e-9:
            bad.append(f"{row.category}：页面印 {row.contained}，吨位 × 品位得 {expected}")
    return bad


# ---------------------------------------------------------------------------
# 1. 解析器：喂真实页原文，重现冻结的表
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", sorted(REPORT_SOURCES))
def test_the_parser_reproduces_the_frozen_table_from_the_frozen_pages(
    fixture_root: Path, slug: str
) -> None:
    """把冻结的**页原文**重新喂进解析器，必须逐字段重现出冻结的表。

    这是默认（离线）路径能给出的最强证据。它证明不了数字对（页原文与表都是这个
    解析器读出来的），但它证明解析器在两次读之间没有漂 —— 否则"回放产出同一份
    日报"这件事会静默失效。

    断言前提本身也重要：`pages` 空的话这条测试会变成一句永远成立的空话。
    """
    source = REPORT_SOURCES[slug]
    extract = _frozen(fixture_root, source)

    assert extract.pages, "页原文没冻结，这条断言就是在空转"
    assert extract.table is not None
    assert parse_resource_table(extract.pages, source) == extract.table


def test_a_page_that_only_mentions_the_marker_does_not_become_a_table(fixture_root: Path) -> None:
    """CET 那份第 6 页正文里也印着 "Mineral Resource as at June 30, 2022"（脚注），
    但那一页**没有表** —— 只有一句"305M tonnes grading 1.1% Li2O…"的概述。

    解析器必须跳过它、去第 36 页取真表。这条盯的是"表头标记只是**必要**条件"：
    从一句概述里凑出一张表，是这份产物里最难被发现的一种错 —— 它会印出一个
    看起来完全正常的资源量。
    """
    source = PILBARA_CET
    pages = dict(_frozen(fixture_root, source).pages)

    assert 6 in pages, "前提变了：第 6 页不再含表头标记"
    assert "Mineral Resource as at" in pages[6]
    assert "305M tonnes" in pages[6], "前提变了：第 6 页不再是那句概述"
    assert parse_resource_table(((6, pages[6]),), source) is None


def test_a_second_table_on_the_same_page_is_separated_by_column_count(fixture_root: Path) -> None:
    """PMET 第 41 页上有**两张**表：锂的（6 列）与铯的（5 列），后者同样以
    `Indicated` / `Inferred` 开头，只是少一列。

    分开它们的只有**列数**。这条把两张表在页面上的原文都摆出来：铯表那几行确实
    在页面上，且确实没进产物。靠"表头在第几行"认表是认不住的 —— 文本抽取后
    表头与数据行的先后顺序并不可靠。
    """
    source = PMET_CV5_CV13
    text = dict(_frozen(fixture_root, source).pages)[41]
    assert "Indicated 163,000 10.25 1.78 646 16,708" in text, "前提变了：铯表不在这一页了"
    assert "Caesium Zone Classification" in text

    table = parse_resource_table(((41, text),), source)

    assert table is not None
    assert [(row.category, row.tonnage_mt) for row in table.rows] == [
        (ResourceCategory.INDICATED, 107.991),
        (ResourceCategory.INFERRED, 33.38),
    ]
    assert {row.tonnage_mt for row in table.rows}.isdisjoint({0.163, 0.53, 0.693, 1.698})


def test_a_dash_cell_is_not_read_as_zero() -> None:
    """`-` 的意思是"这一类未估算/为零"，**不是** 0。

    读成 0 会在日报上印出"推断资源量 0 百万吨"—— 一个假得毫无破绽的数字。
    真实样本是 PMET 第 41 页铯表里的 `Inferred - - - - -`（那一行恰好因为列数
    不符先被挡掉了，所以这里用同形状的合成行来检验"数字列"这条规则本身）。

    后半段是对照：同样的形状、填真数字，就该认得出来 —— 否则这条测试证明的只是
    "解析器什么都不认"。
    """
    source = PILBARA_CET
    dashes = " ".join(["-"] * len(source.columns))
    page = f"{source.header_marker}\nInferred {dashes}\n"

    assert parse_resource_table(((1, page),), source) is None, "`-` 被当成 0 读进去了"

    numbers = " ".join("1" for _ in source.columns)
    control = parse_resource_table(((1, f"{source.header_marker}\nInferred {numbers}\n"),), source)

    assert control is not None, "对照组也读不出来 —— 上面那条断言证明不了任何事"
    assert control.rows[0].tonnage_mt == 1.0
    assert control.rows[0].category is ResourceCategory.INFERRED


def test_the_declared_column_order_is_what_places_the_numbers(fixture_root: Path) -> None:
    """列序由**声明**决定，不是猜的。

    把登记表里"品位"与"含金属量"两列对调，行上的数字就跟着对调。这条既证明映射
    确实来自声明，也说明声明错了会错得多么安静 —— 它不会崩、不会空，只会印出一张
    看起来完全正常的错表。这正是 ⛔ 人工核对卡点的理由。
    """
    source = PMET_CV5_CV13
    columns = list(source.columns)
    grade_index, contained_index = _index_of(source, "grade"), _index_of(source, "contained")
    columns[grade_index], columns[contained_index] = columns[contained_index], columns[grade_index]
    swapped = replace(source, columns=tuple(columns))

    page = dict(_frozen(fixture_root, source).pages)[41]
    table = parse_resource_table(((41, page),), swapped)

    assert table is not None
    assert (table.rows[0].grade, table.rows[0].contained) == (3.75, 1.4), "列序没跟着声明走"


def test_the_scale_from_the_declaration_is_applied_without_float_noise(fixture_root: Path) -> None:
    """PMET 的吨位在页面上写的是**吨**（107,991,000），登记表声明 ×1e-6 换成百万吨。

    顺带钉住一个反复出现的小坑：`33_380_000 × 1e-6` 在二进制浮点下是
    `33.379999999999995`。直接印出去像是我们算出了十三位有效数字。这里用 `repr`
    断言，因为 `== 33.38` 对那个噪声值同样成立 —— 用 `==` 是测不出这个坑的。
    """
    table = _frozen(fixture_root, PMET_CV5_CV13).table

    assert table is not None
    assert [row.tonnage_mt for row in table.rows] == [107.991, 33.38]
    assert repr(table.rows[1].tonnage_mt) == "33.38"


def test_resources_are_labeled_as_resources_because_the_report_says_so(fixture_root: Path) -> None:
    """节内"资源量 / 储量"之分，有**文档自己的一句话**兜底。

    PMET 第 41 页原文：'Mineral Resources are not Mineral Reserves as they do not
    have demonstrated economic viability.' —— 我们的 `kind` 字段就是这句话落成类型。
    它让"节内严格区分、不混用"这条验收可以被断言，而不是只能靠人眼。
    """
    source = PMET_CV5_CV13
    text = " ".join(dict(_frozen(fixture_root, source).pages)[41].split())
    assert "Mineral Resources are not Mineral Reserves" in text, "前提变了：那句免责声明不在这一页"

    table = _frozen(fixture_root, source).table
    assert table is not None
    assert {row.kind for row in table.rows} == {ResourceKind.RESOURCE}
    assert ResourceCategory.PROVEN.kind is ResourceKind.RESERVE
    assert ResourceCategory.PROBABLE.kind is ResourceKind.RESERVE


# ---------------------------------------------------------------------------
# 2. 交叉核对：拿页面自己印的东西对表内相加的结果
# ---------------------------------------------------------------------------


def test_the_rows_sum_to_the_total_row_printed_on_the_same_page(fixture_root: Path) -> None:
    """同一页上印着 `Total 305 1.1 105 0.6 3.5 71`，我们的三行相加也得 305 / 3.5。

    这是本票**唯一不靠自证**的核对之一：`Total` 行不是解析器算出来的，是页面
    自己印的。没有它，回放用例证明的只是"解析器这次和上次读得一样"。
    """
    source = PILBARA_CET
    extract = _frozen(fixture_root, source)
    assert extract.table is not None

    total = find_total_row(extract.pages, source)
    assert total is not None, "页面上那行 Total 没找到 —— 交叉核对失去了参照物"

    rows = extract.table.rows
    assert sum(row.tonnage_mt or 0.0 for row in rows) == total[_index_of(source, "tonnage")]
    assert sum(row.contained or 0.0 for row in rows) == total[_index_of(source, "contained")]


def test_the_page_states_the_same_totals_again_in_prose_and_in_a_footnote(
    fixture_root: Path,
) -> None:
    """两处**页面自己写的文字**，与表内合计互为佐证，而且跨页：

    - 第 6 页概述：'JORC Mineral Resource Estimate of 305M tonnes grading 1.1% Li2O,
      105 ppm Ta2O5 and 0.6% Fe2O3'；
    - 第 36 页表下脚注：'containing 3.5 M tonnes of Li2O and 71 M pounds of Ta2O5'。

    两段的数字都对得上 `Total` 行 —— 说明我们读的是同一张表、同一组列。
    这段文字**没有**参与解析（解析器只认"类别词 + 恰好 N 个数字"的行），
    所以它是佐证，不是自证。
    """
    source = PILBARA_CET
    pages = dict(_frozen(fixture_root, source).pages)
    total = find_total_row(_frozen(fixture_root, source).pages, source)
    assert total is not None

    prose = " ".join(pages[6].split())
    assert "Estimate of 305M tonnes grading 1.1% Li2O, 105 ppm Ta2O5 and 0.6% Fe2O3" in prose
    assert total[_index_of(source, "tonnage")] == 305.0
    assert total[_index_by_name(source, "Li2O 品位")] == 1.1
    assert total[_index_by_name(source, "Ta2O5 品位")] == 105.0
    assert total[_index_by_name(source, "Fe2O3 品位")] == 0.6

    footnote = " ".join(pages[36].split())
    assert "containing 3.5 M tonnes of Li2O and 71 M pounds of Ta2O5" in footnote
    assert total[_index_by_name(source, "Li2O 含量")] == 3.5
    assert total[_index_by_name(source, "Ta2O5 含量")] == 71.0


def test_contained_metal_tracks_tonnage_times_grade_when_the_units_match(
    fixture_root: Path,
) -> None:
    """CET 那份的"Li2O 含量(Mt)"就是吨位 × 品位 —— 单位一致，于是可以逐行验算。

    **这条验的是"我们挑的列有没有挑反"，不是"数字对不对"**，两者的强弱差着量级：
    把品位与含量挑反，`19 Mt × 0.3 / 100 = 0.057` 对页面印的 `1.4` 差 24 倍，
    一挑反就当场红；而数字本身对不对，这条**答不了**（见下）。

    为什么宽到一个末位单位：页面的"含量"是由**未取整的**吨位与品位算出来的，与它
    自己印出来的那两位取值天然有出入。三行的实际偏差——Measured `0.266` 印成 `0.3`、
    Indicated `2.244` 印成 `2.2`、Inferred `1.089` 印成 `1.0`——都落在一个末位单位
    （`contained` 印到小数点后一位）之内。把容差收到更紧，就是在拿页面自己的取整
    当我们的算错，那种假失败比没有断言更糟。

    宽到这个程度还剩多少检出能力，不由这段话说，由
    `test_the_loose_contained_check_still_has_teeth` **跑出来**。

    数字的**紧**核对在别处：`test_the_rows_sum_to_the_total_row_printed_on_the_same_page`
    比的是页面自己印的 `Total` 行 —— 那个参照物没有参与解析，才是能证事的。
    """
    source = PILBARA_CET
    table = _frozen(fixture_root, source).table
    assert table is not None

    bad = _contained_disagreements(table.rows, CONTAINED_PRECISION)
    assert bad == [], "恒等式在真数据上不成立：" + "；".join(bad)


def test_the_loose_contained_check_still_has_teeth(fixture_root: Path) -> None:
    """容差放宽到一个末位单位之后，这把尺子还剩多少检出能力 —— 这句话得能兑现。

    只写注释说"挑反了会红"不算数：注释不会被跑。这里把**同一份冻结数据**按挑反的
    方式重算一遍，断言三行**都被抓住**。两边一起跑，才说明这个容差既不虚紧（真数据
    不假红），也不虚松（挑反真的红）—— 单独任何一条都说明不了。

    顺带把余量最紧的一行量出来（`Inferred`：越界 0.11，门槛 0.1 —— 只差 0.01）。
    这不是凑数字，是给未来改容差的人一条警戒线：**把 `CONTAINED_PRECISION` 调到
    0.15 以上，这一行就悄悄失去检出能力了**，而上面那条恒等式照样全绿。
    """
    source = PILBARA_CET
    table = _frozen(fixture_root, source).table
    assert table is not None

    swapped = tuple(
        row.model_copy(update={"grade": row.contained, "contained": row.grade})
        for row in table.rows
    )
    bad = _contained_disagreements(swapped, CONTAINED_PRECISION)

    joined = "；".join(bad)
    assert len(bad) == 3, f"三行都该被抓住，实际只抓住 {len(bad)} 行：{joined}"
    # 余量最小的那行单独点出来 —— 一行都不漏，但最紧的一行只剩 0.01 的头寸。
    narrowest = min(
        abs(row.contained - row.tonnage_mt * row.grade / 100)  # type: ignore[operator]
        for row in swapped
    )
    assert narrowest - CONTAINED_PRECISION == pytest.approx(0.01, abs=1e-6), (
        f"最紧那一行的越界量变了（{narrowest}），容差的理由要重算"
    )


def test_contained_lce_needs_the_carbonate_factor_so_it_is_not_a_universal_rule(
    fixture_root: Path,
) -> None:
    """PMET 那份的"含金属量"是 **LCE**（碳酸锂当量），不是 Li2O。

    同名的 `contained` 字段在两个体系里单位不同，所以恒等式里要带换算系数。这条
    同时也是对"别把它当成通用规则"的说明：任何"含量 = 吨位 × 品位"的全局断言
    都会在这一份上假失败，而假失败的断言比没有断言更糟。
    """
    source = PMET_CV5_CV13
    table = _frozen(fixture_root, source).table
    assert table is not None

    for row in table.rows:
        assert row.tonnage_mt is not None and row.grade is not None and row.contained is not None
        expected = row.tonnage_mt * row.grade / 100 * LCE_FACTOR
        assert row.contained == pytest.approx(expected, rel=0.02), f"{row.category} 行的 LCE 对不上"


# ---------------------------------------------------------------------------
# 3. 冻结纪律
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", sorted(REPORT_SOURCES))
def test_the_frozen_extract_says_it_is_not_human_verified_yet(
    fixture_root: Path, slug: str
) -> None:
    """⛔ 卡点就长在这个字段上：人对着 PDF 核过之前，它必须还是 `false`。

    这条测试**保护的是一个尚未完成的状态**。哪天有人直接把 JSON 里的字段抄成
    `true` 而不去核对，它会当场变红 —— 这正是它存在的意义。
    """
    source = REPORT_SOURCES[slug]
    extract = _frozen(fixture_root, source)
    payload = _payload(fixture_root, source)

    assert extract.human_verified is False
    assert payload["human_verified"] is False
    assert payload["human_verified_by"] is None and payload["human_verified_at"] is None
    assert "未经人工核对" in extract.note and "不构成事实" in extract.note


def test_flipping_the_verified_flag_changes_only_the_note(
    tmp_path: Path, fixture_root: Path
) -> None:
    """把标记翻成 `true`，说明就该跟着变 —— 否则那个字段是个装饰品。

    同时断言数字**没被改动**：它记的是"谁读过这份结果"，不是"读出来是什么"。
    """
    source = PILBARA_CET
    payload = _payload(fixture_root, source)
    payload["human_verified"] = True
    target = tmp_path / "resources"
    target.mkdir()
    (target / f"{source.slug}.json").write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

    verified = load_frozen_extracts(target)[0]

    assert verified.human_verified is True
    assert verified.note == "已人工核对"
    assert verified.table == _frozen(fixture_root, source).table


async def test_a_pdf_that_was_never_frozen_fails_loudly_instead_of_going_to_the_network(
    fixture_root: Path,
) -> None:
    """回放时找不到某份 PDF 的冻结结果 → 响亮失败。

    悄悄降级成"数据缺失"会让人去查一份根本没问题的报告；悄悄联网则让"回放"这个词
    失去意义（ADR-0002 / ADR-0009）。哨兵串必须还在消息里 —— 它要跨 MCP 边界。
    """
    source = FrozenResourceSource(_resource_dir(fixture_root))

    with pytest.raises(FrozenExtractMissing) as excinfo:
        await source.extract("https://example.invalid/never-frozen.pdf")

    assert isinstance(excinfo.value, ReplayMiss)
    assert isinstance(excinfo.value, LoudFailure)
    assert REPLAY_MISS_SENTINEL in str(excinfo.value), "跨 MCP 边界的哨兵丢了"
    assert "extract_resources.py" in str(excinfo.value), "要告诉人下一步去哪儿补"


async def test_replay_mode_never_touches_the_fetcher(fixture_root: Path) -> None:
    """回放路径**结构上**就没有网络：`build_resource_source` 在 replay 下返回
    `FrozenResourceSource`，它连 fetcher 都不接。

    给一个"一被调用就炸"的 fetcher，然后跑通整条读路径 —— 这比断言"没有发出请求"
    更硬：它证明的是那个对象根本没被用上。
    """

    class _MustNotBeCalled:
        async def fetch(self, url: str) -> RawResponse:
            raise AssertionError(f"回放模式去抓了网络：{url}")

        async def post_form(self, url: str, form: object) -> RawResponse:
            raise AssertionError(f"回放模式去抓了网络：{url}")

    source = build_resource_source(
        data_mode="replay",
        fetcher=_MustNotBeCalled(),
        resource_dir=_resource_dir(fixture_root),
    )

    assert isinstance(source, FrozenResourceSource)
    table, failure = await source.extract(PILBARA_CET.pdf_url)

    assert failure is None
    assert table is not None
    assert [row.category for row in table.rows] == [
        ResourceCategory.MEASURED,
        ResourceCategory.INDICATED,
        ResourceCategory.INFERRED,
    ]


# ---------------------------------------------------------------------------
# 4. 实时路径与故障处置
# ---------------------------------------------------------------------------


class _FixedSource:
    """一个只会照着给的答案回答的 `ResourceSource` —— 用来单独检验 adapter 的编排。"""

    def __init__(self, table: ResourceTable | None, failure: str | None) -> None:
        self._table = table
        self._failure = failure

    async def extract(self, pdf_url: str) -> tuple[ResourceTable | None, str | None]:
        return self._table, self._failure


class _FetcherReturning:
    """把同一个响应发给任何 URL，并记下被调用的地址 —— 用来验证"该不该去抓"。"""

    def __init__(self, response: RawResponse) -> None:
        self._response = response
        self.calls: list[str] = []

    async def fetch(self, url: str) -> RawResponse:
        self.calls.append(url)
        return self._response

    async def post_form(self, url: str, form: object) -> RawResponse:
        self.calls.append(url)
        return self._response


def _raw(url: str, status: int, body: bytes) -> RawResponse:
    return RawResponse(
        url=url, status=status, content_type="application/pdf", body=body, fetched_at=NOW
    )


async def test_an_unregistered_pdf_is_refused_rather_than_guessed() -> None:
    """没有登记过列序的 PDF 一律不解析 —— 硬猜列序等于编数字。

    断言里连"没有去下载"一起验了：连表长什么样都不知道，去取那份文件也没有用。
    """
    url = "https://example.invalid/unregistered.pdf"
    fetcher = _FetcherReturning(_raw(url, 200, b"%PDF-1.4 not really"))
    table, failure = await LiveResourceSource(fetcher).extract(url)

    assert table is None
    assert failure is not None and "config/reports.py" in failure
    assert fetcher.calls == [], "没登记就不该去下载"


async def test_a_recorded_real_503_becomes_a_reason_not_an_exception(
    fixture_root: Path, fault_url: str
) -> None:
    """源拒绝了：降级并带上状态码，而不是抛异常、更不是"这份报告没有资源量"。

    样本是清单里那条**真实录下来的** 503（A7 用的同一个），走的是给这份 PDF 换一个
    观测地址的老办法（与 `test_price_tool` 同款）—— 不手写清单条目，也不给它开后门。
    """
    patched = {PILBARA_CET.slug: replace(PILBARA_CET, pdf_url=fault_url)}
    source = LiveResourceSource(FixtureFetcher(FixtureStore(fixture_root)), patched)

    table, failure = await source.extract(fault_url)

    assert table is None
    assert failure is not None
    assert "503" in failure, "理由里要带上那个状态码，否则没法排查"


async def test_a_body_that_is_not_a_pdf_degrades_instead_of_crashing() -> None:
    """源回了 200，但不是 PDF（错误页、登录跳转的 HTML）。

    这是**源侧**给了坏文件，按 ADR-0006 降级并说清，不掀翻整张图。真实样本：验证
    Pilbara 直链时收到的 `Page not found | PLS`（170 KB 的 HTML，见工单记录）；
    它没进 fixture —— 一份 170 KB 的错误页会稀释"清单 = 真实抓取记录"这个前提，
    而它要证明的事（"回来的不是 PDF"）在这里已经覆盖。

    注意它与"没装 pypdf"必须分开：后者是**我们**的环境不对，要炸穿。
    """
    url = "https://example.invalid/error-page.pdf"
    fetcher = _FetcherReturning(_raw(url, 200, b"<!doctype html><title>Page not found</title>"))

    patched = {PILBARA_CET.slug: replace(PILBARA_CET, pdf_url=url)}
    table, failure = await LiveResourceSource(fetcher, patched).extract(url)

    assert table is None
    assert failure is not None and "不是能解析的 PDF" in failure


async def test_a_loud_failure_from_the_fetcher_is_not_swallowed() -> None:
    """`LoudFailure`（缺浏览器 / 录播缺失）不许在这一层被变成降级信封。

    静默降级会让一次环境故障伪装成"这座矿山没有资源量数据"—— 与铜价那条同理。
    """

    class _Loud:
        async def fetch(self, url: str) -> RawResponse:
            raise BrowserUnavailable("没有无头浏览器")

        async def post_form(self, url: str, form: object) -> RawResponse:
            raise BrowserUnavailable("没有无头浏览器")

    source = LiveResourceSource(_Loud(), {PILBARA_CET.slug: PILBARA_CET})

    with pytest.raises(BrowserUnavailable):
        await source.extract(PILBARA_CET.pdf_url)


async def test_the_adapter_wraps_a_table_into_an_ok_envelope(fixture_root: Path) -> None:
    adapter = ResourceAdapter(FrozenResourceSource(_resource_dir(fixture_root)))

    extract = await adapter.extract_resources(PILBARA_CET.pdf_url, NOW)

    assert extract.status == "ok"
    assert extract.source_status is FetchStatus.OK
    assert extract.reason is None
    assert extract.table is not None and len(extract.table.rows) == 3
    assert extract.retrieved_at == NOW


async def test_an_empty_pdf_url_is_our_bug_and_raises() -> None:
    """参数非法是"工具自己坏了"，按 ADR-0005 抛异常 —— 它不是数据源的状态。"""
    adapter = ResourceAdapter(FrozenResourceSource("fixtures/resources"))

    with pytest.raises(ValueError):
        await adapter.extract_resources("   ", NOW)


async def test_no_table_recognised_degrades_as_unavailable_not_empty(fixture_root: Path) -> None:
    """**抽不到表 ≠ 这个项目没有资源量。**

    `EMPTY` 的含义是"源可达，且我们**成功地判定**确实没有符合范围的数据"；而"打了开
    一份报告却认不出它的表"绝大多数时候是**我们**读不出来（版式变了、列数变了）。
    记成 EMPTY 就等于把我们的解析失败说成矿山的性质 —— 那正是 ADR-0005 花力气分开
    这两种情形的理由。
    """
    adapter = ResourceAdapter(_FixedSource(table=None, failure=None))

    extract = await adapter.extract_resources(PILBARA_CET.pdf_url, NOW)

    assert extract.status == "degraded"
    assert extract.source_status is FetchStatus.UNAVAILABLE
    assert extract.reason is not None and "没有抽到" in extract.reason
    assert extract.table is None


async def test_a_source_reported_failure_reaches_the_envelope_verbatim(fixture_root: Path) -> None:
    """源侧的理由要**原样**进信封 —— 第 3 节与第 6 节靠它说清缺了什么。

    改写成一句"数据缺失"就等于把排查线索掐掉。
    """
    reason = "技术报告返回 HTTP 404，本次未能取到。"
    adapter = ResourceAdapter(_FixedSource(table=None, failure=reason))

    extract = await adapter.extract_resources(PILBARA_CET.pdf_url, NOW)

    assert extract.status == "degraded"
    assert extract.reason == reason


# ---------------------------------------------------------------------------
# 登记表自身的约束
# ---------------------------------------------------------------------------


def test_the_registry_declares_one_tonnage_column_per_report() -> None:
    """每份报告的登记表里吨位列**恰好一列**。

    多了就没有"哪一列是吨位"的答案，少了则 `ResourceRow.tonnage_mt` 永远为空 ——
    两种都会让产物看起来正常但少东西。
    """
    for slug, source in REPORT_SOURCES.items():
        roles = [column.role for column in source.columns]
        assert roles.count("tonnage") == 1, slug
        assert roles.count("grade") <= 1, slug
        assert roles.count("contained") <= 1, slug
        assert source_by_pdf_url(source.pdf_url) is source, slug


def test_every_archive_link_can_be_traced_back_to_a_registered_report() -> None:
    """档案里的直链必须能反查到登记表。

    反查不到就说明线上会走到"没登记、不解析"那条分支 —— 产物会说"数据缺失"，
    而真实原因是我们自己两边没对上。这条把那个错误挡在提交之前。
    """
    for entry in ARCHIVE:
        if entry.report_url is None:
            continue
        assert source_by_pdf_url(entry.report_url) is not None, f"{entry.id} 的直链没登记"


# ---------------------------------------------------------------------------
# 真下载真解析（PRD §13 R4）
# ---------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize("slug", sorted(REPORT_SOURCES))
async def test_the_real_pdf_still_parses_to_the_frozen_table(slug: str, fixture_root: Path) -> None:
    """真下载、真解析。默认套件排除（`addopts = -m 'not network'`）。

    它比回放用例强在两处：
    1. 跑的是**整条链路**（下载 → 逐页抽文本 → 解析），而回放只跑后半段；
    2. 顺带验证冻结结果的**出身**：拿回来的字节数与 sha256 必须与 JSON 里声称的一致
       —— 否则"这份 JSON 对应哪一次下载"这句话是空头支票。

    这份报告哪天换版（列变了、页变了），这条会红，而回放用例照样绿 —— 两者的
    差别正是它存在的理由。

    需要网络与（在有墙的网络上）`MINING_HTTP_PROXY`。
    """
    settings = Settings.from_env()
    source = REPORT_SOURCES[slug]
    extract = _frozen(fixture_root, source)

    async with httpx.AsyncClient(
        timeout=120.0, follow_redirects=True, proxy=settings.http_proxy or None
    ) as client:
        response = await client.get(source.pdf_url, headers={"User-Agent": settings.user_agent})

    assert response.status_code == 200, f"{source.pdf_url} 返回 {response.status_code}"
    body = response.content
    assert body.startswith(b"%PDF")

    assert len(body) == extract.pdf_bytes, "字节数对不上冻结记录 —— 这份文件换过了"
    assert hashlib.sha256(body).hexdigest() == extract.pdf_sha256, "sha256 对不上冻结记录"

    assert parse_resource_table(pages_from_pdf_bytes(body), source) == extract.table
