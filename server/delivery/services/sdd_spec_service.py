"""SddSpecService —— SddSpec 的唯一写入入口（D-49-3，INV-6）。

所有 ``SddSpec`` 落库只经本 service（旁路写表由 test_sdd_spec_inv6_guard grep 守护）。
本 phase 仅实现 ``create_draft``：经 ``DocumentService.create_internal_spec`` 落 spec 正文
``Document(sdd_spec)``，再幂等建/取 ``SddSpec(status=draft)`` 并连
document/work_item/plan_version/repository。

**状态流转 / 评审写入方法归 Phase 50，本 phase 不实现。**

幂等（D-49-3，兼顾不留孤儿 Document）：先按 ``(plan_version_id, repository)`` 短路探测既有
SddSpec，命中即直接返回——不调 create_internal_spec → 不新增 Document/DocumentVersion
（满足「重产不重复建、同内容不翻版本」）。未命中才落 Document 再
``get_or_create``——``unique_together(plan_version, repository)`` DB 约束 + get_or_create
兜底极小概率并发竞态（竞态下落单的孤儿 Document 视为 best-effort 可接受）。

async 安全：用 ``plan_version_id`` 标量 + ``repository`` / ``work_item`` 实例，不裸访问
lazy-FK。DocumentService 同 delivery app，顶部 import 无环。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from delivery.models import SddSpec, SddSpecStatus
from delivery.services.document_service import DocumentService

logger = structlog.get_logger(__name__)

__all__ = ["SddSpecService"]


class SddSpecService:
    """SddSpec 唯一写入入口（INV-6）。本 phase 仅 create_draft。"""

    async def create_draft(
        self,
        *,
        plan_version_id: Any,
        repository: Any,
        work_item: Any,
        content: str,
        change_kind: str = "proposal",
    ) -> SddSpec:
        """幂等建/取 ``SddSpec(status=draft)``，先落 spec 正文 Document（INV-6）。

        Args:
            plan_version_id: 来源 PlanVersion.id 标量（幂等键之一）。
            repository: 被产 spec 的 SDD 仓 Repository 实例（幂等键之一）。
            work_item: 关联交付脊柱实例；None=chat 自然语言需求（INV-2）。
            content: spec 正文 markdown（来自 LLM 合成产物）。
            change_kind: SddSpecChangeKind 值（proposal/delta），默认 proposal。

        Returns:
            既有或新建的 SddSpec 实例。
        """
        # 1. 幂等短路：命中既有 SddSpec 即返回（不调 create_internal_spec → 不留孤儿/不翻版本）
        existing = await SddSpec.objects.filter(
            plan_version_id=plan_version_id, repository=repository
        ).afirst()
        if existing is not None:
            logger.info(
                "sdd_spec_draft_idempotent_hit",
                plan_version_id=str(plan_version_id),
                repository_id=str(repository.id),
                spec_id=str(existing.id),
            )
            return existing

        # 2. 未命中：先落 spec 正文 Document（DocumentService 收口，INV-6）
        document = await DocumentService().create_internal_spec(
            work_item=work_item,
            repository_label=repository.name,
            content=content,
        )

        # 3. get_or_create 兜底并发竞态（unique_together DB 约束串行化）
        return await self._create_locked(
            plan_version_id=plan_version_id,
            repository=repository,
            work_item=work_item,
            document=document,
            change_kind=change_kind,
        )

    @sync_to_async
    def _create_locked(
        self,
        *,
        plan_version_id: Any,
        repository: Any,
        work_item: Any,
        document: Any,
        change_kind: str,
    ) -> SddSpec:
        """原子建/取 SddSpec（get_or_create 兜底 unique_together 竞态）。"""
        with transaction.atomic():
            spec, _created = SddSpec.objects.get_or_create(
                plan_version_id=plan_version_id,
                repository=repository,
                defaults={
                    "document": document,
                    "work_item": work_item,
                    "change_kind": change_kind,
                    "status": SddSpecStatus.DRAFT,
                },
            )
            return spec
