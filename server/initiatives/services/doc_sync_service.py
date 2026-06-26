"""DocSyncService —— 飞书↔Friday 文档同步编排（SYNC-01~06）。

本计划（83-02）落 ``.pull``（飞书→Friday 回拉链路，SYNC-01）：

    回拉正文（get_document_content）→ doc_sync_diff 结构化分类（block_id + content_hash）
    → 经 ProjectDocService / MemoryService 写收口 → CAS 推进 last_synced_revision
    → 失效渲染缓存（invalidate_doc_render）。

push（83-03）/ 真三方合并冲突编排（83-04）/ TTL 轮询兜底（83-06）留后续计划。

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

from common.logging import redact_secrets_in_text
from initiatives.models import (
    DocSyncStatus,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectStatus,
)
from initiatives.services.doc_sync_cache import invalidate_doc_render
from initiatives.services.doc_sync_diff import BlockDiff, diff_blocks

logger = structlog.get_logger(__name__)

__all__ = ["DocSyncService"]

_COMPONENT = "doc_sync"


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

        theirs = self._normalize_theirs_blocks(raw_blocks, blocks_to_markdown)
        block_map = await self._load_block_map(doc.id)
        diffs = diff_blocks(
            base_snapshot=doc.last_synced_snapshot,
            theirs_blocks=theirs,
            block_map=block_map,
        )

        counts = {"added": 0, "edited": 0, "deleted": 0, "captured": 0}
        for d in diffs:
            await self._apply_diff(doc, d, initiated_by_user_id, counts)

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
            applied = False
            if is_memory and d.db_ref:
                applied = await self._memory_edit(
                    d.db_ref, d.content, initiated_by_user_id
                )
            if not applied:
                # 飞书优先覆盖快照 + capture 飞书侧内容留痕（never-drop，SYNC-04）。
                # TODO(83-04): 真三方合并（base=last_synced / theirs=飞书 / ours=DB），
                # 相交冲突落败方 capture + 飞书评论提示；本期最简“飞书优先 + 留痕”。
                await svc.capture_block_revision(
                    doc_id=doc.id,
                    feishu_block_id=d.feishu_block_id,
                    content=d.content,
                    db_ref=d.db_ref,
                    source="feishu",
                    reason="pull_edit",
                )
                counts["captured"] += 1
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
            )
        except Exception as exc:  # noqa: BLE001 — MEMORY 写失败不反噬整条 pull（脱敏后记 warning）
            self._log_memory_write_failed("append", exc)
            return None

    async def _memory_edit(
        self, memory_id: str, content: str, initiated_by_user_id: str | None
    ) -> bool:
        """飞书编辑块 → 编辑对应记忆（成员可编辑；非成员/异常返回 False 交调用方 capture 留痕）。"""
        from initiatives.services.memory_service import MemoryError, MemoryService

        editor = await self._resolve_user(initiated_by_user_id)
        try:
            await MemoryService().edit(
                memory_id=memory_id,
                content=content,
                editor=editor,
                initiated_by_user_id=initiated_by_user_id,
            )
            return True
        except MemoryError:
            # 非成员飞书编辑（MEM-02 fail-closed）/ 状态非法 → 不就地改，交 capture 留痕（never-drop）。
            return False
        except Exception as exc:  # noqa: BLE001 — 其余异常脱敏记 warning，交 capture 留痕
            self._log_memory_write_failed("edit", exc)
            return False

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
