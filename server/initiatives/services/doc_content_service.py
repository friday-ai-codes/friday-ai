"""DocContentService —— 工作区单文档内容读取 + 人工区写回编排（WB-03，84-01）。

为前端工作台补齐 Phase 82/83 之上缺失的「取单文档正文 + block 分区」「人工区写回」读写面：

- ``get_doc_render``：读单个 ``ProjectDoc`` 的渲染 markdown（复用 ``last_synced_snapshot`` +
  渲染缓存，**不**新写飞书拉取）+ block 列表（每 block 标注 system/human 分区与 editable）。
- ``update_human_blocks``：仅接受/写入 ``section==HUMAN`` 的 block 文本，拒绝任何 system block
  写入（系统区只读）；写收口经 ``ProjectDocService.write_human_block``（INV-6，append-only 留痕 +
  刷新映射指纹），写后 enqueue 既有 ``durable_doc_sync_push``（DB→飞书 block 级增量，**永不整篇
  覆盖**）。写操作仅项目成员（WS-02 fail-closed，复用 ``ProjectMember`` 成员校验）。

关键约束：
- **不旁路写表（INV-6）**：本 service 只**读** ProjectDoc/BlockMap/BlockRevision/StateApi/Memory
  组装内容；一切写经 ``ProjectDocService``（结构化）/ ``MemoryService``（记忆）。
- **系统区只读**：``editable = (section == HUMAN)``；human-blocks 写回拒绝 system block。
- **可观测性（强制）**：``project_doc_content_read``（caller）、人工区写回三态
  ``project_doc_human_write_started/completed/failed``（带 ``duration_ms`` / 写回 block 数 /
  sync 调度结果），全部 ``category=caller``、``component=initiatives.workspace``，绑定触发用户；
  异常文本经 ``redact_secrets_in_text``，best-effort 观测绝不反噬主流程。
- **async ORM 走 sync_to_async**；预取避免 async lazy FK。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from initiatives.models import (
    DocSection,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectDocBlockRevision,
    ProjectMember,
    ProjectMemory,
    ProjectStateApi,
)
from initiatives.services.doc_push_scheduler import schedule_doc_push
from initiatives.services.project_doc_service import ProjectDocService

logger = structlog.get_logger(__name__)

__all__ = [
    "DocContentService",
    "DocContentError",
    "DocContentNotFound",
    "SystemReadOnlyError",
    "HumanWriteForbidden",
    "ALLOWED_DOC_TYPES",
    "SYNC_STATUS_SYNCING",
]

_COMPONENT = "initiatives.workspace"

# 合法 doc_type 闭集（与 DocType 枚举一致）：非法值在 view 层 400。
ALLOWED_DOC_TYPES: frozenset[str] = frozenset(DocType.values)

# 人工区写回响应的瞬态同步态（前端据此轮询 doc 内容 GET 的 sync_status）。
# 非 DB DocSyncStatus 枚举值，仅作写回响应提示。
SYNC_STATUS_SYNCING = "syncing"


class DocContentError(Exception):
    """文档内容操作非法基类（view 层默认转 400）。"""


class DocContentNotFound(DocContentError):
    """文件/区块不存在（view 层转 404）。"""


class SystemReadOnlyError(DocContentError):
    """尝试写入系统区 block（系统区只读，view 层转 409）。"""


class HumanWriteForbidden(DocContentError):
    """非项目成员写人工区（WS-02 fail-closed，view 层转 403）。"""


class DocContentService:
    """工作区单文档内容读取 + 人工区写回编排（写收口经 ProjectDocService，INV-6）。"""

    # ---- 读：单文档渲染 + block 分区（Task 1）----

    async def get_doc_render(
        self, *, project_id: Any, doc_type: str
    ) -> dict[str, Any] | None:
        """读单文档渲染 markdown + block 分区列表；文件不存在返回 None（view 转 404）。

        ``rendered_markdown`` 复用 ``last_synced_snapshot`` + 渲染缓存（read-through），
        **不**新写飞书拉取。blocks 每项标注 ``section``(system/human) 与
        ``editable``(=section==HUMAN)，并尽力解析 ``text``（系统区按 db_ref 渲染、人工区取
        最新留痕）。
        """
        started = time.monotonic()
        doc = await self._aget_doc(project_id, doc_type)
        if doc is None:
            return None

        rendered = await self._resolve_rendered_markdown(doc)
        blocks = await self._build_blocks(doc["id"], doc_type, project_id)

        logger.info(
            "project_doc_content_read",
            project_id=str(project_id),
            doc_type=doc_type,
            doc_id=str(doc["id"]),
            block_count=len(blocks),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
        return {
            "doc_type": doc_type,
            "sync_status": doc["sync_status"],
            "last_synced_revision": doc["last_synced_revision"],
            "rendered_markdown": rendered,
            "blocks": blocks,
        }

    async def _resolve_rendered_markdown(self, doc: dict[str, Any]) -> str:
        """渲染 markdown：渲染缓存命中即返回；未命中以 ``last_synced_snapshot`` 回填。"""
        from initiatives.services.doc_sync_cache import get_doc_render, set_doc_render

        cached = await sync_to_async(get_doc_render)(doc["id"])
        if cached is not None:
            return cached
        snapshot = doc["last_synced_snapshot"] or ""
        if snapshot:
            await sync_to_async(set_doc_render)(doc["id"], snapshot)
        return snapshot

    @sync_to_async
    def _aget_doc(self, project_id: Any, doc_type: str) -> dict[str, Any] | None:
        row = (
            ProjectDoc.objects.filter(project_id=project_id, doc_type=doc_type)
            .values("id", "sync_status", "last_synced_revision", "last_synced_snapshot")
            .first()
        )
        return dict(row) if row else None

    @sync_to_async
    def _build_blocks(
        self, doc_id: Any, doc_type: str, project_id: Any
    ) -> list[dict[str, Any]]:
        """组装 block 列表（system 先 human 后，按 created_at 保序）；只读，无副作用。"""
        rows = list(
            ProjectDocBlockMap.objects.filter(doc_id=doc_id)
            .order_by("section", "created_at")
            .values("feishu_block_id", "db_ref", "section", "content_hash")
        )

        # 人工区当前态：取最新一条 human 留痕（append-only，最近一条即当前）。
        human_text: dict[str, str] = {}
        human_ids = [r["feishu_block_id"] for r in rows if r["section"] == DocSection.HUMAN]
        if human_ids:
            for bid in human_ids:
                rev = (
                    ProjectDocBlockRevision.objects.filter(
                        doc_id=doc_id, feishu_block_id=bid, source="human"
                    )
                    .order_by("-captured_at")
                    .values("content")
                    .first()
                )
                human_text[bid] = (rev["content"] if rev else "") or ""

        # 系统区 db_ref → 渲染态（与 push 渲染口径一致：STATE/MEMORY 可解析，余留空）。
        out: list[dict[str, Any]] = []
        for r in rows:
            section = r["section"]
            if section == DocSection.HUMAN:
                text = human_text.get(r["feishu_block_id"], "")
            else:
                text = self._resolve_system_text(doc_type, r["db_ref"])
            out.append(
                {
                    "block_id": r["feishu_block_id"],
                    "db_ref": r["db_ref"],
                    "section": section,
                    "text": text,
                    "editable": section == DocSection.HUMAN,
                }
            )
        return out

    @staticmethod
    def _resolve_system_text(doc_type: str, db_ref: str) -> str:
        """系统区 block 文本：按 doc_type + db_ref 渲染（STATE/MEMORY），其余返回空串。"""
        if not db_ref:
            return ""
        if doc_type == DocType.STATE:
            api_row = (
                ProjectStateApi.objects.filter(pk=db_ref)
                .values("method", "path", "status")
                .first()
            )
            if not api_row:
                return ""
            return f"{api_row['method']} {api_row['path']} — {api_row['status']}"
        if doc_type == DocType.MEMORY:
            mem_row = ProjectMemory.objects.filter(pk=db_ref).values("content").first()
            if not mem_row:
                return ""
            return mem_row["content"] or ""
        return ""

    # ---- 写：人工区 block 回写（Task 2，触发同步引擎 block 级回灌）----

    async def update_human_blocks(
        self,
        *,
        project_id: Any,
        doc_type: str,
        blocks: list[dict[str, str]],
        user: Any,
    ) -> dict[str, Any]:
        """写人工区 block 文本并 enqueue block 级 push（永不整篇覆盖）。

        - 写权限仅项目成员（WS-02 fail-closed），非成员 ``HumanWriteForbidden`` → 403。
        - 仅写 ``section==HUMAN`` 的 block；命中 system block → ``SystemReadOnlyError`` → 409；
          未知 block_id → ``DocContentNotFound`` → 404。
        - 写收口经 ``ProjectDocService.write_human_block``（INV-6），写后 enqueue 既有
          ``durable_doc_sync_push``（DB→飞书 block 级增量）。返回瞬态 ``sync_status=syncing``。
        """
        started = time.monotonic()
        uid = getattr(user, "id", None)
        uid_repr = str(uid) if uid else "system"
        logger.info(
            "project_doc_human_write_started",
            project_id=str(project_id),
            doc_type=doc_type,
            block_count=len(blocks),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )
        try:
            await self._assert_member(project_id, user)
            doc = await self._aget_doc(project_id, doc_type)
            if doc is None:
                raise DocContentNotFound("工作区文件不存在")
            sections = await self._load_block_sections(doc["id"])

            # 全量校验后再写（任一非法整体拒绝，避免半写）。
            for block in blocks:
                bid = block["block_id"]
                section = sections.get(bid)
                if section is None:
                    raise DocContentNotFound(f"block 不存在：{bid}")
                if section != DocSection.HUMAN:
                    raise SystemReadOnlyError("系统区由 Friday 自动维护，只读")

            svc = ProjectDocService()
            for block in blocks:
                await svc.write_human_block(
                    doc_id=doc["id"],
                    feishu_block_id=block["block_id"],
                    content=block.get("text", ""),
                    editor=user,
                )

            # 人工区写后 enqueue block 级 push（fail-soft，绝不反噬写主流程）。
            await schedule_doc_push(
                project_id=project_id,
                doc_type=doc_type,
                initiated_by_user_id=uid_repr if uid else None,
            )
        except DocContentError as exc:
            logger.info(
                "project_doc_human_write_failed",
                project_id=str(project_id),
                doc_type=doc_type,
                reason=type(exc).__name__,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                initiated_by_user_id=uid_repr,
                component=_COMPONENT,
                category="caller",
            )
            raise
        except Exception as exc:  # noqa: BLE001 — 非预期异常记 failed 后上抛（view 转 500）
            logger.warning(
                "project_doc_human_write_failed",
                project_id=str(project_id),
                doc_type=doc_type,
                reason="unexpected",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                initiated_by_user_id=uid_repr,
                component=_COMPONENT,
                category="caller",
            )
            raise

        logger.info(
            "project_doc_human_write_completed",
            project_id=str(project_id),
            doc_type=doc_type,
            written=len(blocks),
            sync_scheduled=True,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )
        return {
            "doc_type": doc_type,
            "written": len(blocks),
            "sync_status": SYNC_STATUS_SYNCING,
        }

    # ---- 成员校验（WS-02 fail-closed，复用 ProjectMember）----

    async def _assert_member(self, project_id: Any, user: Any) -> None:
        uid = getattr(user, "id", None)
        if uid is None or not getattr(user, "is_authenticated", False):
            raise HumanWriteForbidden("仅项目成员可编辑人工区")
        is_member = await sync_to_async(self._is_member_sync)(project_id, uid)
        if not is_member:
            raise HumanWriteForbidden("仅项目成员可编辑人工区")

    @staticmethod
    def _is_member_sync(project_id: Any, uid: Any) -> bool:
        return ProjectMember.objects.filter(
            project_id=project_id, user_id=uid
        ).exists()

    @sync_to_async
    def _load_block_sections(self, doc_id: Any) -> dict[str, str]:
        return {
            r["feishu_block_id"]: r["section"]
            for r in ProjectDocBlockMap.objects.filter(doc_id=doc_id).values(
                "feishu_block_id", "section"
            )
        }
