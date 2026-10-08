"""fixture 仓库：回放模式下唯一的读数入口（ADR-0002）。

存的是**抓取时刻的原始响应体逐字节**（除 PDF —— 二进制不入库，见 ADR-0001），
另加 `sources.json` 记 URL / SHA256 / 抓取时间 / Content-Type / 状态。

回放模式下**唯一的时间真相来自 fixture**：简报的"今日"、各节数据截止时间戳、
`window_days` 的窗口计算，全部从 `sources.json` 的锚点时间推导，不读系统时钟。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mining_brief.config.paths import fixture_root
from mining_brief.contracts import RawResponse
from mining_brief.errors import ReplayMiss


class FixtureMissing(ReplayMiss, LookupError):
    """回放时查不到对应的录播。

    这条**必须**响亮地失败 —— 悄悄退回真实网络会让"离线确定性"变成薛定谔的绿，
    而悄悄降级成"数据缺失"会让人去查一个根本没坏的网站（ADR-0002 / ADR-0009）。

    同时继承 `LookupError`：按 URL 查不到东西，用 `LookupError` 表达最贴切，
    老的调用方也仍然按 `LookupError` 捕获得到。
    """


class FixtureEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    path: str
    sha256: str
    fetched_at: datetime
    content_type: str
    status: int

    @property
    def is_binary(self) -> bool:
        """二进制文件（PDF）不入库，因此**没有** body 文件，只有 path 指向的抽取结果。"""
        return self.sha256 == ""


class FixtureManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    anchor_at: datetime
    """回放模式下的"现在"。产出的简报日期会因此是过去的某一天 —— 这是刻意的
    （ADR-0002），看到"简报日期 ≠ 今天"不是 bug。"""

    entries: tuple[FixtureEntry, ...]


class FixtureStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else fixture_root()
        manifest_path = self.root / "sources.json"
        if not manifest_path.exists():
            raise FixtureMissing(f"缺少 fixture 清单：{manifest_path}")
        self.manifest = FixtureManifest.model_validate_json(manifest_path.read_text("utf-8"))
        self._by_url = {entry.url: entry for entry in self.manifest.entries}

    @property
    def anchor_at(self) -> datetime:
        return self.manifest.anchor_at

    def has(self, url: str) -> bool:
        return url in self._by_url

    def entry_for(self, url: str) -> FixtureEntry:
        try:
            return self._by_url[url]
        except KeyError:
            known = "\n  ".join(sorted(self._by_url)) or "(清单为空)"
            raise FixtureMissing(
                f"回放模式找不到这个 URL 的录播：{url}\n"
                f"已有录播：\n  {known}\n"
                "缺录播时**不回退真实网络** —— 请重跑 scripts/fetch_fixtures.py。"
            ) from None

    def raw(self, url: str) -> RawResponse:
        """取回逐字节原文。回放时 `fetched_at` 用录播记录的真实抓取时刻，
        这样"这份数据是什么时候抓的"在产物里仍然可追溯。"""
        entry = self.entry_for(url)
        body_path = self.root / entry.path
        if not body_path.exists():
            raise FixtureMissing(f"清单里有 {entry.path}，但文件不存在")
        body = body_path.read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        if actual != entry.sha256:
            raise FixtureMissing(
                f"fixture 校验和不符：{entry.path}\n  清单 {entry.sha256}\n  实际 {actual}\n"
                "文件被改动过，或清单是旧版。"
            )
        return RawResponse(
            url=entry.url,
            status=entry.status,
            content_type=entry.content_type,
            body=body,
            fetched_at=entry.fetched_at,
        )


def read_manifest(root: Path | str | None = None) -> FixtureManifest:
    base = Path(root) if root is not None else fixture_root()
    return FixtureManifest.model_validate_json((base / "sources.json").read_text("utf-8"))


def write_manifest(root: Path | str, payload: dict[str, object]) -> None:
    path = Path(root) / "sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
