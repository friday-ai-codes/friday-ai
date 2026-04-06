from __future__ import annotations
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from friday.settings import DATA_DIR
CHECKPOINT_DB_PATH = DATA_DIR / "orchestration_checkpoints.db"
_checkpointer: AsyncSqliteSaver | None = None
async def get_checkpointer -> AsyncSqliteSaver:
 """获取全局 AsyncSqliteSaver 实例（惰性初始化）。
 使用独立 SQLite 文件，避免与 Django 主数据库竞争写锁。
 连接生命周期与进程绑定，不使用 context manager 以保持单例存活。
 """
 global _checkpointer
 if _checkpointer is None:
 conn = aiosqlite.connect(str(CHECKPOINT_DB_PATH))
 raw_conn = await conn.__aenter__
 saver = AsyncSqliteSaver(raw_conn)
 await saver.setup
 _checkpointer = saver
 return _checkpointer
