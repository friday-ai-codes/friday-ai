"""DocSyncService —— 飞书↔Friday 文档同步编排（SYNC-01~06）。

本模块落飞书↔Friday 双向同步编排：

- ``.pull``（83-02，飞书→Friday 回拉，SYNC-01）：回拉正文（get_document_content）→
  doc_sync_diff 结构化分类（block_id + content_hash）→ 经 ProjectDocService / MemoryService
  写收口 → CAS 推进 last_synced_revision → 失效渲染缓存（invalidate_doc_render）。
- ``.push``（83-03，Friday→飞书 推送，SYNC-02）：DB **系统区**写触发 → 渲染系统区期望态 →
  与 block_map(section=system) 经 diff_blocks 比对 → 新增走 ``create_children`` / 改走
  ``update_block`` / 删走 ``delete_blocks``（按 index 范围）→ **永不整篇 replace** →
  ``upsert_block_map`` 更新指纹 + CAS 推进水位 → 失效缓存。per-doc 串行靠 durable
  ``lock=docsync-{feishu_document_id}``（与 pull/poll 同文档同值），限流靠 client 层 ``@retry``。

真三方合并冲突编排（83-04）/ 编辑感知延迟写 + 乐观并发 rebase（83-04）/ TTL 轮询兜底
（83-06）留后续计划。push 本期只对 MEMORY/STATE 渲染系统区期望态；MILESTONES/RESEARCH/
PREFLIGHT 的系统派生区渲染留后续（无渲染器即跳过，**绝不**对空期望态盲删既有块）。

关键约束（与 83-CONTEXT / 观测规范一致）：
- **不旁路写表（INV-6）**：``ProjectDoc`` / ``ProjectDocBlockMap`` / ``ProjectDocBlockRevision``
  写一律经 ``ProjectDocService``；MEMORY 条目写经 ``MemoryService``。本 service 只**读**
  ProjectDoc/BlockMap 组装 diff 输入（由 ``test_doc_sync_inv6_guard`` grep 守护）。
- **fail-soft 绝不反噬**：找不到 doc / 项目非 developing / sync_status==broken / 回拉失败
  → 记 skipped/failed 后返回，**绝不抛回 webhook / 编辑主流程**；回拉失败 / 文档被删置 broken
  （供 ``rebuild_workspace`` 一键重建，Pitfall 6）。
- **脱敏不可绕过**：飞书正文 / 异常文本入日志前经 ``redact_secrets_in_text``；只记
  doc_id/doc_type/计数/op，**绝不**记 token / 正文明文（T-83-02-INFO）。
- **归因**：worker 入口已 bind ``initiated_by_user_id``（未映射 system）；MEMORY 写转发
  ``initiated_by_user_id``。OQ-1：飞书镜像编辑走独立 sync 路径（``_skip_member_check`` /
  非成员 capture 留痕），保持 MEM-02 对“前端贡献”仍 fail-closed，且 capture-never-clobber。
- **async ORM 走 sync_to_async**；预取 project/space（防 async lazy FK，Pitfall: Phase 82 已踩）。
- **乐观并发（Pitfall 3）**：推进水位走 ``ProjectDocService.advance_sync_revision`` CAS，不依赖
  durable doing 锁（in-process fallback 忽略 lock）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.logging import redact_secrets_in_text
from initiatives.models import (
    ApiStatus,
    DocSection,
    DocSyncStatus,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectMemory,
    ProjectMemoryStatus,
    ProjectStateApi,
    ProjectStatus,
)
from initiatives.services.doc_sync_cache import invalidate_doc_render
from initiatives.services.doc_sync_diff import (
    BlockDiff,
    block_content_hash,
    diff_blocks,
    three_way_merge,
)

logger = structlog.get_logger(__name__)

__all__ = ["DocSyncService"]

_COMPONENT = "doc_sync"

# 编辑感知延迟写（OQ-3）：push 前若距 last_feishu_edit_at 不足该窗口（秒）判为「用户活跃编辑中」，
# 不抢写、重排 run_at 延迟落，避免与用户飞书编辑冲撞（防 T-83-04-RACE）。
DOC_SYNC_ACTIVE_EDIT_WINDOW = 15
# 活跃时重排推送的延迟（秒），到静默窗口再尝试落。
DOC_SYNC_DEFER_SECONDS = 10
# 乐观并发 rebase 有限重试上限（CAS 落空→pull rebase 再推），绝不死循环（Pitfall 3）。
_MAX_PUSH_REBASE_ATTEMPTS = 3
# 系统区落败方飞书评论提示文案（capture-never-clobber 时 best-effort 提示，绝不阻断）。
_CAPTURE_COMMENT_TEXT = "此段由系统维护，您的修改已留痕保存，请写到人工编辑区以免被覆盖。"


class DocSyncService:
    """飞书↔Friday 文档同步编排（写入收口于 ProjectDocService/MemoryService，INV-6）。"""

    async def pull(
        self,
        *,
        file_token: str,
        event_id: str = "",
        initiated_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """飞书→Friday 回拉一篇文档并结构化写回（SYNC-01，best-effort fail-soft）。

        ``file_token`` 即飞书 docx 的 ``feishu_document_id``。归档 / broken / 找不到 doc
        在入口 fail-soft 跳过；回拉 / 应用任何异常都被吞掉并置 broken，**绝不抛回事件主流程**。
        """
        uid_repr = initiated_by_user_id or "system"
        started = time.monotonic()

        doc = await self._aget_doc_by_file_token(file_token)
        if doc is None:
            self._log_skipped(file_token, event_id, uid_repr, "doc_not_found")
            return {"status": "skipped", "reason": "doc_not_found"}
        if doc.project.status != ProjectStatus.DEVELOPING:
            # 项目归档/终止 → 停双向同步（Pitfall 6），fail-soft 跳过（退订留生命周期编排）。
            self._log_skipped(file_token, event_id, uid_repr, "project_not_developing")
            return {"status": "skipped", "reason": "project_not_developing"}
        if doc.sync_status == DocSyncStatus.BROKEN:
            self._log_skipped(file_token, event_id, uid_repr, "doc_broken")
            return {"status": "skipped", "reason": "doc_broken"}

        logger.info(
            "doc_sync_pull_started",
            file_token=file_token,
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            event_id=event_id,
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )

        try:
            result = await self._pull_apply(doc, initiated_by_user_id)
        except Exception as exc:  # noqa: BLE001 — 回拉/应用失败 fail-soft，置 broken 绝不反噬
            from initiatives.services.project_doc_service import ProjectDocService

            reason = self._classify_pull_error(exc)
            try:
                await ProjectDocService().set_sync_status(
                    doc_id=doc.id, status=DocSyncStatus.BROKEN
                )
            except Exception:  # noqa: BLE001 — 连置 broken 都失败也不抛
                pass
            logger.warning(
                "doc_sync_pull_failed",
                file_token=file_token,
                doc_id=str(doc.id),
                doc_type=doc.doc_type,
                reason=reason,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                initiated_by_user_id=uid_repr,
                component=_COMPONENT,
                category="caller",
            )
            return {"status": "failed", "reason": reason}

        logger.info(
            "doc_sync_pull_completed",
            file_token=file_token,
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
            **result,
        )
        return {"status": "ok", **result}

    # ---- pull 内部流水线 ----

    async def _pull_apply(
        self, doc: ProjectDoc, initiated_by_user_id: str | None
    ) -> dict[str, Any]:
        """回拉正文 → diff → 写收口 → CAS 推进水位 → 失效缓存（异常上抛由 pull 统一 fail-soft）。"""
        from services.feishu_doc import blocks_to_markdown

        client = await self._build_doc_client(doc.project.space)
        # 回拉正文（DocumentNotFoundError 等错误由 pull 捕获置 broken）。
        markdown, raw_blocks = await client.get_document_content(doc.feishu_document_id)

        # 记录飞书侧编辑时间（编辑感知延迟写探测源，OQ-3）：drive 事件回拉即视为最近编辑。
        from initiatives.services.project_doc_service import ProjectDocService

        await ProjectDocService().touch_feishu_edit(doc_id=doc.id, at=timezone.now())

        theirs = self._normalize_theirs_blocks(raw_blocks, blocks_to_markdown)
        block_map = await self._load_block_map(doc.id)
        diffs = diff_blocks(
            base_snapshot=doc.last_synced_snapshot,
            theirs_blocks=theirs,
            block_map=block_map,
        )

        counts = {"added": 0, "edited": 0, "deleted": 0, "captured": 0}
        for d in diffs:
            await self._apply_diff(doc, d, block_map, client, initiated_by_user_id, counts)

        # CAS 推进水位（乐观并发）：以入口读到的 revision 为期望值。真实飞书 revision 整型
        # 回填留 A5 live 验证；本期用单调 +1 推进（不依赖飞书 revision，仍保证 CAS 语义）。
        expected = doc.last_synced_revision
        advanced = await self._advance(doc.id, expected, expected + 1, markdown)

        invalidate_doc_render(doc.id)

        return {"diffs": len(diffs), "advanced": advanced, **counts}

    async def _apply_diff(
        self,
        doc: ProjectDoc,
        d: BlockDiff,
        block_map: dict[str, dict[str, str]],
        client: Any,
        initiated_by_user_id: str | None,
        counts: dict[str, int],
    ) -> None:
        """单块结构化变更写回（写收口经 ProjectDocService/MemoryService）。"""
        from initiatives.services.project_doc_service import ProjectDocService

        svc = ProjectDocService()
        is_memory = doc.doc_type == DocType.MEMORY

        if d.op == "added":
            db_ref = d.db_ref
            if is_memory:
                memory = await self._memory_append(
                    doc.project_id, d.content, initiated_by_user_id
                )
                if memory is not None:
                    db_ref = str(memory.id)
            await svc.upsert_block_map(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                db_ref=db_ref,
                section=d.section,
                content_hash=d.content_hash,
            )
            counts["added"] += 1

        elif d.op == "edited":
            base_hash = self._mapped_hash(block_map.get(d.feishu_block_id))
            if is_memory:
                await self._apply_memory_edit(
                    doc, d, initiated_by_user_id, client, counts
                )
            else:
                await self._apply_generic_edit(doc, d, base_hash, client, counts)
            # 飞书侧 merged 即新态：推进 block_map 指纹（飞书优先覆盖快照）。
            await svc.upsert_block_map(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                db_ref=d.db_ref,
                section=d.section,
                content_hash=d.content_hash,
            )
            counts["edited"] += 1

        elif d.op == "deleted":
            if is_memory and d.db_ref:
                await self._memory_supersede(d.db_ref, initiated_by_user_id)
            await svc.clear_block_map(doc_id=doc.id, feishu_block_id=d.feishu_block_id)
            counts["deleted"] += 1

        # 高频内部步骤：per-block sampling + debug（绝不 INFO 刷屏，Pitfall 7）。
        logger.debug(
            "doc_block_diff_applied",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            op=d.op,
            feishu_block_id=d.feishu_block_id,
            section=d.section,
            component=_COMPONENT,
            category="sampling",
        )

    # ---- pull 同块冲突三方合并（base=last-synced / theirs=飞书 / ours=DB，SYNC-04）----

    async def _apply_generic_edit(
        self,
        doc: ProjectDoc,
        d: BlockDiff,
        base_hash: str,
        client: Any,
        counts: dict[str, int],
    ) -> None:
        """非 MEMORY 同块编辑：三方合并飞书优先；相交冲突落败系统侧 capture（绝不静默丢）。

        ``ours``（DB 系统态）能解析时走 ``three_way_merge``：仅飞书改→自动并（不产 revision）；
        两侧都改且相交→DB 取飞书侧 merged、落败方（ours）经 ``capture_block_revision`` 留
        ``ProjectDocBlockRevision`` + best-effort 飞书评论。``ours`` 不可解析（db_ref 空/无渲染器）
        → 退回 83-02「飞书优先 + 留痕」（source=feishu），仍 never-drop。
        """
        from initiatives.services.project_doc_service import ProjectDocService

        svc = ProjectDocService()
        ours = await self._resolve_ours_content(doc, d)
        if ours is None:
            # 无独立系统态可比对 → 飞书优先 + 留痕（83-02 行为，never-drop）。
            await svc.capture_block_revision(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                content=d.content,
                db_ref=d.db_ref,
                source="feishu",
                reason="pull_edit",
            )
            counts["captured"] += 1
            return

        merge = three_way_merge(
            base=self._base_for_merge(base_hash, ours), theirs=d.content, ours=ours
        )
        if merge.has_conflict:
            # 相交冲突：DB 取飞书侧 merged（飞书优先），落败系统侧 capture（绝不静默丢）。
            await svc.capture_block_revision(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                content=merge.loser,
                db_ref=d.db_ref,
                source="system",
                reason="conflict_loser",
            )
            counts["captured"] += 1
            self._log_conflict_captured(doc, d, merge.loser)
            await self._best_effort_comment(client, doc, d.feishu_block_id)
        # 不相交（仅飞书改 / 两侧改成相同）→ 自动并，飞书侧 merged 即新态，不产 revision。

    async def _apply_memory_edit(
        self,
        doc: ProjectDoc,
        d: BlockDiff,
        initiated_by_user_id: str | None,
        client: Any,
        counts: dict[str, int],
    ) -> None:
        """MEMORY 同块编辑走受限 sync 入口（OQ-1）：成员落 active+revision；非成员 capture 不进 active。

        非成员飞书编辑 fail-soft 接受（不抛、active 不变、落 revision），归因 system/unmapped，
        best-effort 飞书评论提示；任何异常兜底 capture 飞书内容（never-drop）。
        """
        from initiatives.services.memory_service import MemoryService
        from initiatives.services.project_doc_service import ProjectDocService

        if not d.db_ref:
            # 无 db_ref 映射 → 退回飞书优先 + 留痕（never-drop）。
            await ProjectDocService().capture_block_revision(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                content=d.content,
                db_ref=d.db_ref,
                source="feishu",
                reason="pull_edit",
            )
            counts["captured"] += 1
            return

        editor = await self._resolve_user(initiated_by_user_id)
        try:
            outcome = await MemoryService().sync_edit(
                memory_id=d.db_ref,
                content=d.content,
                editor=editor,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — MEMORY 写失败兜底 capture，绝不反噬整条 pull
            self._log_memory_write_failed("edit", exc)
            await ProjectDocService().capture_block_revision(
                doc_id=doc.id,
                feishu_block_id=d.feishu_block_id,
                content=d.content,
                db_ref=d.db_ref,
                source="feishu",
                reason="pull_edit",
            )
            counts["captured"] += 1
            return

        if not outcome.get("applied", False):
            # 非成员飞书编辑：已在 MemoryService 落 revision 不进 active；记归因 + 评论提示。
            counts["captured"] += 1
            self._log_nonmember_captured(doc, d, outcome.get("attribution", "system"))
            await self._best_effort_comment(client, doc, d.feishu_block_id)

    async def _resolve_ours_content(
        self, doc: ProjectDoc, d: BlockDiff
    ) -> str | None:
        """解析某块的 DB 系统态（ours），用于三方合并；不可解析返回 None（退回飞书优先）。

        - STATE：按 db_ref 取 ``ProjectStateApi`` 渲染（与 push 渲染口径一致）。
        - 其余非 MEMORY 文件：暂无 per-block DB 态（系统派生区渲染留后续）→ None。
        """
        if not d.db_ref:
            return None
        if doc.doc_type == DocType.STATE:
            return await self._aget_state_api_content(d.db_ref)
        return None

    @sync_to_async
    def _aget_state_api_content(self, db_ref: str) -> str | None:
        row = (
            ProjectStateApi.objects.filter(pk=db_ref)
            .values("method", "path", "status")
            .first()
        )
        if row is None:
            return None
        return f"{row['method']} {row['path']} — {row['status']}"

    @staticmethod
    def _base_for_merge(base_hash: str, ours: str) -> str:
        """构造三方合并 base 入参（``three_way_merge`` 仅做相等比较，无需真实 base 正文）。

        - ``ours`` 指纹 == base 指纹 → 系统侧自上次同步未改 → base 即 ours（仅飞书改→自动并）。
        - 否则系统侧也改过 → 返回与 ours/theirs 必不相等的占位（保留「两侧都改」冲突判定），
          真实 base 正文未逐块持久化（仅存 content_hash + 整篇快照），占位即可驱动正确归并。
        """
        if block_content_hash(ours) == base_hash:
            return ours
        return f"\x00base:{base_hash}"

    @staticmethod
    def _mapped_hash(mapped: Any) -> str:
        if isinstance(mapped, dict):
            return str(mapped.get("content_hash", "") or "")
        return ""

    async def _best_effort_comment(
        self, client: Any, doc: ProjectDoc, feishu_block_id: str
    ) -> None:
        """capture 落败方时给飞书块发评论提示（A4 [ASSUMED]，整段 fail-soft 绝不反噬同步）。"""
        try:
            await client.add_comment(
                doc.feishu_document_id,
                block_id=feishu_block_id,
                text=_CAPTURE_COMMENT_TEXT,
            )
        except Exception as exc:  # noqa: BLE001 — 评论失败不影响 capture/同步（DB 留痕保底）
            logger.warning(
                "doc_capture_comment_failed",
                doc_id=str(doc.id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

    @staticmethod
    def _log_conflict_captured(doc: ProjectDoc, d: BlockDiff, loser: str) -> None:
        """同块冲突落败方 capture 留痕（caller，只记落败长度计数，绝不记正文，T-83-04-INFO）。"""
        logger.info(
            "doc_block_conflict_captured",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            feishu_block_id=d.feishu_block_id,
            section=d.section,
            loser_len=len(loser or ""),
            component=_COMPONENT,
            category="caller",
        )

    @staticmethod
    def _log_nonmember_captured(
        doc: ProjectDoc, d: BlockDiff, attribution: str
    ) -> None:
        """MEMORY 非成员飞书编辑 capture（caller，记归因，不进 active，绝不记正文，OQ-1）。"""
        logger.info(
            "doc_nonmember_edit_captured",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            feishu_block_id=d.feishu_block_id,
            attribution=attribution,
            component=_COMPONENT,
            category="caller",
        )

    # ---- MEMORY 写收口（经 MemoryService，OQ-1 独立 sync 路径）----

    async def _memory_append(
        self, project_id: Any, content: str, initiated_by_user_id: str | None
    ) -> Any:
        """飞书新增块 → 追加项目记忆（_skip_member_check：飞书 sync 路径，非前端贡献）。"""
        from initiatives.services.memory_service import MemoryService

        contributor = await self._resolve_user(initiated_by_user_id)
        try:
            return await MemoryService().append(
                project_id=project_id,
                content=content,
                contributor=contributor,
                initiated_by_user_id=initiated_by_user_id,
                _skip_member_check=True,
                _skip_doc_push=True,  # 飞书镜像回写，防 pull→push 回声（T-83-03-ECHO）
            )
        except Exception as exc:  # noqa: BLE001 — MEMORY 写失败不反噬整条 pull（脱敏后记 warning）
            self._log_memory_write_failed("append", exc)
            return None

    async def _memory_supersede(
        self, memory_id: str, initiated_by_user_id: str | None
    ) -> None:
        """飞书删除块 → 废弃对应记忆（best-effort，失败不反噬；map 行仍会清）。"""
        from initiatives.services.memory_service import MemoryService

        actor = await self._resolve_user(initiated_by_user_id)
        try:
            await MemoryService().supersede(
                memory_id=memory_id,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
                _skip_doc_push=True,  # 飞书镜像回写，防 pull→push 回声（T-83-03-ECHO）
            )
        except Exception as exc:  # noqa: BLE001 — 废弃失败不反噬（脱敏记 warning）
            self._log_memory_write_failed("supersede", exc)

    @staticmethod
    def _log_memory_write_failed(op: str, exc: Exception) -> None:
        logger.warning(
            "doc_sync_memory_write_failed",
            op=op,
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )

    # ---- push：Friday→飞书 block 级增量推送（SYNC-02，83-03）----

    async def push(
        self,
        *,
        doc_id: str,
        initiated_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """DB 系统区写 → 飞书 block 级增量推送（SYNC-02，best-effort fail-soft）。

        归档 / broken / 无 ``feishu_document_id`` / 无系统区渲染器 在入口 fail-soft 跳过；
        推送任何异常都被吞掉并置 broken，**绝不抛回 debounce 钩子 / DB 写主流程**。
        per-doc 串行由 durable ``lock=docsync-{feishu_document_id}`` 保证（与 pull/poll 同值），
        限流退避由 client 层 ``@retry`` 承载。**永不整篇 replace**：只对系统区算期望态，与
        block_map(section=system) diff 后逐块 children/update/delete。
        """
        uid_repr = initiated_by_user_id or "system"
        started = time.monotonic()

        doc = await self._aget_doc_by_id(doc_id)
        if doc is None:
            self._log_push_skipped(doc_id, uid_repr, "doc_not_found")
            return {"status": "skipped", "reason": "doc_not_found"}
        if doc.project.status != ProjectStatus.DEVELOPING:
            self._log_push_skipped(doc_id, uid_repr, "project_not_developing")
            return {"status": "skipped", "reason": "project_not_developing"}
        if doc.sync_status == DocSyncStatus.BROKEN:
            self._log_push_skipped(doc_id, uid_repr, "doc_broken")
            return {"status": "skipped", "reason": "doc_broken"}
        if not doc.feishu_document_id:
            self._log_push_skipped(doc_id, uid_repr, "no_document_id")
            return {"status": "skipped", "reason": "no_document_id"}

        # 渲染系统区期望态；无渲染器（MILESTONES/RESEARCH/PREFLIGHT 留后续）→ 跳过，
        # **绝不**对空期望态把既有系统块全判为 deleted（防误删，T-83-03-CLOBBER）。
        entries = await self._render_system_entries(doc.doc_type, doc.project_id)
        if entries is None:
            self._log_push_skipped(doc_id, uid_repr, "unsupported_doc_type")
            return {"status": "skipped", "reason": "unsupported_doc_type"}

        # 编辑感知延迟写（OQ-3，gate ①）：用户活跃编辑中 → 不抢写，重排 run_at 延迟落。
        if self._is_active_edit(doc):
            await self._defer_push(doc, initiated_by_user_id)
            logger.debug(
                "doc_push_deferred_active_edit",
                doc_id=str(doc.id),
                doc_type=doc.doc_type,
                component=_COMPONENT,
                category="sampling",
            )
            return {"status": "deferred", "reason": "active_edit"}

        logger.info(
            "doc_sync_push_started",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            entries=len(entries),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )

        try:
            result = await self._push_with_rebase(doc, entries, initiated_by_user_id)
        except Exception as exc:  # noqa: BLE001 — 推送失败 fail-soft，置 broken 绝不反噬
            from initiatives.services.project_doc_service import ProjectDocService

            reason = self._classify_pull_error(exc)
            try:
                await ProjectDocService().set_sync_status(
                    doc_id=doc.id, status=DocSyncStatus.BROKEN
                )
            except Exception:  # noqa: BLE001 — 连置 broken 都失败也不抛
                pass
            logger.warning(
                "doc_sync_push_failed",
                doc_id=str(doc.id),
                doc_type=doc.doc_type,
                reason=reason,
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                initiated_by_user_id=uid_repr,
                component=_COMPONENT,
                category="caller",
            )
            return {"status": "failed", "reason": reason}

        logger.info(
            "doc_sync_push_completed",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
            **result,
        )
        return {"status": "ok", **result}

    # ---- push gate：编辑感知延迟写 + 乐观并发 rebase（83-04，不依赖真实 doing lock）----

    @staticmethod
    def _is_active_edit(doc: ProjectDoc) -> bool:
        """判定文档是否处于「用户活跃编辑」窗口（距 last_feishu_edit_at < ACTIVE_EDIT_WINDOW 秒）。"""
        last = doc.last_feishu_edit_at
        if last is None:
            return False
        delta = (timezone.now() - last).total_seconds()
        return 0 <= delta < DOC_SYNC_ACTIVE_EDIT_WINDOW

    async def _defer_push(
        self, doc: ProjectDoc, initiated_by_user_id: str | None
    ) -> None:
        """活跃编辑中重排一次延迟推送（lock/key 与 debounce 同口径），整段 fail-soft 不反噬。"""
        try:
            from datetime import timedelta

            from durable.queues import QUEUE_DOC_SYNC
            from durable.service import DurableTaskService

            await DurableTaskService.defer(
                "durable_doc_sync_push",
                {"doc_id": str(doc.id)},
                queue=QUEUE_DOC_SYNC,
                lock=f"docsync-{doc.feishu_document_id}",
                idempotency_key=f"docpush:{doc.id}",
                run_at=timezone.now() + timedelta(seconds=DOC_SYNC_DEFER_SECONDS),
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 重排失败 fail-soft，绝不反噬 push 调用方
            logger.warning(
                "doc_push_defer_failed",
                doc_id=str(doc.id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

    async def _push_with_rebase(
        self, doc: ProjectDoc, entries: list[dict[str, str]], uid: str | None
    ) -> dict[str, Any]:
        """乐观并发推送（gate ②，Pitfall 3）：CAS 推进水位落空→先 pull rebase 再重试（有限次）。

        不依赖 durable doing lock（in-process fallback 忽略 lock）：``_push_apply`` 内 CAS
        条件 update ``last_synced_revision``；并发改过（影响 0 行）→ ``advanced=False`` →
        本方法重拉 rebase（``self.pull``）再以最新水位重试，``_MAX_PUSH_REBASE_ATTEMPTS`` 上限
        防死循环。重试时 push 自身幂等（已落 block_map 的块不再重复增量）。
        """
        result: dict[str, Any] = {}
        for _attempt in range(_MAX_PUSH_REBASE_ATTEMPTS):
            result = await self._push_apply(doc, entries)
            if result.get("advanced", False):
                return result
            # CAS 落空：并发 pull/push 改过水位 → 先 pull rebase 再以最新态重试。
            logger.info(
                "doc_push_rebased",
                doc_id=str(doc.id),
                doc_type=doc.doc_type,
                initiated_by_user_id=uid or "system",
                component=_COMPONENT,
                category="caller",
            )
            await self.pull(file_token=doc.feishu_document_id, initiated_by_user_id=uid)
            refreshed = await self._aget_doc_by_id(doc.id)
            if refreshed is None:
                break
            doc = refreshed
            rerendered = await self._render_system_entries(doc.doc_type, doc.project_id)
            if rerendered is None:
                break
            entries = rerendered
        return result

    async def _push_apply(
        self, doc: ProjectDoc, entries: list[dict[str, str]]
    ) -> dict[str, Any]:
        """系统区期望态 → diff_blocks（按 db_ref 键）→ children/update/delete 增量外呼。

        复用 83-01 ``diff_blocks``：把 DB 渲染的期望块当 ``theirs_blocks``（block_id=db_ref）、
        系统区 block_map（按 db_ref 键）当 ``block_map`` 比对——新增=db_ref 无映射、编辑=指纹变、
        删除=映射有但期望态已无。**全程无整篇 PUT**：added→``create_children``、edited→
        ``update_block``、deleted→``delete_blocks``。写收口经 ProjectDocService（INV-6）。
        """
        from initiatives.services.project_doc_service import ProjectDocService

        svc = ProjectDocService()
        client = await self._build_doc_client(doc.project.space)

        # 系统区映射（按 db_ref 键，过滤 section==SYSTEM → 人工区绝不进 diff/不被改）。
        rows = await self._load_system_block_rows(doc.id)
        block_map: dict[str, object] = {
            db_ref: {"content_hash": v["content_hash"], "db_ref": db_ref, "section": "system"}
            for db_ref, v in rows.items()
        }
        # 期望态块（block_id=db_ref，作为结构化匹配键）。
        expected_blocks = [
            {
                "block_id": e["db_ref"],
                "content": e["content"],
                "section": "system",
                "db_ref": e["db_ref"],
            }
            for e in entries
            if e["db_ref"]
        ]
        diffs = diff_blocks(
            base_snapshot=doc.last_synced_snapshot,
            theirs_blocks=expected_blocks,
            block_map=block_map,
        )

        # 删除按既有块在文档中的相对位序定 index（[ASSUMED] A4：batch_delete by index）；
        # 降序删避免逐删导致后续 index 漂移。
        order = [v["feishu_block_id"] for v in rows.values()]
        counts = {"added": 0, "edited": 0, "deleted": 0}
        deleted_diffs = [d for d in diffs if d.op == "deleted"]
        non_deleted = [d for d in diffs if d.op != "deleted"]

        for d in non_deleted:
            await self._push_one(doc, d, rows, svc, client, counts)
        for d in sorted(
            deleted_diffs,
            key=lambda d: (
                order.index(rows[d.feishu_block_id]["feishu_block_id"])
                if d.feishu_block_id in rows
                else 0
            ),
            reverse=True,
        ):
            await self._push_delete(doc, d, rows, order, svc, client, counts)

        snapshot = "\n\n".join(e["content"] for e in entries)
        expected = doc.last_synced_revision
        advanced = await self._advance(doc.id, expected, expected + 1, snapshot)

        invalidate_doc_render(doc.id)
        return {"diffs": len(diffs), "advanced": advanced, **counts}

    async def _push_one(
        self,
        doc: ProjectDoc,
        d: BlockDiff,
        rows: dict[str, dict[str, str]],
        svc: Any,
        client: Any,
        counts: dict[str, int],
    ) -> None:
        """单块新增/编辑增量外呼 + 映射回写（added→children / edited→update_block）。"""
        db_ref = d.feishu_block_id  # push 侧以 db_ref 为结构化匹配键
        if d.op == "added":
            new_ids = await client.create_children(
                doc.feishu_document_id, children=[self._render_block(d.content)]
            )
            new_block_id = new_ids[0] if new_ids else f"pending-{db_ref}"
            await svc.upsert_block_map(
                doc_id=doc.id,
                feishu_block_id=new_block_id,
                db_ref=db_ref,
                section=DocSection.SYSTEM,
                content_hash=d.content_hash,
            )
            counts["added"] += 1
        elif d.op == "edited":
            feishu_block_id = rows.get(db_ref, {}).get("feishu_block_id", "")
            if feishu_block_id:
                await client.update_block(
                    doc.feishu_document_id,
                    feishu_block_id,
                    self._render_block_update(d.content),
                )
                await svc.upsert_block_map(
                    doc_id=doc.id,
                    feishu_block_id=feishu_block_id,
                    db_ref=db_ref,
                    section=DocSection.SYSTEM,
                    content_hash=d.content_hash,
                )
            counts["edited"] += 1
        self._log_block_pushed(doc, d.op, db_ref)

    async def _push_delete(
        self,
        doc: ProjectDoc,
        d: BlockDiff,
        rows: dict[str, dict[str, str]],
        order: list[str],
        svc: Any,
        client: Any,
        counts: dict[str, int],
    ) -> None:
        """单块删除增量外呼 + 清映射（deleted→delete_blocks by index）。"""
        db_ref = d.feishu_block_id
        feishu_block_id = rows.get(db_ref, {}).get("feishu_block_id", "")
        if feishu_block_id:
            idx = order.index(feishu_block_id) if feishu_block_id in order else 0
            await client.delete_blocks(
                doc.feishu_document_id, start_index=idx, end_index=idx + 1
            )
            await svc.clear_block_map(doc_id=doc.id, feishu_block_id=feishu_block_id)
        counts["deleted"] += 1
        self._log_block_pushed(doc, d.op, db_ref)

    # ---- push：系统区期望态渲染（只读，按 doc_type 分派）----

    async def _render_system_entries(
        self, doc_type: str, project_id: Any
    ) -> list[dict[str, str]] | None:
        """渲染某文件**系统区**期望态条目 ``[{db_ref, content}]``；无渲染器返回 None（跳过不删）。

        - MEMORY：active ``ProjectMemory`` 逐条镜像（db_ref=memory.id）。
        - STATE：``ProjectStateApi`` 清单逐条派生（db_ref=api.id）。
        - MILESTONES/RESEARCH/PREFLIGHT：系统派生区渲染留后续（返回 None → push 跳过，
          **绝不**对空期望态盲删既有系统块）。
        """
        if doc_type == DocType.MEMORY:
            return await self._render_memory_entries(project_id)
        if doc_type == DocType.STATE:
            return await self._render_state_entries(project_id)
        return None

    @sync_to_async
    def _render_memory_entries(self, project_id: Any) -> list[dict[str, str]]:
        rows = (
            ProjectMemory.objects.filter(
                project_id=project_id, status=ProjectMemoryStatus.ACTIVE
            )
            .order_by("created_at")
            .values("id", "content")
        )
        return [{"db_ref": str(r["id"]), "content": r["content"] or ""} for r in rows]

    @sync_to_async
    def _render_state_entries(self, project_id: Any) -> list[dict[str, str]]:
        rows = (
            ProjectStateApi.objects.filter(project_id=project_id)
            .exclude(status=ApiStatus.DEPRECATED)
            .order_by("created_at")
            .values("id", "method", "path", "status")
        )
        return [
            {
                "db_ref": str(r["id"]),
                "content": f"{r['method']} {r['path']} — {r['status']}",
            }
            for r in rows
        ]

    @sync_to_async
    def _load_system_block_rows(self, doc_id: Any) -> dict[str, dict[str, str]]:
        """系统区映射按 db_ref 键（仅 section==SYSTEM；人工区绝不进 diff/不被改）。

        返回 ``{db_ref: {feishu_block_id, content_hash}}``，按 created_at 保序（供删除 index 定位）。
        """
        rows = (
            ProjectDocBlockMap.objects.filter(doc_id=doc_id, section=DocSection.SYSTEM)
            .order_by("created_at")
            .values("feishu_block_id", "db_ref", "content_hash")
        )
        out: dict[str, dict[str, str]] = {}
        for r in rows:
            if r["db_ref"]:
                out[r["db_ref"]] = {
                    "feishu_block_id": r["feishu_block_id"],
                    "content_hash": r["content_hash"],
                }
        return out

    @staticmethod
    def _render_block(content: str) -> dict[str, Any]:
        """系统区新增条目 → 飞书文本块（children API 入参，append 新块）。

        # [ASSUMED] A4：以 block_type=2 文本块承载条目；真实块结构 live 验证后回填。
        """
        return {
            "block_type": 2,
            "text": {"elements": [{"text_run": {"content": content}}], "style": {}},
        }

    @staticmethod
    def _render_block_update(content: str) -> dict[str, Any]:
        """系统区编辑条目 → update_block PATCH 请求体（就地改既有块文本）。

        # [ASSUMED] A4：``update_text_elements`` 形态；真实请求体 live 验证后回填。
        """
        return {
            "update_text_elements": {"elements": [{"text_run": {"content": content}}]}
        }

    @staticmethod
    def _log_block_pushed(doc: ProjectDoc, op: str, db_ref: str) -> None:
        """per-block 采样 + debug（绝不 INFO 刷屏；只记 op/db_ref，绝不记正文）。"""
        logger.debug(
            "doc_block_pushed",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            op=op,
            db_ref=db_ref,
            component=_COMPONENT,
            category="sampling",
        )

    @staticmethod
    def _log_push_skipped(doc_id: Any, uid_repr: str, reason: str) -> None:
        logger.info(
            "doc_sync_push_skipped",
            doc_id=str(doc_id),
            reason=reason,
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )

    # ---- 读侧 helper（无写表，INV-6 安全）----

    @sync_to_async
    def _aget_doc_by_file_token(self, file_token: str) -> ProjectDoc | None:
        """按 feishu_document_id 取 ProjectDoc，预取 project+space（防 async lazy FK）。"""
        if not file_token:
            return None
        return (
            ProjectDoc.objects.select_related("project", "project__space")
            .filter(feishu_document_id=file_token)
            .first()
        )

    @sync_to_async
    def _aget_doc_by_id(self, doc_id: Any) -> ProjectDoc | None:
        """按主键取 ProjectDoc，预取 project+space（防 async lazy FK），push 入口用。"""
        if not doc_id:
            return None
        return (
            ProjectDoc.objects.select_related("project", "project__space")
            .filter(pk=doc_id)
            .first()
        )

    @sync_to_async
    def _load_block_map(self, doc_id: Any) -> dict[str, dict[str, str]]:
        """组装 diff 输入：``{feishu_block_id: {content_hash, db_ref, section}}``（只读）。"""
        rows = ProjectDocBlockMap.objects.filter(doc_id=doc_id).values(
            "feishu_block_id", "content_hash", "db_ref", "section"
        )
        return {
            r["feishu_block_id"]: {
                "content_hash": r["content_hash"],
                "db_ref": r["db_ref"],
                "section": r["section"],
            }
            for r in rows
        }

    @sync_to_async
    def _resolve_user(self, uid: str | None) -> Any:
        """Friday 用户 id → User（system / 空 / 未命中 → None，归因仍为 system）。"""
        if not uid or uid == "system":
            return None
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=uid).first()

    @staticmethod
    async def _build_doc_client(space: Any) -> Any:
        """构建 FeishuDocClient（复用 Phase 82 工厂，入参 Space 实例）。"""
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

        return await create_feishu_doc_client_for_project(space)

    @staticmethod
    def _normalize_theirs_blocks(raw_blocks: Any, blocks_to_markdown: Any) -> list[dict]:
        """飞书回拉 blocks → diff 输入 ``[{block_id, content}]``（缺 block_id 的脏块跳过）。

        # [ASSUMED] A5: 每个 block 的稳定标识键为 ``block_id``，改文字 id 不变；逐块文本经
        # blocks_to_markdown([block]) 取材作 content（用于 content_hash 结构化匹配）。
        """
        out: list[dict] = []
        for b in raw_blocks or []:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("block_id") or "")
            if not bid:
                continue
            out.append({"block_id": bid, "content": blocks_to_markdown([b])})
        return out

    async def _advance(
        self, doc_id: Any, expected: int, new_revision: int, snapshot: str
    ) -> bool:
        from initiatives.services.project_doc_service import ProjectDocService

        return await ProjectDocService().advance_sync_revision(
            doc_id=doc_id,
            expected_revision=expected,
            new_revision=new_revision,
            snapshot=snapshot,
        )

    @staticmethod
    def _classify_pull_error(exc: Exception) -> str:
        """分类回拉错误（仅返回受控原因串，绝不含正文/异常明文）。"""
        from services.feishu_doc import (
            DocumentNotFoundError,
            PermissionDeniedError,
            RateLimitError,
        )

        if isinstance(exc, DocumentNotFoundError):
            return "document_not_found"
        if isinstance(exc, PermissionDeniedError):
            return "permission_denied"
        if isinstance(exc, RateLimitError):
            return "rate_limited"
        return "pull_error"

    @staticmethod
    def _log_skipped(
        file_token: str, event_id: str, uid_repr: str, reason: str
    ) -> None:
        logger.info(
            "doc_sync_pull_skipped",
            file_token=file_token,
            event_id=event_id,
            reason=reason,
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )
