"""Phase 一次性数据迁移命令。
把 ``CodingSession.tech_plan / affected_files`` 数据回填到独立的
``CodingPlan`` 表，并把 ``CodingSession.coding_plan_id`` 反向关联回填。
去重策略：同一 ``conversation_id`` 下 ``tech_plan`` 内容相同的多个 session
共享同一个 CodingPlan（通过 ``CodingPlan.aget_or_create_for_conversation``
的 sha256 工厂）。无 ``tech_plan`` 的极少数 session 按 conversation 共享一个
占位 plan。
用法:
 python manage.py migrate_coding_sessions_to_plans --dry-run
 python manage.py migrate_coding_sessions_to_plans --report /tmp/report.json
 python manage.py migrate_coding_sessions_to_plans
命令 idempotent：重复执行不会重复建表，第二次执行所有 session 都进入
``skipped`` 分支。
"""
from __future__ import annotations
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any
import structlog
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand
logger = structlog.get_logger(__name__)
PLACEHOLDER_TECH_PLAN = "_(无 tech_plan，自动生成占位)_"
PLACEHOLDER_TITLE = "占位方案（无技术方案文本）"
class Command(BaseCommand):
 """``migrate_coding_sessions_to_plans`` 管理命令实现。"""
 help = (
 "把 CodingSession 的 tech_plan / affected_files 数据回填到独立的 "
 "CodingPlan 表（Phase）。idempotent；支持 --dry-run 与 --report。"
 )
 def add_arguments(self, parser: Any) -> None:
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="预览模式，不写 DB，只输出统计与（可选）报告。",
 )
 parser.add_argument(
 "--report",
 type=str,
 default="",
 help="可选 JSON 报告输出路径，写入 [{session_id, plan_id, action}]。",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 async_to_sync(self._ahandle)(
 dry_run=bool(options.get("dry_run")),
 report_path=str(options.get("report") or ""),
 )
 async def _ahandle(self, *, dry_run: bool, report_path: str) -> None:
 from chat.models import CodingPlan, CodingSession
 logger.info("migrate_coding_sessions_started", dry_run=dry_run)
 stats: dict[str, int] = {
 "total": 0,
 "created": 0,
 "linked": 0,
 "skipped": 0,
 "placeholder": 0,
 }
 report: list[dict[str, str]] =
 # dry-run 与正式执行共享一套分类逻辑：
 # - 模拟态用本地 dict 跟踪每个 conversation 的 hash → "plan_id 占位串"
 # - 正式态调用工厂方法真写入
 # 占位 plan 同样按 conversation 维度共享一个（hash key 用常量）。
 # ----------------------------------------------------------------
 sim_index: dict[tuple[uuid.UUID, str], str] = {}
 placeholder_cache: dict[uuid.UUID, "CodingPlan"] = {}
 async for session in (
 CodingSession.objects.select_related("coding_plan", "conversation")
 .order_by("created_at")
 .aiterator
 ):
 stats["total"] += 1
 session_id_str = str(session.id)
 if session.coding_plan_id is not None:
 stats["skipped"] += 1
 report.append(
 {
 "session_id": session_id_str,
 "plan_id": str(session.coding_plan_id),
 "action": "skipped",
 }
 )
 logger.info(
 "coding_session_skip_already_linked",
 session_id=session_id_str,
 plan_id=str(session.coding_plan_id),
 )
 continue
 conversation_id = session.conversation_id # type: ignore[attr-defined]
 tech_plan = (session.tech_plan or "").strip
 is_placeholder = tech_plan == ""
 if is_placeholder:
 key = (conversation_id, "__placeholder__")
 if dry_run:
 if key not in sim_index:
 sim_index[key] = f"sim-placeholder-{conversation_id}"
 stats["created"] += 1
 stats["placeholder"] += 1
 report.append(
 {
 "session_id": session_id_str,
 "plan_id": sim_index[key],
 "action": "placeholder",
 }
 )
 continue
 if conversation_id not in placeholder_cache:
 plan, _created = await CodingPlan.aget_or_create_for_conversation(
 conversation=session.conversation,
 tech_plan=PLACEHOLDER_TECH_PLAN,
 affected_files=,
 title=PLACEHOLDER_TITLE,
 )
 if _created:
 stats["created"] += 1
 placeholder_cache[conversation_id] = plan
 plan = placeholder_cache[conversation_id]
 session.coding_plan = plan
 await session.asave(update_fields=["coding_plan", "updated_at"])
 stats["placeholder"] += 1
 report.append(
 {
 "session_id": session_id_str,
 "plan_id": str(plan.id),
 "action": "placeholder",
 }
 )
 logger.info(
 "coding_session_linked",
 session_id=session_id_str,
 plan_id=str(plan.id),
 placeholder=True,
 )
 continue
 content_hash = hashlib.sha256(tech_plan.encode("utf-8")).hexdigest
 key = (conversation_id, content_hash)
 if dry_run:
 if key not in sim_index:
 sim_index[key] = f"sim-{content_hash[:12]}"
 stats["created"] += 1
 stats["linked"] += 1
 report.append(
 {
 "session_id": session_id_str,
 "plan_id": sim_index[key],
 "action": "linked",
 }
 )
 continue
 plan, created = await CodingPlan.aget_or_create_for_conversation(
 conversation=session.conversation,
 tech_plan=session.tech_plan,
 affected_files=session.affected_files or,
 title="",
 )
 if created:
 stats["created"] += 1
 session.coding_plan = plan
 await session.asave(update_fields=["coding_plan", "updated_at"])
 stats["linked"] += 1
 report.append(
 {
 "session_id": session_id_str,
 "plan_id": str(plan.id),
 "action": "created" if created else "linked",
 }
 )
 logger.info(
 "coding_session_linked",
 session_id=session_id_str,
 plan_id=str(plan.id),
 created=created,
 )
 # 汇总输出
 summary_lines = [
 f"扫描总数: {stats['total']}",
 f"新建 CodingPlan: {stats['created']}",
 f"已链接 CodingSession: {stats['linked']}",
 f"占位方案 CodingSession: {stats['placeholder']}",
 f"跳过 (已 linked): {stats['skipped']}",
 ]
 if dry_run:
 summary_lines.insert(0, "[dry-run] 未写入 DB")
 for line in summary_lines:
 self.stdout.write(self.style.SUCCESS(line))
 if report_path:
 Path(report_path).write_text(
 json.dumps(report, ensure_ascii=False, indent=2),
 encoding="utf-8",
 )
 self.stdout.write(self.style.SUCCESS(f"报告已写入: {report_path}"))
 logger.info(
 "migrate_coding_sessions_finished",
 dry_run=dry_run,
 **stats,
 )
