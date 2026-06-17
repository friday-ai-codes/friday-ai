"""SddSpecService —— SddSpec 的唯一写入入口（D-49-3，INV-6）。

所有 ``SddSpec`` 落库只经本 service（旁路写表由 test_sdd_spec_inv6_guard grep 守护）。
本 phase 仅实现 ``create_draft``：经 ``DocumentService.create_internal_spec`` 落 spec 正文
文档（sdd_spec 类型），再幂等建/取 ``SddSpec(status=draft)`` 并连
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
from django.utils import timezone

from delivery.models import ReviewDecision, SddSpec, SddSpecReview, SddSpecStatus
from delivery.services.document_service import DocumentService

logger = structlog.get_logger(__name__)

__all__ = ["SddSpecService", "SddSpecTransitionError"]


class SddSpecTransitionError(Exception):
    """spec 状态流转非法 / 竞态双推进 fail-loud（前端/API 转 400，D-50-1）。"""


class SddSpecService:
    """SddSpec 唯一写入入口（INV-6）：create_draft + 状态机流转（plan 50-02）。

    状态流转（D-50-1）经条件 ``.filter(status=from).update(status=to)`` + 影响行数判定：
    非法源状态 / 竞态双推进影响 0 行 → ``SddSpecTransitionError``（幂等 fail-loud，
    复用 RepoCodingTaskService 范式）。``approve`` / ``reject`` 在单一 ``transaction.atomic``
    内建 ``SddSpecReview`` + 驱动状态——更新 0 行回滚评审（不留孤儿，T-50-04）。
    本 service 是 ``SddSpecReview`` 唯一写入点（INV-6）。
    """

    # 简单流转合法表（archive 特殊处理：任意非 archived → archived）。
    _LEGAL_TRANSITIONS: dict[str, tuple[str, str]] = {
        "submit_for_review": (SddSpecStatus.DRAFT, SddSpecStatus.IN_REVIEW),
        "mark_implemented": (SddSpecStatus.APPROVED, SddSpecStatus.IMPLEMENTED),
    }

    # ---- 状态机流转（D-50-1） ----

    async def submit_for_review(self, spec_id: Any) -> None:
        """draft → in_review（任意认证用户，权限分流在 API 层 D-50-3）。"""
        await self._simple_transition(spec_id, "submit_for_review")

    async def mark_implemented(self, spec_id: Any) -> None:
        """approved → implemented（手动入口；Phase 51/52 编码/PR 触发）。"""
        await self._simple_transition(spec_id, "mark_implemented")

    async def approve(self, spec_id: Any, reviewer: Any, comment: str = "") -> None:
        """in_review → approved，单一事务原子建 approve 评审 + 驱动状态。"""
        await self._review_transition(
            spec_id,
            reviewer=reviewer,
            decision=ReviewDecision.APPROVE,
            comment=comment,
            from_status=SddSpecStatus.IN_REVIEW,
            to_status=SddSpecStatus.APPROVED,
            action="approve",
        )

    async def reject(self, spec_id: Any, reviewer: Any, comment: str) -> None:
        """in_review → draft（退回修订），单一事务原子建 reject 评审 + 驱动状态。"""
        await self._review_transition(
            spec_id,
            reviewer=reviewer,
            decision=ReviewDecision.REJECT,
            comment=comment,
            from_status=SddSpecStatus.IN_REVIEW,
            to_status=SddSpecStatus.DRAFT,
            action="reject",
        )

    async def archive(self, spec_id: Any) -> None:
        """任意非 archived → archived（手动归档，终态）。"""
        await self._archive(spec_id)

    @staticmethod
    def _raise_transition_error(spec_id: Any, action: str, expected: str) -> None:
        """0 行更新时读当前状态拼 fail-loud 消息（含 action + 当前状态，sync 上下文）。"""
        current = (
            SddSpec.objects.filter(id=spec_id).values_list("status", flat=True).first()
        )
        raise SddSpecTransitionError(
            f"非法流转：action={action}，期望源状态={expected}，当前状态={current}（spec={spec_id}）"
        )

    @sync_to_async
    def _simple_transition(self, spec_id: Any, action: str) -> None:
        from_status, to_status = self._LEGAL_TRANSITIONS[action]
        updated = SddSpec.objects.filter(id=spec_id, status=from_status).update(
            status=to_status, updated_at=timezone.now()
        )
        if updated == 0:
            self._raise_transition_error(spec_id, action, from_status)

    @sync_to_async
    def _archive(self, spec_id: Any) -> None:
        updated = (
            SddSpec.objects.filter(id=spec_id)
            .exclude(status=SddSpecStatus.ARCHIVED)
            .update(status=SddSpecStatus.ARCHIVED, updated_at=timezone.now())
        )
        if updated == 0:
            self._raise_transition_error(spec_id, "archive", "非 archived")

    @sync_to_async
    def _review_transition(
        self,
        spec_id: Any,
        *,
        reviewer: Any,
        decision: str,
        comment: str,
        from_status: str,
        to_status: str,
        action: str,
    ) -> None:
        # 单一事务：先建评审，再条件更新；更新 0 行 raise → 回滚评审（无孤儿，T-50-04）。
        with transaction.atomic():
            SddSpecReview.objects.create(
                spec_id=spec_id,
                reviewer=reviewer,
                decision=decision,
                comment=comment,
            )
            updated = SddSpec.objects.filter(id=spec_id, status=from_status).update(
                status=to_status, updated_at=timezone.now()
            )
            if updated == 0:
                self._raise_transition_error(spec_id, action, from_status)

    # ---- spec→实现 PR 关联（Phase 52 D-52-2，LINK-01，INV-6） ----

    async def link_implementation_pr(
        self, *, plan_version_id: Any, repository_id: Any, pr_url: str
    ) -> None:
        """回填 spec→实现 PR 关联（spec→PR 唯一写入入口，INV-6，D-52-2）。

        按 ``(plan_version_id, repository_id)`` 命中 SddSpec：追加 PR ref（按 ``pr_url``
        去重幂等），且 spec 当前 ``approved`` → 经 ``mark_implemented`` 语义流转
        （approved→implemented）；非 approved → 仅记 PR ref 不强转状态（宽容 warning）。
        无 SddSpec（非 SDD 仓）→ no-op（零回归，D-52-5）。append + 状态流转在单一
        ``transaction.atomic`` 内（INV-6）。

        Args:
            plan_version_id: 来源 PlanVersion.id 标量（幂等键之一，async 安全用标量）。
            repository_id: 产 PR 的仓 Repository.id 标量（幂等键之一）。
            pr_url: 实现 PR/MR 链接（去重键）。
        """
        await self._link_implementation_pr(
            plan_version_id=plan_version_id,
            repository_id=repository_id,
            pr_url=pr_url,
        )

    @sync_to_async
    def _link_implementation_pr(
        self, *, plan_version_id: Any, repository_id: Any, pr_url: str
    ) -> None:
        # approved→implemented 复用 _LEGAL_TRANSITIONS 源/目标常量作单一真相（不重复硬编码）。
        from_status, to_status = self._LEGAL_TRANSITIONS["mark_implemented"]
        with transaction.atomic():
            spec = (
                SddSpec.objects.select_for_update()
                .filter(plan_version_id=plan_version_id, repository_id=repository_id)
                .first()
            )
            if spec is None:
                # 非 SDD 仓无 spec → no-op（无写入、无异常，零回归 D-52-5）。
                return

            prs = list(spec.implementation_prs or [])
            already_linked = any(p.get("pr_url") == pr_url for p in prs)
            if not already_linked:
                prs.append(
                    {
                        "pr_url": pr_url,
                        "repository_id": str(repository_id),
                        "linked_at": timezone.now().isoformat(),
                    }
                )
                spec.implementation_prs = prs
                spec.save(update_fields=["implementation_prs", "updated_at"])

            # 状态流转：仅 approved → implemented；非 approved 宽容不强转（记 warning）。
            if spec.status == from_status:
                SddSpec.objects.filter(id=spec.id, status=from_status).update(
                    status=to_status, updated_at=timezone.now()
                )
            elif not already_linked:
                logger.warning(
                    "sdd_spec_pr_link_non_approved",
                    plan_version_id=str(plan_version_id),
                    repository_id=str(repository_id),
                    pr_url=pr_url,
                    spec_id=str(spec.id),
                    status=spec.status,
                )

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
        """原子建/取 SddSpec（get_or_create 兜底 unique_together 竞态）。

        WR-01：并发竞态下 get_or_create 命中他者已建的 SddSpec 时，本次步骤 2 落的
        Document 不会被任何 SddSpec 引用 → 同事务内删除该孤儿（级联清 DocumentVersion），
        避免泄漏无引用的 sdd_spec Document。
        """
        with transaction.atomic():
            spec, created = SddSpec.objects.get_or_create(
                plan_version_id=plan_version_id,
                repository=repository,
                defaults={
                    "document": document,
                    "work_item": work_item,
                    "change_kind": change_kind,
                    "status": SddSpecStatus.DRAFT,
                },
            )
            if not created and document is not None and spec.document_id != document.id:
                from delivery.models import Document

                Document.objects.filter(id=document.id).delete()
            return spec
