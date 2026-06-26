"""TTL 兜底轮询（SYNC-01 漏事件兜底，83-06）。

``drive.file.edit_v1`` 订阅/事件可能丢（订阅失败退化、回调网络抖动、app 重启窗口），
本周期任务兜底：遍历**进行中项目**（``Project.status == developing``）的 **READY**（已就绪、
非 broken）且已绑定飞书文档 id 的 ``ProjectDoc``，回拉飞书正文比对 revision 漂移，变了即
``defer durable_doc_sync_pull``——与事件链路对**同一文档共用** ``lock=docsync-{feishu_document_id}``
串行 + ``idempotency_key`` 去重防重复落库（poll→pull 与事件→pull 殊途同归、不重复 apply）。

复用 ``poll_repository_updates`` 范式：单条 ``try/except`` 隔离（单 doc 异常绝不阻断整批）、
结构化 ``{checked, triggered}`` 返回。归因 **system**（系统调度，无触发用户）。

约束（与观测规范一致）：
- best-effort 绝不反噬：单 doc 取材/比对/入队异常吞掉记采样 warning，继续其余。
- 归档项目 doc 不进 poll（项目 status gate）；broken doc 不进 poll（sync_status==READY gate）
  → 不被反复触发 pull（T-83-06-DOS）。
- revision 代理用回拉正文的归一化指纹（``block_content_hash``，与 block diff 同口径）比对
  ``last_synced_snapshot`` 指纹；真实飞书整型 revision 回填留 A5 live 验证（不依赖真机）。
- 仅记 doc_id/revision 指纹/计数，**绝不**记 token / 正文明文（T-83-06-INFO）；单 doc 比对 debug。
"""

from __future__ import annotations

import time

import structlog
from asgiref.sync import sync_to_async

from initiatives.models import DocSyncStatus, ProjectDoc, ProjectStatus

logger = structlog.get_logger(__name__)

__all__ = ["poll_project_docs_revisions"]

_COMPONENT = "doc_sync"


@sync_to_async
def _list_pollable_docs() -> list[ProjectDoc]:
    """进行中项目的 READY 且已绑定飞书 id 的 doc（预取 project+space，防 async lazy FK）。

    归档/终止项目（status != developing）与 broken/pending doc 天然被过滤——不进 poll，
    避免对已停同步/失效文档反复触发 pull（T-83-06-DOS）。
    """
    qs = (
        ProjectDoc.objects.select_related("project", "project__space")
        .filter(
            project__status=ProjectStatus.DEVELOPING,
            sync_status=DocSyncStatus.READY,
        )
        .exclude(feishu_document_id="")
    )
    return list(qs)


async def poll_project_docs_revisions() -> dict[str, int]:
    """遍历进行中项目 READY doc 比对 revision，漂移即 defer pull（兜底漏事件）。

    单实例（apscheduler ``max_instances=1``）+ 单 doc try/except 隔离；返回
    ``{"checked": n, "triggered": m}``。归因 system。
    """
    started = time.monotonic()
    docs = await _list_pollable_docs()

    logger.info(
        "doc_sync_poll_started",
        checked=len(docs),
        initiated_by_user_id="system",
        component=_COMPONENT,
        category="caller",
    )

    checked = 0
    triggered = 0
    for doc in docs:
        checked += 1
        try:
            if await _check_and_defer(doc):
                triggered += 1
        except Exception as exc:  # noqa: BLE001 — 单 doc 异常隔离，绝不阻断整批
            logger.warning(
                "doc_sync_poll_doc_failed",
                doc_id=str(doc.id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    logger.info(
        "doc_sync_poll_completed",
        checked=checked,
        triggered=triggered,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        initiated_by_user_id="system",
        component=_COMPONENT,
        category="caller",
    )
    return {"checked": checked, "triggered": triggered}


async def _check_and_defer(doc: ProjectDoc) -> bool:
    """回拉某 doc 正文比对 revision；漂移→defer durable_doc_sync_pull，返回是否 defer。"""
    from initiatives.services.doc_sync_diff import block_content_hash
    from initiatives.services.doc_sync_service import DocSyncService

    client = await DocSyncService._build_doc_client(doc.project.space)
    markdown, _blocks = await client.get_document_content(doc.feishu_document_id)

    revision = block_content_hash(markdown)
    baseline = block_content_hash(doc.last_synced_snapshot or "")
    if revision == baseline:
        # 未漂移：飞书侧自上次同步未变 → 不 defer（避免无谓 pull / 重复落库）。
        logger.debug(
            "doc_sync_poll_no_drift",
            doc_id=str(doc.id),
            component=_COMPONENT,
            category="sampling",
        )
        return False

    from durable.queues import QUEUE_DOC_SYNC
    from durable.service import DurableTaskService

    # lock=docsync-{feishu_document_id} 与 83-02 pull / 83-03 push 对同一文档完全一致
    # （三处同值 → pull/push/poll 全串行）；idempotency_key 去重同一 revision 的重复 poll，
    # 经同 lock 与事件→pull 串行、防重复 apply。归因 system（无触发用户）。
    await DurableTaskService.defer(
        "durable_doc_sync_pull",
        {"file_token": doc.feishu_document_id, "event_id": f"poll:{revision}"},
        queue=QUEUE_DOC_SYNC,
        lock=f"docsync-{doc.feishu_document_id}",
        idempotency_key=f"docpull:{doc.feishu_document_id}:poll:{revision}",
        initiated_by_user_id="system",
    )
    logger.debug(
        "doc_sync_poll_drift_deferred",
        doc_id=str(doc.id),
        component=_COMPONENT,
        category="sampling",
    )
    return True
