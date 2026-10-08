"""仓库内的固定路径。

**为什么不写 `Path("fixtures")`：`cwd` 不是我们的。** CLI 从仓库根跑，所以相对路径
一直是"对的"—— 直到同一个 server 被 MCP 宿主（Claude Desktop / Cursor）拉起，而那
时候的工作目录是宿主的、不是仓库的。那种坏法很隐蔽：进程起来了、工具列出来了，
第一次取数据才报"找不到清单"。

所以默认路径按**安装位置**推：本项目在仓库根，`mining_brief/` 是它的子目录，于是
`__file__` 往上两级就是仓库根。`uv run` 与 `uv sync` 默认把本包以 editable 方式装进
venv，`__file__` 因而指向仓库里这份源码；测试里构造 `Settings` 时也会显式传入
`fixture_root`，两条路都不依赖 cwd。

需要指到别处（比如把 fixture 放在别处的大文件盘上）时用 `MINING_FIXTURE_ROOT`。
"""

from __future__ import annotations

import os
from pathlib import Path

#: `mining_brief/config/paths.py` → `mining_brief/config` → `mining_brief` → 仓库根。
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_FIXTURE_ROOT = REPO_ROOT / "fixtures"
DEFAULT_LLM_FIXTURE_ROOT = DEFAULT_FIXTURE_ROOT / "llm"


def fixture_root() -> Path:
    """fixture 根目录：`MINING_FIXTURE_ROOT` 优先，否则仓库根下的 `fixtures/`。"""
    override = os.environ.get("MINING_FIXTURE_ROOT", "").strip()
    return Path(override) if override else DEFAULT_FIXTURE_ROOT


def llm_fixture_root() -> Path:
    """LLM 录播目录。跟着 `fixture_root()` 走，不单独配一个变量。

    两者分家会造出一种很难查的坏法：数据换成了一套 fixture，LLM 却还在读仓库里
    那一份 —— 回放的 key 落在数据上，于是每一句都会以"缺录播"报错，而人会先去
    怀疑模型而不是路径。
    """
    return fixture_root() / "llm"
