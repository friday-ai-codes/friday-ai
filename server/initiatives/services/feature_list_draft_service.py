"""feature list 异步解析草稿服务（状态机 + 进度 + WS 推送 + commit）。

把「粘贴文档 → AI 分层解析」重构为 durable 后台任务：

- ``astart_parse``：写草稿 + defer 父任务，立即返回（多项目不互相阻塞）。
- 父任务 ``run_feature_list_parse_start``：出模块外壳 → fan-out 逐模块子任务并发解析。
- 子任务 ``run_feature_list_parse_module``：解析单模块功能点，429 退回队列指数退避重试。
- 进度/部分结果落库（刷新页面可续看）并经 ``apush_project_event`` 实时推前端。
- ``acommit``：草稿 → 正式 ``Artifact``（走 ``FeatureListService.aset_feature_list``）后删除草稿。

进度权重：模块阶段（出模块外壳）占 ``W_MODULES=20``；逐功能点阶段占 ``W_FEATURES=80``，
按已完成模块数线性累加。观测：``component=initiatives.feature_list_draft``。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from common.logging import redact_secrets_in_text
from initiatives.models import (
    FeatureListDraft,
    FeatureListDraftPhase,
    FeatureListDraftStatus,
)
from initiatives.services.realtime import apush_project_event

logger = structlog.get_logger(__name__)

_COMPONENT = "initiatives.feature_list_draft"
_EVENT = "feature_list_draft"

# 进度权重（按经验：出模块外壳 20%，逐模块填功能点 80%）。
W_MODULES = 20
W_FEATURES = 80


def _compute_progress(mods: list[dict[str, Any]], *, outline_done: bool) -> tuple[int, str, str]:
    """由模块解析状态推算 ``(progress, status, phase)``（纯函数）。"""
    total = len(mods)
    if not outline_done or total == 0:
        return 5, FeatureListDraftStatus.PARSING, FeatureListDraftPhase.MODULES
    done = sum(1 for m in mods if m.get("parse_state") in ("done", "failed"))
    ratio = done / total if total else 0
    progress = round(W_MODULES + W_FEATURES * ratio)
    if done >= total:
        any_ok = any(m.get("parse_state") == "done" for m in mods)
        status = FeatureListDraftStatus.READY if any_ok else FeatureListDraftStatus.FAILED
        return 100, status, FeatureListDraftPhase.DONE
    if done > 0:
        return progress, FeatureListDraftStatus.PARTIAL, FeatureListDraftPhase.FEATURES
    return progress, FeatureListDraftStatus.PARSING, FeatureListDraftPhase.FEATURES


def slice_module_text(source_text: str, line_start: Any, line_end: Any) -> str:
    """按 [line_start, line_end]（1-based，含端点）从原文切出单模块正文切片。"""
    lines = (source_text or "").split("\n")
    try:
        s = max(0, int(line_start) - 1)
        e = int(line_end)
    except (TypeError, ValueError):
        s, e = 0, len(lines)
    return "\n".join(lines[s:e])


class FeatureListDraftService:
    """feature list 解析草稿的唯一状态入口（含后台任务回写与前端推送）。"""

    # ── 读取 / 序列化 ────────────────────────────────────────────────

    @staticmethod
    def serialize(draft: FeatureListDraft | None) -> dict[str, Any]:
        """把草稿序列化为前端契约 dict（无草稿返回 idle 空态）。"""
        if draft is None:
            return {
                "has_draft": False,
                "status": FeatureListDraftStatus.IDLE,
                "phase": FeatureListDraftPhase.IDLE,
                "progress": 0,
                "modules": [],
                "error": "",
            }
        mods = (draft.tree or {}).get("modules", []) if isinstance(draft.tree, dict) else []
        return {
            "has_draft": True,
            "status": draft.status,
            "phase": draft.phase,
            "progress": int(draft.progress or 0),
            "job_id": draft.job_id,
            "error": draft.error,
            "modules": mods,
            "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        }

    @sync_to_async
    def _aget(self, project_id: Any) -> FeatureListDraft | None:
        return FeatureListDraft.objects.filter(project_id=project_id).first()

    @sync_to_async
    def _aget_by_id(self, draft_id: Any) -> FeatureListDraft | None:
        return FeatureListDraft.objects.filter(id=draft_id).first()

    async def aget_serialized(self, project_id: Any) -> dict[str, Any]:
        return self.serialize(await self._aget(project_id))

    async def aget_by_id(self, draft_id: Any) -> FeatureListDraft | None:
        return await self._aget_by_id(draft_id)

    # ── 推送 ─────────────────────────────────────────────────────────

    async def _apush(self, project_id: Any, snapshot: dict[str, Any]) -> None:
        """best-effort 推送草稿进度快照（失败不反噬）。"""
        await apush_project_event(project_id, _EVENT, snapshot)

    # ── 发起解析 ─────────────────────────────────────────────────────

    @sync_to_async
    def _areset_for_parse(
        self, project_id: Any, text: str, actor_id: Any
    ) -> FeatureListDraft:
        draft, _ = FeatureListDraft.objects.update_or_create(
            project_id=project_id,
            defaults={
                "status": FeatureListDraftStatus.PARSING,
                "phase": FeatureListDraftPhase.MODULES,
                "progress": 5,
                "source_text": text,
                "tree": {},
                "error": "",
                "job_id": "",
                "updated_by_id": actor_id,
            },
        )
        return draft

    @sync_to_async
    def _aset_job_id(self, draft_id: Any, job_id: str) -> None:
        FeatureListDraft.objects.filter(id=draft_id).update(job_id=job_id)

    async def astart_parse(
        self, project_id: Any, text: str, *, actor_id: Any = None
    ) -> dict[str, Any]:
        """写草稿并 defer 父任务；立即返回草稿快照（不阻塞请求）。"""
        from durable.queues import QUEUE_FEATURE_PARSE
        from durable.service import DurableTaskService

        draft = await self._areset_for_parse(project_id, text, actor_id)
        snapshot = self.serialize(draft)
        await self._apush(project_id, snapshot)
        job_id = await DurableTaskService.defer(
            "feature_list_parse_start",
            {"project_id": str(project_id), "draft_id": str(draft.id)},
            queue=QUEUE_FEATURE_PARSE,
            idempotency_key=f"featparse-start:{draft.id}",
            initiated_by_user_id=str(actor_id) if actor_id else None,
        )
        await self._aset_job_id(draft.id, job_id)
        logger.info(
            "feature_list_draft_parse_started",
            project_id=str(project_id),
            draft_id=str(draft.id),
            job_id=job_id,
            doc_chars=len(text or ""),
            component=_COMPONENT,
            category="caller",
        )
        snapshot["job_id"] = job_id
        return snapshot

    # ── 后台任务回写 ─────────────────────────────────────────────────

    @sync_to_async
    def _aset_outline(
        self, draft_id: Any, outline: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], int, Any] | None:
        """把 Step0 模块外壳写入草稿（parse_state=pending），返回 (snapshot, count, project_id)。"""
        with transaction.atomic():
            draft = FeatureListDraft.objects.select_for_update().filter(id=draft_id).first()
            if draft is None:
                return None
            mods = [
                {
                    "module": str(o.get("module") or "未分组"),
                    "summary": "",
                    "line_start": int(o.get("line_start") or 1),
                    "line_end": int(o.get("line_end") or 1),
                    "parse_state": "pending",
                    "features": [],
                }
                for o in outline
            ]
            progress, status, phase = _compute_progress(mods, outline_done=True)
            draft.tree = {"modules": mods}
            draft.progress = progress
            draft.status = status
            draft.phase = phase
            draft.save(update_fields=["tree", "progress", "status", "phase", "updated_at"])
            return self.serialize(draft), len(mods), draft.project_id

    async def aset_outline(
        self, draft_id: Any, outline: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], int] | None:
        result = await self._aset_outline(draft_id, outline)
        if result is None:
            return None
        snapshot, count, project_id = result
        await self._apush(project_id, snapshot)
        return snapshot, count

    @sync_to_async
    def _aset_module_state(
        self, draft_id: Any, index: int, state: str
    ) -> tuple[dict[str, Any], Any] | None:
        with transaction.atomic():
            draft = FeatureListDraft.objects.select_for_update().filter(id=draft_id).first()
            if draft is None:
                return None
            mods = (draft.tree or {}).get("modules", [])
            if not (0 <= index < len(mods)):
                return self.serialize(draft), draft.project_id
            mods[index]["parse_state"] = state
            draft.tree = {"modules": mods}
            draft.save(update_fields=["tree", "updated_at"])
            return self.serialize(draft), draft.project_id

    async def aset_module_running(self, draft_id: Any, index: int) -> None:
        result = await self._aset_module_state(draft_id, index, "running")
        if result is not None:
            snapshot, project_id = result
            await self._apush(project_id, snapshot)

    async def aset_module_pending(self, draft_id: Any, index: int) -> None:
        """429 退回队列时把模块状态复位为 pending（等待重试）。"""
        result = await self._aset_module_state(draft_id, index, "pending")
        if result is not None:
            snapshot, project_id = result
            await self._apush(project_id, snapshot)

    @sync_to_async
    def _awrite_module(
        self,
        draft_id: Any,
        index: int,
        *,
        features: list[dict[str, Any]] | None,
        failed: bool,
    ) -> tuple[dict[str, Any], Any] | None:
        with transaction.atomic():
            draft = FeatureListDraft.objects.select_for_update().filter(id=draft_id).first()
            if draft is None:
                return None
            mods = (draft.tree or {}).get("modules", [])
            if 0 <= index < len(mods):
                if failed:
                    mods[index]["parse_state"] = "failed"
                else:
                    mods[index]["features"] = features or []
                    mods[index]["parse_state"] = "done"
            progress, status, phase = _compute_progress(mods, outline_done=True)
            draft.tree = {"modules": mods}
            draft.progress = progress
            draft.status = status
            draft.phase = phase
            draft.save(update_fields=["tree", "progress", "status", "phase", "updated_at"])
            return self.serialize(draft), draft.project_id

    async def awrite_module(
        self,
        draft_id: Any,
        index: int,
        *,
        features: list[dict[str, Any]] | None = None,
        failed: bool = False,
    ) -> dict[str, Any] | None:
        result = await self._awrite_module(
            draft_id, index, features=features, failed=failed
        )
        if result is None:
            return None
        snapshot, project_id = result
        await self._apush(project_id, snapshot)
        return snapshot

    @sync_to_async
    def _afail(self, draft_id: Any, reason: str) -> tuple[dict[str, Any], Any] | None:
        with transaction.atomic():
            draft = FeatureListDraft.objects.select_for_update().filter(id=draft_id).first()
            if draft is None:
                return None
            draft.status = FeatureListDraftStatus.FAILED
            draft.error = redact_secrets_in_text(str(reason))[:500]
            draft.save(update_fields=["status", "error", "updated_at"])
            return self.serialize(draft), draft.project_id

    async def afail(self, draft_id: Any, reason: str) -> None:
        result = await self._afail(draft_id, reason)
        if result is not None:
            snapshot, project_id = result
            await self._apush(project_id, snapshot)

    # ── 保存草稿（用户手工编辑） ──────────────────────────────────────

    @sync_to_async
    def _asave_manual(
        self, project_id: Any, modules: list[dict[str, Any]], actor_id: Any
    ) -> dict[str, Any]:
        from initiatives.services.feature_list_service import FeatureListService

        normalized = FeatureListService._normalize_manual_modules(modules or [])
        mods = [
            {
                "module": m.get("module") or "未分组",
                "summary": m.get("summary", ""),
                "parse_state": "done",
                "features": m.get("features", []),
            }
            for m in normalized
        ]
        draft, _ = FeatureListDraft.objects.update_or_create(
            project_id=project_id,
            defaults={
                "status": FeatureListDraftStatus.READY,
                "phase": FeatureListDraftPhase.DONE,
                "progress": 100,
                "tree": {"modules": mods},
                "error": "",
                "updated_by_id": actor_id,
            },
        )
        return self.serialize(draft)

    async def asave_manual(
        self, project_id: Any, modules: list[dict[str, Any]], *, actor_id: Any = None
    ) -> dict[str, Any]:
        snapshot = await self._asave_manual(project_id, modules, actor_id)
        await self._apush(project_id, snapshot)
        return snapshot

    # ── 确认提交（草稿 → 正式工件后删除草稿） ────────────────────────

    @sync_to_async
    def _aload_tree_modules(self, project_id: Any) -> list[dict[str, Any]] | None:
        draft = FeatureListDraft.objects.filter(project_id=project_id).first()
        if draft is None:
            return None
        return (draft.tree or {}).get("modules", [])

    @sync_to_async
    def _adelete(self, project_id: Any) -> None:
        FeatureListDraft.objects.filter(project_id=project_id).delete()

    async def acommit(
        self,
        project_id: Any,
        *,
        modules: list[dict[str, Any]] | None = None,
        actor: Any = None,
        actor_id: Any = None,
    ) -> None:
        """把草稿（或传入的 modules）落为正式 feature_list 工件，成功后删除草稿。"""
        from initiatives.services.feature_list_service import FeatureListService

        payload = modules
        if payload is None:
            payload = await self._aload_tree_modules(project_id)
        if not payload:
            raise ValueError("草稿为空，无可保存的功能点")
        await FeatureListService().aset_feature_list(
            project_id,
            mode="manual",
            modules=payload,
            actor=actor,
            initiated_by_user_id=actor_id,
        )
        await self._adelete(project_id)
        logger.info(
            "feature_list_draft_committed",
            project_id=str(project_id),
            module_count=len(payload),
            component=_COMPONENT,
            category="caller",
        )


feature_list_draft_service = FeatureListDraftService()

__all__ = [
    "FeatureListDraftService",
    "feature_list_draft_service",
    "slice_module_text",
    "W_MODULES",
    "W_FEATURES",
]
