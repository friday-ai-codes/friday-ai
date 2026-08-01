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
    canonical = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _amaybe_schedule_blueprint_ingestion(
    artifact_id: Any, content: Any, *, trigger: str
) -> None:
    """content 是 ``blueprint/v1`` 时投递知识图谱摄取（Phase 116 VIEW-04）。

    ⛔ **不包 try**：``aschedule_ingestion`` 内部已吞异常（``knowledge/ingestion.py:118``），
    在这里重复兜底会掩盖「normalizer 注册漏行」这类**应当响亮**的错误。

    判别常量懒 import 自 schema 模块（MN-10：⛔ 不复制 ``"blueprint/v1"`` 字面量）；
    非蓝图 content（旧链 merge / echo / 其它 artifact_type）走这条判别是零影响的 no-op。
    """
    from knowledge.ingestion import IngestionRequest, aschedule_ingestion
    from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

    if not isinstance(content, dict):
        return
    if content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION:
        return
    await aschedule_ingestion(IngestionRequest("blueprint", str(artifact_id), trigger))


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
            artifact.id, content, trigger="blueprint_version_created"
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
            raise ArtifactContentInvalid(
                f"{artifact.artifact_type} content 校验失败：{err}"
            )
        # ⭐ 先记下调用前的 current 版本：``_add_version_sync`` 在 content_hash 相等时
        # ``return current``（版本没翻）⇒ 不比对就投递的话，每次无变化的重复写入都会白跑
        # 一次 normalizer + 一次后台任务。
        previous_version_id = artifact.current_version_id
        version = await self._add_version_sync(
            artifact, content, _content_hash(content), produced_by_session_id, produced_by_ref
        )
        if str(getattr(version, "id", "")) != str(previous_version_id or ""):
            await _amaybe_schedule_blueprint_ingestion(
                artifact.id, content, trigger="blueprint_version_created"
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
            new_version = ArtifactVersion.objects.create(
                artifact=artifact,
                version_no=next_version,
                supersedes=current,
                content=content,
                content_hash=new_hash,
                produced_by_session_id=produced_by_session_id or "",
                produced_by_ref=produced_by_ref or "",
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

    async def approve_version(
        self, version: ArtifactVersion, *, approved: bool
    ) -> ArtifactVersion:
        """版本审批：置 approval_status，并联动交付物状态。"""
        return await self._approve_version_sync(version, approved)

    @sync_to_async
    def _approve_version_sync(
        self, version: ArtifactVersion, approved: bool
    ) -> ArtifactVersion:
        with transaction.atomic():
            version.approval_status = (
                ArtifactApprovalStatus.APPROVED
                if approved
                else ArtifactApprovalStatus.REJECTED
            )
            version.save(update_fields=["approval_status"])
            artifact = version.artifact
            artifact.status = (
                ArtifactStatus.APPROVED if approved else ArtifactStatus.UNDER_REVIEW
            )
            artifact.save(update_fields=["status", "updated_at"])
            return version
