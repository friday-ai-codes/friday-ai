"""CommentEventService —— 评论事件落库唯一写入入口（CMT-01，INV-6 精神）。

评论事件以 append-only 流式入库：所有路径（拉取式 ``ingest_comments`` /
webhook ``append_webhook_comment``）最终都经 ``append_events`` 这唯一收口落库，
禁旁路写 ``WorkItemCommentEvent`` 表（守护测试在 29-03 落地）。

去重锚 ``(work_item, feishu_comment_id, event_type, event_time)`` 经
``get_or_create`` 保证幂等可重入——同评论多次拉取不产生重复事件（T-29-03）。

失败策略沿用 Phase 28 WIT-03 范式：拉取回源失败仅记 ``WorkItemSyncState``
（facet=comments，status=missing/error），不抛、不回滚 WorkItem。
``approval_semantic`` 经 ``classify_approval_semantic`` 单一判定（与 29-03 webhook
接线共用同一来源，per CONTEXT Grey Area 3）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone

from delivery.models import (
    ApprovalSemantic,
    CommentEventType,
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemCommentEvent,
)
from delivery.services.work_item_service import (
    _ERROR_SNIPPET_LIMIT,
    WorkItemIdentity,
    _redact_secrets,
)
from services.feishu import create_feishu_client_for_project

logger = structlog.get_logger(__name__)

__all__ = ["CommentEventService", "classify_approval_semantic"]

# approval 关键词单一来源：与 feishu/views.py _handle_workitem_comment 对齐。
# 把 webhook 既有关键词识别抽成纯函数单一判定来源（per CONTEXT Grey Area 3），
# service 拉取路径与 29-03 webhook 接线共用，避免判定漂移。
_APPROVAL_KEYWORDS = ("通过", "批准", "approved", "lgtm", "ok", "\U0001f44d")
_REJECTION_KEYWORDS = ("驳回", "拒绝", "rejected", "需要修改", "不通过", "\U0001f44e")


def classify_approval_semantic(text: str | None) -> str:
    """由评论内容判定审批语义 approve / reject / none（单一判定来源）。

    复用 webhook ``_handle_workitem_comment`` 既有关键词：命中 approval 关键词
    （通过/批准/approved/lgtm/ok/👍）→ approve；命中 rejection 关键词
    （驳回/拒绝/rejected/需要修改/不通过/👎）→ reject。**同时命中以 reject 优先**
    （驳回是更强约束，反向取最保守；与 webhook ``approved = is_approved and
    not is_rejected`` 取向一致）。空 / None → none。

    Args:
        text: 评论正文（webhook payload 的 ``comment`` 或 parse_comments 的 ``content``）。

    Returns:
        ``ApprovalSemantic`` 值之一："none" / "approve" / "reject"。
    """
    if not text:
        return ApprovalSemantic.NONE
    lowered = text.lower()
    is_rejected = any(kw in lowered for kw in _REJECTION_KEYWORDS)
    is_approved = any(kw in lowered for kw in _APPROVAL_KEYWORDS)
    # reject 优先：同时命中时取最保守
    if is_rejected:
        return ApprovalSemantic.REJECT
    if is_approved:
        return ApprovalSemantic.APPROVE
    return ApprovalSemantic.NONE


class CommentEventService:
    """评论事件落库唯一写入入口（INV-6 精神）。"""

    async def append_events(self, work_item: WorkItem, comments: list[dict], source: str) -> int:
        """**评论事件落库的唯一写入收口**（append-only，幂等可重入）。

        遍历 ``parse_comments`` 形状的 dict（键：id/content/created_at/author/
        thread_parent_id），对每条派生 event_type 并经去重锚 get_or_create 落库。
        event_type 推导（per CONTEXT Grey Area 3）：approval_semantic≠none → approval；
        否则有 thread_parent_id → replied、无 → created（edited/deleted 本 phase 不
        合成，留待真实信号）。

        Args:
            work_item: 已落库 canonical WorkItem。
            comments: parse_comments 形状的评论 dict 列表。
            source: 调用方来源（仅日志/语义用，事件模型无 source 字段）。

        Returns:
            本次**新建**事件数（重复摄取命中去重锚则不计）。
        """
        created_count = await self._append_events_sync(work_item, comments, source)
        # 评论入图（RREF-02）：本次有新增事件才 best-effort 触发 work_item 重投影，
        # 使评论进入 feishu_work_item 知识快照（created_count==0 幂等重摄不触发，
        # 避免无谓重投影）。触发绝不阻塞/回滚评论落库（事实源优先，INV-3）。
        if created_count > 0:
            await self._schedule_work_item_reprojection(work_item)
        return created_count

    async def _schedule_work_item_reprojection(self, work_item: WorkItem) -> None:
        """评论新增后 best-effort 触发 feishu_work_item 重投影（评论入快照，RREF-02）。

        ``aschedule_ingestion`` 自身 ``transaction.on_commit`` + 后台投递 + 异常全吞，
        故触发绝不阻塞/回滚评论落库；外层再裹 try/except 防御惰性 import 等异常
        （delivery→knowledge 循环依赖经函数内惰性 import 规避）。
        """
        try:
            from knowledge.ingestion import IngestionRequest, aschedule_ingestion

            source_id = (
                f"{work_item.feishu_project_key}:"
                f"{work_item.work_item_type}:{work_item.work_item_id}"
            )
            await aschedule_ingestion(
                IngestionRequest(
                    source_kind="feishu_work_item",
                    source_id=source_id,
                    trigger="comment_event_appended",
                )
            )
        except Exception as exc:
            logger.warning(
                "comment_event_reprojection_schedule_failed",
                work_item_id=str(work_item.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    @sync_to_async
    def _append_events_sync(self, work_item: WorkItem, comments: list[dict], source: str) -> int:
        """整批落库（同步循环 get_or_create），经 ``append_events`` 经 sync_to_async 桥接。"""
        created_count = 0
        for comment in comments or []:
            raw_id = comment.get("id")
            if not raw_id:
                # 缺 feishu_comment_id → 无去重锚，跳过 + warning（不构造无锚事件）
                logger.warning(
                    "comment_event_skip_missing_id",
                    work_item_id=str(work_item.id),
                    source=source,
                )
                continue
            feishu_comment_id = str(raw_id)
            body = comment.get("content") or ""
            event_time = self._parse_ms(comment.get("created_at"))
            semantic = classify_approval_semantic(body)
            thread_parent_id = str(comment.get("thread_parent_id") or "")

            if semantic != ApprovalSemantic.NONE:
                event_type = CommentEventType.APPROVAL
            elif thread_parent_id:
                event_type = CommentEventType.REPLIED
            else:
                event_type = CommentEventType.CREATED

            try:
                _, created = WorkItemCommentEvent.objects.get_or_create(
                    work_item=work_item,
                    feishu_comment_id=feishu_comment_id,
                    event_type=event_type,
                    event_time=event_time,
                    defaults={
                        "author": comment.get("author") or "",
                        "body": body,
                        "thread_parent_id": thread_parent_id,
                        # parse_comments 当前不产 attachments → 默认 []（不臆造）
                        "attachments": comment.get("attachments") or [],
                        "approval_semantic": semantic,
                    },
                )
            except IntegrityError:
                # 并发竞态兜底：另一路径在 check-then-insert 间隙已落同锚行，
                # uniq_comment_event_anchor 唯一约束拦下重复 INSERT（get_or_create 的
                # 重试 get 极端下仍可能上抛）——视作"已追加"，不重复、不崩溃（WR-02）。
                created = False
            if created:
                created_count += 1
        return created_count

    async def ingest_comments(self, identity: WorkItemIdentity, source: str) -> dict:
        """**拉取式摄取路径**：拉 get_comments → append events（供 manual/编排调用）。

        复用 Phase 27 ``get_comments``（内部已 parse_comments，**不重写解析**）。
        缺 project / 缺 canonical work_item / 回源失败 → 降配（comments facet
        missing/error + warning），不抛、不回滚 WorkItem（WIT-03 范式）。

        Args:
            identity: 飞书三元组身份。
            source: 调用方来源（WorkItemOrigin 值，如 manual）。

        Returns:
            降配结果 dict：``{"status", "appended", ...}``。
        """
        project = await self._resolve_project(identity.feishu_project_key)
        work_item = await self._resolve_work_item(identity)

        if project is None:
            # 缺 project 无法回源：有 work_item 记 missing，否则仅 warning
            if work_item is not None:
                await self._record_sync_state(
                    work_item,
                    SyncStatus.MISSING,
                    source,
                    error="project_unconfigured",
                )
            logger.warning(
                "comment_ingest_project_unconfigured",
                project_key=identity.feishu_project_key,
                work_item_id=identity.work_item_id,
            )
            return {"status": "missing", "appended": 0, "reason": "project_unconfigured"}

        try:
            comments = await self._fetch_comments(project, identity)
        except Exception as exc:
            error = self._safe_error(exc)
            logger.warning(
                "comment_ingest_fetch_failed",
                project_key=identity.feishu_project_key,
                work_item_type=identity.work_item_type,
                work_item_id=identity.work_item_id,
                error=error,
                error_type=type(exc).__name__,
            )
            if work_item is not None:
                await self._record_sync_state(work_item, SyncStatus.MISSING, source, error=error)
            return {"status": "error", "appended": 0, "error": error}

        if work_item is None:
            # 缺 canonical work_item：跳过 append（建 WorkItem 是 upsert 的职责，CONTEXT）
            logger.warning(
                "comment_ingest_work_item_missing",
                project_key=identity.feishu_project_key,
                work_item_type=identity.work_item_type,
                work_item_id=identity.work_item_id,
            )
            return {"status": "missing", "appended": 0, "reason": "work_item_missing"}

        appended = await self.append_events(work_item, comments, source)
        # 拉取空列表也算 complete（不假装 missing）
        await self._record_sync_state(work_item, SyncStatus.COMPLETE, source)
        return {"status": "complete", "appended": appended}

    async def append_webhook_comment(
        self,
        identity: WorkItemIdentity,
        *,
        comment_id: str,
        body: str,
        author: str = "",
        thread_parent_id: str = "",
        created_at: Any = None,
        source: str,
    ) -> int:
        """**webhook 接线路径**（29-03 调用）：单条 webhook 评论归一后经 append_events 落库。

        按三元组解析已落库 work_item；缺 work_item → warning 跳过返回 0
        （不创建 WorkItem，那是 upsert 的职责，CONTEXT）。

        Args:
            identity: 飞书三元组身份。
            comment_id: 飞书评论 id（去重锚组成）。
            body: 评论正文。
            author: 评论作者。
            thread_parent_id: 线程父评论 id（根评论为空）。
            created_at: 毫秒时间戳（缺失 → event_time=None）。
            source: 调用方来源（WorkItemOrigin 值，如 feishu_webhook）。

        Returns:
            新建事件数（缺 work_item 返回 0）。
        """
        work_item = await self._resolve_work_item(identity)
        if work_item is None:
            logger.warning(
                "comment_webhook_work_item_missing",
                project_key=identity.feishu_project_key,
                work_item_type=identity.work_item_type,
                work_item_id=identity.work_item_id,
            )
            return 0
        comment = {
            "id": comment_id,
            "content": body,
            "created_at": created_at,
            "author": author,
            "thread_parent_id": thread_parent_id,
        }
        return await self.append_events(work_item, [comment], source)

    # === 步骤实现 ===

    async def _resolve_project(self, project_key: str):
        """按 feishu_project_key 解析 Space（async）；缺失返回 None。"""
        from projects.models import Space

        return await Space.objects.filter(feishu_project_key=project_key).afirst()

    async def _resolve_work_item(self, identity: WorkItemIdentity):
        """按三元组解析已落库 canonical WorkItem（async）；缺失返回 None。"""
        return await WorkItem.objects.filter(
            feishu_project_key=identity.feishu_project_key,
            work_item_type=identity.work_item_type,
            work_item_id=identity.work_item_id,
        ).afirst()

    async def _fetch_comments(self, project, identity: WorkItemIdentity) -> list[dict]:
        """经项目加密凭证回源 get_comments（复用 Phase 27，真实 type，不重写解析）。

        ``get_comments`` 对非 JSON / err_code≠0 已 fail-soft 返回 ``[]``（视作
        complete-empty）；本方法只把网络/客户端层异常向上抛给 ``ingest_comments``
        的 try/except 降配为 missing/error。
        """
        client = create_feishu_client_for_project(project)
        return await client.get_comments(
            project_key=identity.feishu_project_key,
            work_item_id=identity.work_item_id,
            work_item_type=identity.work_item_type,
        )

    @sync_to_async
    def _record_sync_state(
        self,
        work_item: WorkItem,
        status: str,
        source: str,
        *,
        error: str = "",
    ) -> None:
        """按 (work_item, comments) 落 WorkItemSyncState（update_or_create 幂等，WIT-03 范式）。"""
        from delivery.models import WorkItemSyncState

        WorkItemSyncState.objects.update_or_create(
            work_item=work_item,
            facet=SyncFacet.COMMENTS,
            defaults={
                "status": status,
                "source": source,
                "last_synced_at": timezone.now() if status == SyncStatus.COMPLETE else None,
                "error": error,
            },
        )

    # === helper ===

    def _safe_error(self, exc: Exception) -> str:
        """脱敏错误摘要：先抹凭证再截断（复用 28-02 _redact_secrets 思路，T-29-05）。

        comment body 属业务内容不入 error/日志凭证面；仅 SyncState.error 脱敏。
        """
        return _redact_secrets(str(exc))[:_ERROR_SNIPPET_LIMIT]

    def _parse_ms(self, raw: Any):
        """毫秒时间戳 → aware UTC datetime；缺失/非法 → None（恒 aware，与 §13.1 对齐）。"""
        if raw is None:
            return None
        try:
            ms = int(raw)
        except (TypeError, ValueError):
            return None
        if ms <= 0:
            return None
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
