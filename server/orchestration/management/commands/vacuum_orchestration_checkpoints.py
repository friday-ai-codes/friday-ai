"""手动 VACUUM orchestration_checkpoints.db 回收空间（Phase Claude's Discretion）。
背景：SQLite DELETE 不释放磁盘空间，需 VACUUM 才能收缩文件。
本 phase 决策（RESEARCH Open Q4）：
- 默认**不**在 `cleanup_orchestration_checkpoints` 命令内 VACUUM
 （避免 journal_mode 冲突 + 阻塞活跃读写）
- 独立命令由管理员手动触发；文档指引 "每月执行一次" 或
 "监控发现 db > 100MB 时执行"
- **不**注册到 APScheduler（明确拒绝自动化，T- Availability accept）
用法：
 python manage.py vacuum_orchestration_checkpoints
 python manage.py vacuum_orchestration_checkpoints --dry-run
注意：
- VACUUM 需要 journal_mode=DELETE（AsyncSqliteSaver 默认 WAL 可能冲突
 → 本命令先切 journal_mode 再 VACUUM 再切回 WAL）
- 执行期间阻塞其他编排读写 — 建议在低峰期触发
"""
from __future__ import annotations
import asyncio
from typing import Any
import aiosqlite
import structlog
from django.core.management.base import BaseCommand, CommandParser
from orchestration.checkpointer import CHECKPOINT_DB_PATH
logger = structlog.get_logger(__name__)
class Command(BaseCommand):
 help = "手动 VACUUM orchestration_checkpoints.db 回收空间（Phase Claude's Discretion）"
 def add_arguments(self, parser: CommandParser) -> None:
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="仅报告当前 db 大小，不执行 VACUUM",
 )
 def handle(self, *args: object, **options: Any) -> None:
 dry_run = bool(options["dry_run"])
 if not CHECKPOINT_DB_PATH.exists:
 self.stdout.write(
 self.style.WARNING(
 f"orchestration_checkpoints.db 不存在（{CHECKPOINT_DB_PATH}）"
 )
 )
 logger.info(
 "vacuum_orchestration_checkpoints_skipped",
 reason="db_not_exists",
 path=str(CHECKPOINT_DB_PATH),
 )
 return
 size_before = CHECKPOINT_DB_PATH.stat.st_size
 if dry_run:
 self.stdout.write(
 f"[dry-run] current db size: {size_before / 1024 / 1024:.2f} MB"
 )
 logger.info(
 "vacuum_orchestration_checkpoints_dry_run",
 size_bytes=size_before,
 )
 return
 asyncio.run(self._vacuum)
 size_after = (
 CHECKPOINT_DB_PATH.stat.st_size
 if CHECKPOINT_DB_PATH.exists
 else 0
 )
 logger.info(
 "vacuum_orchestration_checkpoints_completed",
 size_before_bytes=size_before,
 size_after_bytes=size_after,
 reclaimed_bytes=size_before - size_after,
 )
 self.stdout.write(
 self.style.SUCCESS(
 f"VACUUM 完成："
 f"{size_before / 1024 / 1024:.2f} MB → "
 f"{size_after / 1024 / 1024:.2f} MB "
 f"(回收 {(size_before - size_after) / 1024 / 1024:.2f} MB)"
 )
 )
 async def _vacuum(self) -> None:
 """先切 journal_mode=DELETE，执行 VACUUM，再切回 WAL（AsyncSqliteSaver 默认）。"""
 async with aiosqlite.connect(str(CHECKPOINT_DB_PATH)) as conn:
 await conn.execute("PRAGMA journal_mode=DELETE")
 await conn.execute("VACUUM")
 await conn.execute("PRAGMA journal_mode=WAL")
 await conn.commit
