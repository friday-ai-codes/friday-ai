"""Core module - 核心执行逻辑。

包含：
- config: 配置管理
- runner: 容器模式入口（使用 from friday_task.core.runner import TaskRunner）
- executor: Claude Agent 执行器
"""

from .config import TaskConfig
from .executor import ClaudeRunner

# TaskRunner 单独导入以避免循环依赖：
# from friday_task.core.runner import TaskRunner

__all__ = ["TaskConfig", "ClaudeRunner"]
