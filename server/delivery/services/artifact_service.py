"""ArtifactService —— 通用交付物的唯一写入入口（Chassis v2 · P1）。

泛化自 ``TechnicalPlanService``，把"建交付物 + 版本管理 + 内容去重"从方案专用
推广到任意 ``artifact_type``：

- ``create(artifact_type, content, ...)``：校验 content（按类型注册校验器）→ 建
  Artifact + 首版 v1 + 置 current_version。
- ``add_version(artifact, content, ...)``：content_hash 相等复用 current 不翻版本；
  不等建新版本 ``supersedes=current`` 并推进 ``current_version``。
- ``set_status`` / ``approve_version``：交付物 / 版本审批态流转。

``content_hash`` 为本地 ``sha256(canonical JSON sort_keys)``。写操作 ORM 经
``sync_to_async`` + ``transaction.atomic``。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from delivery.artifacts.registry import validate_content
from delivery.models import (
    Artifact,
    ArtifactApprovalStatus,
    ArtifactStatus,
    ArtifactVersion,
)

logger = structlog.get_logger(__name__)

__all__ = ["ArtifactContentInvalid", "ArtifactService"]


class ArtifactContentInvalid(ValueError):
    """content 未过 artifact_type 注册校验器。"""


def _content_hash(content: dict) -> str:
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _session_run_label(produced_by_session_id: str) -> str:
    """会话当前谱系标签（``stage_state["stage_rerun"]["run_label"]``），查不到回空串。

    节点重跑（quick 260806）把新谱系标签写在会话 ``stage_state`` 上；此后该会话产出的
    每个版本都属于这条谱系。**同步函数**：仅供 ``_create_sync`` / ``_add_version_sync``
    在写入事务内调用。整段吞异常——谱系标签是展示面，绝不因它废掉一次落版本。
    """
    session_id = str(produced_by_session_id or "").strip()
    if not session_id:
        return ""
    try:
        from delivery.models import ConvergenceSession

        stage_state = (
            ConvergenceSession.objects.filter(id=session_id)
            .values_list("stage_state", flat=True)
            .first()
        )
        marker = (stage_state or {}).get("stage_rerun") if isinstance(stage_state, dict) else None
        label = str((marker or {}).get("run_label") or "") if isinstance(marker, dict) else ""
        return label[:64]
    except Exception:  # noqa: BLE001 — 谱系标签 best-effort，绝不反噬落版本
        return ""


async def _amaybe_schedule_blueprint_ingestion(
    artifact_id: Any, content: Any, *, trigger: str, initiated_by_user_id: str = ""
) -> None:
    """content 是 ``blueprint/v1`` 时投递知识图谱摄取（Phase 116 VIEW-04）。

    ⛔ **不包 try**：``aschedule_ingestion`` 内部已吞异常（``knowledge/ingestion.py:118``），
    在这里重复兜底会掩盖「normalizer 注册漏行」这类**应当响亮**的错误。

    判别常量懒 import 自 schema 模块（MN-10：⛔ 不复制 ``"blueprint/v1"`` 字面量）；
    非蓝图 content（旧链 merge / echo / 其它 artifact_type）走这条判别是零影响的 no-op。

    ``initiated_by_user_id``（CTX-02，116-REVIEW MN-02）：后台任务**必须**显式携带发起
    用户，worker 入口据它 ``bind_task_context`` 重绑 ⇒ 图谱侧全链日志能回答「谁触发了这次
    入图」。取不到记 ``"system"``（⛔ 不留空串——那会让「系统行为」与「漏传」不可区分）。
    """
    from knowledge.ingestion import IngestionRequest, aschedule_ingestion
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

    if not isinstance(content, dict):
        return
    if content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        return
    await aschedule_ingestion(
        IngestionRequest("blueprint", str(artifact_id), trigger),
        initiated_by_user_id=str(initiated_by_user_id or "").strip() or "system",
    )


async def _ainitiator_of_session(produced_by_session_id: str) -> str:
    """反查会话的发起用户（116-REVIEW MN-02）；查不到 / 无会话一律回空串。

    ``add_version`` 拿不到 ``created_by_user_id``，但调用链上有 ``produced_by_session_id``
    —— 会话行上就记着 ``initiated_by_user_id``。⭐ 按标量 id 反查（⛔ 不裸访问 lazy-FK），
    整段吞异常：这是**观测归因**，⛔ 绝不因为查不到发起人就废掉一次入图。
    """
    session_id = str(produced_by_session_id or "").strip()
    if not session_id:
        return ""
    try:
        from delivery.models import ConvergenceSession

        return str(
            await ConvergenceSession.objects.filter(id=session_id)
            .values_list("initiated_by_user_id", flat=True)
            .afirst()
            or ""
        )
    except Exception:  # noqa: BLE001 — 归因 best-effort，绝不反噬入图主流程
        return ""


class ArtifactService:
    """通用交付物唯一写入入口。"""

    async def create(
        self,
        artifact_type: str,
        content: dict,
        *,
        title: str = "",
        work_item: Any = None,
        produced_by_session_id: str = "",
        produced_by_ref: str = "",
        created_by_user_id: str = "",
    ) -> Artifact:
        """建交付物：校验 content → 建 Artifact + 首版 v1 + 置 current_version。"""
        ok, err = validate_content(artifact_type, content)
        if not ok:
            raise ArtifactContentInvalid(f"{artifact_type} content 校验失败：{err}")
        artifact = await self._create_sync(
            artifact_type,
            content,
            title,
            work_item,
            produced_by_session_id,
            produced_by_ref,
            created_by_user_id,
        )
        logger.info(
            "artifact_created",
            category="caller",
            component="artifact_service",
            artifact_id=str(artifact.id),
            artifact_type=artifact_type,
        )
        # P-10：intake 建的 v1 骨架走本方法**不经 add_version** ⇒ 只在 add_version 挂门控的话
        # 「新建蓝图 → 立刻查图谱 → 空」会被当 bug 反复排查。两处对称挂同一条判别。
        await _amaybe_schedule_blueprint_ingestion(
            artifact.id,
            content,
            trigger="blueprint_version_created",
            # MN-02：本方法的形参里就有触发用户，⛔ 不传即整条图谱链归因到 system。
            initiated_by_user_id=created_by_user_id,
        )
        return artifact

    @sync_to_async
    def _create_sync(
        self,
        artifact_type: str,
        content: dict,
        title: str,
        work_item: Any,
        produced_by_session_id: str,
        produced_by_ref: str,
        created_by_user_id: str,
    ) -> Artifact:
        with transaction.atomic():
            artifact = Artifact.objects.create(
                artifact_type=artifact_type,
                title=title,
                work_item=work_item,
                status=ArtifactStatus.DRAFT,
                created_by_user_id=created_by_user_id or "",
            )
            v1 = ArtifactVersion.objects.create(
                artifact=artifact,
                version_no=1,
                content=content,
                content_hash=_content_hash(content),
                produced_by_session_id=produced_by_session_id or "",
                produced_by_ref=produced_by_ref or "",
                # 首版谱系恒 "1"（会话带重跑标记时随标记——理论上首版不会有）。
                version_label=_session_run_label(produced_by_session_id) or "1",
            )
            artifact.current_version = v1
            artifact.save(update_fields=["current_version", "updated_at"])
            return artifact

    async def add_version(
        self,
        artifact: Artifact,
        content: dict,
        *,
        produced_by_session_id: str = "",
        produced_by_ref: str = "",
    ) -> ArtifactVersion:
        """加版本：hash 相等复用 current 不翻版本；不等建 supersedes 链并推进 current。"""
        ok, err = validate_content(artifact.artifact_type, content)
        if not ok:
            raise ArtifactContentInvalid(f"{artifact.artifact_type} content 校验失败：{err}")
        # ⭐ 先记下调用前的 current 版本：``_add_version_sync`` 在 content_hash 相等时
        # ``return current``（版本没翻）⇒ 不比对就投递的话，每次无变化的重复写入都会白跑
        # 一次 normalizer + 一次后台任务。
        previous_version_id = artifact.current_version_id
        version = await self._add_version_sync(
            artifact, content, _content_hash(content), produced_by_session_id, produced_by_ref
        )
        if str(getattr(version, "id", "")) != str(previous_version_id or ""):
            await _amaybe_schedule_blueprint_ingestion(
                artifact.id,
                content,
                trigger="blueprint_version_created",
                # MN-02：本方法拿不到 created_by_user_id，经会话反查发起人（查不到记 system）。
                initiated_by_user_id=await _ainitiator_of_session(produced_by_session_id),
            )
        return version

    @sync_to_async
    def _add_version_sync(
        self,
        artifact: Artifact,
        content: dict,
        new_hash: str,
        produced_by_session_id: str,
        produced_by_ref: str,
    ) -> ArtifactVersion:
        with transaction.atomic():
            artifact.refresh_from_db(fields=["current_version"])
            current = artifact.current_version
            if current is not None and current.content_hash == new_hash:
                return current
            next_version = (current.version_no + 1) if current is not None else 1
            # 谱系标签（quick 260806）：会话带重跑标记 ⇒ 新版本属于重跑谱系；否则继承
            # 当前版本的谱系（人工编辑 / 驳回 bump 都留在同一条谱系上）。空串回落 "1"。
            label = _session_run_label(produced_by_session_id)
            if not label:
                label = str(getattr(current, "version_label", "") or "") or "1"
            new_version = ArtifactVersion.objects.create(
                artifact=artifact,
                version_no=next_version,
                supersedes=current,
                content=content,
                content_hash=new_hash,
                produced_by_session_id=produced_by_session_id or "",
                produced_by_ref=produced_by_ref or "",
                version_label=label,
            )
            artifact.current_version = new_version
            artifact.save(update_fields=["current_version", "updated_at"])
            return new_version

    async def set_status(self, artifact: Artifact, status: str) -> Artifact:
        """流转交付物状态。"""
        if status not in ArtifactStatus.values:
            raise ValueError(f"非法 artifact status={status!r}")
        return await self._set_status_sync(artifact, status)

    @sync_to_async
    def _set_status_sync(self, artifact: Artifact, status: str) -> Artifact:
        artifact.status = status
        artifact.save(update_fields=["status", "updated_at"])
        return artifact

    async def approve_version(self, version: ArtifactVersion, *, approved: bool) -> ArtifactVersion:
        """版本审批：置 approval_status，并联动交付物状态。"""
        return await self._approve_version_sync(version, approved)

    @sync_to_async
    def _approve_version_sync(self, version: ArtifactVersion, approved: bool) -> ArtifactVersion:
        with transaction.atomic():
            version.approval_status = (
                ArtifactApprovalStatus.APPROVED if approved else ArtifactApprovalStatus.REJECTED
            )
            version.save(update_fields=["approval_status"])
            artifact = version.artifact
            artifact.status = ArtifactStatus.APPROVED if approved else ArtifactStatus.UNDER_REVIEW
            artifact.save(update_fields=["status", "updated_at"])
            return version
