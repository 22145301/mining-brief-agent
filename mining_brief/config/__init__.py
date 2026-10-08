"""配置层：只放**非密钥**配置与运行参数（ADR-0008）。

密钥与 LLM key 不在这里 —— 它们走环境变量 + `.env.example`。
"""

from mining_brief.config.logging import configure_logging, get_logger
from mining_brief.config.settings import ConfigError, Settings

__all__ = ["ConfigError", "Settings", "configure_logging", "get_logger"]
