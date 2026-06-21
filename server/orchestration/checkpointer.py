from __future__ import annotations

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from friday.settings import DATA_DIR

CHECKPOINT_DB_PATH = DATA_DIR / "orchestration_checkpoints.db"

_checkpointer: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """获取全局 AsyncSqliteSaver 实例（惰性初始化）。

    使用独立 SQLite 文件，避免与 Django 主数据库竞争写锁。
    连接生命周期与进程绑定，不使用 context manager 以保持单例存活。
    """
    global _checkpointer
    if _checkpointer is None:
        conn = aiosqlite.connect(str(CHECKPOINT_DB_PATH))
        raw_conn = await conn.__aenter__()
        saver = AsyncSqliteSaver(raw_conn)
        await saver.setup()
        _checkpointer = saver
    return _checkpointer


async def close_checkpointer() -> None:
    """关闭全局 checkpointer 及其底层 aiosqlite 连接，释放非 daemon worker 线程。

    aiosqlite 每个连接会起一个 **非 daemon** worker 线程，仅在 ``close()`` 时收到
    停止信号才退出。本单例连接生命周期与进程绑定、平时不关闭；但若进程要正常退出
    （优雅关停 / pytest session 收尾），未关闭会令 Python 解释器在 join 该线程处
    永久阻塞（典型表现：CI server-ci 跑满 6h 超时）。故在关停路径显式调用本函数。

    幂等：未初始化时为 no-op；关闭后把单例重置为 None，允许后续按需重建。
    """
    global _checkpointer
    saver = _checkpointer
    _checkpointer = None
    if saver is not None:
        await saver.conn.close()
