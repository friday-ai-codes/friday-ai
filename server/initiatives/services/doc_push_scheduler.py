"""系统区写后 debounce 推送调度（SYNC-02，83-03）。

``ProjectDocService`` / ``MemoryService`` 在**系统区**写入成功后调 ``schedule_doc_push``：
先从 ``ProjectDoc`` 解析 ``feishu_document_id``，再
``DurableTaskService.defer("durable_doc_sync_push", {"doc_id": ...}, lock=docsync-{feishu_document_id},
idempotency_key=docpush:{doc_id}, run_at=now+DEBOUNCE)``。

关键约束：
- **lock 统一 ``docsync-{feishu_document_id}``**，与 83-02 pull / 83-06 poll 对同一文档完全一致
  → pull/push/poll 全串行、天然防交叉（T-83-03-DOS）。
- **debounce 合并**：``run_at=now+DOC_SYNC_DEBOUNCE_SECONDS`` + ``idempotency_key=docpush:{doc_id}``
  让窗口内多次写去重合并为一份 todo（不逐写即时推）。
- **fail-soft 绝不反噬**：解析/投递任何失败只记 warning，**绝不**阻断 DB 写主流程（T-83-03-FAILSOFT）。
- **防回声**：飞书镜像编辑（origin=feishu_sync）由调用方传 ``_skip_doc_push=True`` 不触发（防 pull→push 回声）。
- 钩子放 service 层（INV-6 单一入口），不放 model signal。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = structlog.get_logger(__name__)

__all__ = ["DOC_SYNC_DEBOUNCE_SECONDS", "schedule_doc_push"]

_COMPONENT = "doc_sync"

# debounce 静默窗口：系统区多次写在该窗口内合并为一次 push（秒级最终一致，抗飞书频控）。
DOC_SYNC_DEBOUNCE_SECONDS = 5


async def schedule_doc_push(
    *,
    project_id: Any,
    doc_type: str,
    initiated_by_user_id: str | None = None,
) -> None:
    """系统区写后 fail-soft 调度一次 debounce 合并的 block 级推送（绝不反噬 DB 写）。

    无对应 ProjectDoc / 无 ``feishu_document_id`` → 静默跳过（未建飞书镜像，无可推）。
    """
    try:
        resolved = await _resolve_doc(project_id, doc_type)
        if resolved is None:
            return
        doc_id, feishu_document_id = resolved
        if not feishu_document_id:
            return

        from durable.queues import QUEUE_DOC_SYNC
        from durable.service import DurableTaskService

        await DurableTaskService.defer(
            "durable_doc_sync_push",
            {"doc_id": doc_id},
            queue=QUEUE_DOC_SYNC,
            lock=f"docsync-{feishu_document_id}",
            idempotency_key=f"docpush:{doc_id}",
            run_at=timezone.now() + timedelta(seconds=DOC_SYNC_DEBOUNCE_SECONDS),
            initiated_by_user_id=initiated_by_user_id,
        )
        logger.debug(
            "doc_push_scheduled",
            doc_id=doc_id,
            doc_type=doc_type,
            component=_COMPONENT,
            category="caller",
        )
    except Exception as exc:  # noqa: BLE001 — 投递失败 fail-soft，绝不阻断 DB 写主流程
        logger.warning(
            "doc_push_schedule_failed",
            doc_type=doc_type,
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )


@sync_to_async
def _resolve_doc(project_id: Any, doc_type: str) -> tuple[str, str] | None:
    """按 (project, doc_type) 取 ProjectDoc 的 (id, feishu_document_id)（只读，无副作用）。"""
    from initiatives.models import ProjectDoc

    row = (
        ProjectDoc.objects.filter(project_id=project_id, doc_type=doc_type)
        .values("id", "feishu_document_id")
        .first()
    )
    if row is None:
        return None
    return str(row["id"]), row["feishu_document_id"] or ""
