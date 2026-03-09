"""运行时兼容性补丁。
adrf 0.1.12 在 15 处使用 asyncio.iscoroutinefunction，
Python 3.14 弃用该函数（3.16 移除），替换为 inspect.iscoroutinefunction。
adrf 无新版本修复此问题，需要运行时 monkey-patch。
"""
import asyncio
import inspect
def patch_asyncio_iscoroutinefunction -> None:
 """将 asyncio.iscoroutinefunction 替换为 inspect.iscoroutinefunction。
 两者功能完全等价，inspect 版本是 Python 官方推荐用法。
 """
 asyncio.iscoroutinefunction = inspect.iscoroutinefunction # type: ignore[attr-defined]
