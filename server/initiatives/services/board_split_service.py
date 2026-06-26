"""BoardSplitService —— feature list → 子看板编排收口（BOARD-01，87-03）。

把 87-02 的拆分提案落成真实子看板，是「看板拆分」的单一编排收口：工作流节点
（``BoardSplitNode``）与 AI 会话工具（``split_feature_list_to_boards``）两入口共用
本服务，绝不各自实现一套。

两段职责：

- :meth:`propose_split`：薄委托 :class:`FeatureListExtractor`（87-02），把多源 feature
  list（文件 / 飞书链接 / 粘贴）抽取为 ``{modules, features_flat, degraded, chunk_count}``。

- :meth:`create_boards`：逐 ``features_flat`` 建子看板（87-01 写 API）——
    1. ``create_work_item(name=feature名, description=feature原文)`` 拿飞书 work_item_id；
    2. ``add_work_item_relation(relation_type=1)`` 关联项目跟踪（始终尝试）；
    3. ``detect_relation_capability().parent_child`` 为真才挂父子，否则降级
       （``degraded_parent_child=True`` + 提示去配置中心，**绝不阻断建看板**）；
    4. ``WorkItemService.upsert`` 落本地 ``delivery.WorkItem``（INV-6），再经
       ``ProjectService.attach_work_item(provenance=board_derived)`` 落 ProjectWorkItemLink
       （INV-6：本服务不旁路写 link，一律经 ProjectService）。
  逐 feature **fail-soft**：单条建项失败入 ``failures`` 并 continue，不拖垮整体。

可观测（强制）：``board_split_proposed``（caller，+duration_ms / feature_count / degraded）、
``board_split_create_started`` / ``_completed`` / ``_failed``（caller，+duration_ms /
created_count / failed_count / degraded_parent_child）、``board_split_feature_failed``
（caller，仅记 reason 摘要，经 ``redact_secrets_in_text`` 脱敏，不回显 token/完整响应）。
观测 best-effort，绝不反噬主流程。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from initiatives.models import LinkProvenance
from initiatives.services.feature_list_extractor import FeatureListExtractor
from initiatives.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

__all__ = ["BoardSplitService"]

_COMPONENT = "board_split"

# [ASSUMED] A-REL：relation_type 取值——1=关联项目跟踪，2=父子关系。
# 真实取值由空间配置中心决定（detect_relation_capability 仅探测父子是否可用），
# 写关系端点未真机验证，deferred 记 87-UAT.md。
_RELATION_TYPE_PROJECT_TRACK = 1
_RELATION_TYPE_PARENT_CHILD = 2

_DEGRADED_HINT = (
    "父子关系类型未配置，已建看板未挂父子，请去飞书项目配置中心预配关系类型"
)


class BoardSplitService:
    """feature list → 子看板的单一编排收口（无状态，工作流节点 + AI 工具共用）。"""

    async def propose_split(
        self,
        *,
        space: Any,
        uploaded_text: str | None = None,
        feishu_url: str | None = None,
        pasted_text: str | None = None,
        extra_instruction: str | None = None,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """多源 feature list → 结构化拆分提案（薄委托 FeatureListExtractor）。

        Args:
            space: ``projects.models.Space`` 实例（解析飞书凭证 + 飞书源回拉）。
            uploaded_text: 上传文件正文（md）。
            feishu_url: 飞书文档链接/ID（回拉正文）。
            pasted_text: 粘贴文本。
            extra_instruction: 多轮重拆指令（87-04，用户在群卡片输入框补充的拆分要求）；
                透传给 ``extract_structure`` 影响 LLM 抽取，缺省 None 即首轮无附加指令。
            initiated_by_user_id: 触发用户 id（审计/可观测绑定；缺记 system）。

        Returns:
            ``{modules, features_flat, degraded, chunk_count}``（FeatureListExtractor 输出）。

        Raises:
            ValueError: 三源全空（FeatureListExtractor.normalize_sources 抛）。
        """
        started = perf_counter()
        extractor = FeatureListExtractor()
        raw_text = await extractor.normalize_sources(
            uploaded_text=uploaded_text,
            feishu_url=feishu_url,
            pasted_text=pasted_text,
            space=space,
        )
        proposal = await extractor.extract_structure(
            raw_text,
            space=space,
            extra_instruction=extra_instruction,
            initiated_by_user_id=initiated_by_user_id,
        )

        logger.info(
            "board_split_proposed",
            feature_count=len(proposal.get("features_flat", [])),
            module_count=len(proposal.get("modules", [])),
            degraded=bool(proposal.get("degraded")),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            initiated_by_user_id=str(initiated_by_user_id)
            if initiated_by_user_id is not None
            else "system",
            component=_COMPONENT,
            category="caller",
        )
        return proposal

    async def create_boards(
        self,
        *,
        space: Any,
        proposal: dict[str, Any],
        work_item_type: str = "story",
        parent_work_item_id: int | None = None,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """逐 feature 建子看板 + 关联项目跟踪 + 落 link + 父子降级（逐条 fail-soft）。

        Args:
            space: ``projects.models.Space`` 实例（飞书凭证 + project_key 来源）。
            proposal: :meth:`propose_split` 返回的拆分提案（读 ``features_flat``）。
            work_item_type: 子看板工作项类型（默认 story）。
            parent_work_item_id: 「项目跟踪」父工作项 id（关联项目跟踪 + 父子的 target）；
                缺省时尝试从关联 Project.feishu_board_id 解析（数值串）。
            actor / initiated_by_user_id: 审计/可观测归因（缺记 system）。

        Returns:
            ``{created: [...], failures: [...], degraded_parent_child: bool, hint: str|None,
            feature_count: int}``。
        """
        started = perf_counter()
        features: list[dict[str, Any]] = list(proposal.get("features_flat") or [])
        project_key = getattr(space, "feishu_project_key", "") or ""

        project = await self._aresolve_project(space)
        if parent_work_item_id is None and project is not None:
            parent_work_item_id = self._parse_parent_id(
                getattr(project, "feishu_board_id", "")
            )

        # 一次性探测关系能力位：父子缺失即整体降级（不挂父子，绝不阻断建看板）。
        capability = await self._adetect_capability(space, project_key, work_item_type)
        degraded_parent_child = not bool(capability.get("parent_child"))

        logger.info(
            "board_split_create_started",
            feature_count=len(features),
            work_item_type=work_item_type,
            has_parent=parent_work_item_id is not None,
            degraded_parent_child=degraded_parent_child,
            initiated_by_user_id=str(initiated_by_user_id)
            if initiated_by_user_id is not None
            else "system",
            component=_COMPONENT,
            category="caller",
        )

        created: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        from services.feishu import create_feishu_client_for_project

        try:
            client = create_feishu_client_for_project(space)
        except Exception as exc:  # noqa: BLE001 — 凭证缺失 fail-loud（无 client 无法建项）
            logger.error(
                "board_split_create_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                feature_count=len(features),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            raise

        for feature in features:
            name = str(feature.get("name") or "").strip()
            description = str(feature.get("description") or "")
            if not name:
                continue
            try:
                work_item_id = await client.create_work_item(
                    project_key,
                    work_item_type,
                    name=name,
                    description=description,
                )
            except Exception as exc:  # noqa: BLE001 — 单条建项失败 fail-soft，不拖垮整体
                reason = redact_secrets_in_text(str(exc))
                failures.append({"feature": name, "reason": reason})
                logger.warning(
                    "board_split_feature_failed",
                    feature=name,
                    reason=reason,
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )
                continue

            # ② 关联项目跟踪（relation_type=1）+ ③ 父子（能力位为真才挂）——
            # 关联失败仅 warning，绝不回滚已建看板（fail-soft）。
            await self._aattach_relations(
                client,
                project_key=project_key,
                work_item_type=work_item_type,
                work_item_id=work_item_id,
                parent_work_item_id=parent_work_item_id,
                parent_child_enabled=bool(capability.get("parent_child")),
            )

            # ④ 落本地 WorkItem（INV-6 经 WorkItemService）→ attach 落 link（INV-6 经 ProjectService）
            link_attached = await self._aupsert_and_attach(
                project=project,
                project_key=project_key,
                work_item_type=work_item_type,
                work_item_id=work_item_id,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )

            created.append(
                {
                    "feature": name,
                    "module": feature.get("module", ""),
                    "work_item_id": work_item_id,
                    "linked": link_attached,
                }
            )

        hint = _DEGRADED_HINT if degraded_parent_child else None

        logger.info(
            "board_split_create_completed",
            feature_count=len(features),
            created_count=len(created),
            failed_count=len(failures),
            degraded_parent_child=degraded_parent_child,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            initiated_by_user_id=str(initiated_by_user_id)
            if initiated_by_user_id is not None
            else "system",
            component=_COMPONENT,
            category="caller",
        )
        return {
            "created": created,
            "failures": failures,
            "degraded_parent_child": degraded_parent_child,
            "hint": hint,
            "feature_count": len(features),
        }

    # ------------------------------------------------------------------
    # 内部 helper
    # ------------------------------------------------------------------

    @sync_to_async
    def _aresolve_project(self, space: Any) -> Any:
        """解析 space 对应的 Project（优先 feishu_project_key 命中，否则首个）。"""
        from initiatives.models import Project

        qs = Project.objects.filter(space=space)
        project_key = getattr(space, "feishu_project_key", "") or ""
        if project_key:
            matched = qs.filter(feishu_project_key=project_key).first()
            if matched is not None:
                return matched
        return qs.first()

    async def _adetect_capability(
        self, space: Any, project_key: str, work_item_type: str
    ) -> dict[str, Any]:
        """探测父子/关联关系能力位（detect_relation_capability 已 fail-soft 绝不抛）。"""
        from services.feishu import create_feishu_client_for_project

        try:
            client = create_feishu_client_for_project(space)
            return await client.detect_relation_capability(project_key, work_item_type)
        except Exception as exc:  # noqa: BLE001 — 探测失败保守降级（父子不可用），不阻断
            logger.warning(
                "board_split_capability_probe_error",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )
            return {"parent_child": False, "project_track": True, "raw": None}

    async def _aattach_relations(
        self,
        client: Any,
        *,
        project_key: str,
        work_item_type: str,
        work_item_id: int,
        parent_work_item_id: int | None,
        parent_child_enabled: bool,
    ) -> None:
        """写关联项目跟踪（relation_type=1）+ 父子（能力位为真）；失败仅 warning（fail-soft）。"""
        if parent_work_item_id is None:
            logger.warning(
                "board_split_relation_skipped",
                work_item_id=work_item_id,
                reason="missing_parent_work_item_id",
                component=_COMPONENT,
                category="caller",
            )
            return

        # ② 关联项目跟踪始终尝试
        await self._asafe_relation(
            client,
            project_key=project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            relation_type=_RELATION_TYPE_PROJECT_TRACK,
            target_id=parent_work_item_id,
        )

        # ③ 父子仅在能力位为真时挂
        if parent_child_enabled:
            await self._asafe_relation(
                client,
                project_key=project_key,
                work_item_type=work_item_type,
                work_item_id=work_item_id,
                relation_type=_RELATION_TYPE_PARENT_CHILD,
                target_id=parent_work_item_id,
            )

    async def _asafe_relation(
        self,
        client: Any,
        *,
        project_key: str,
        work_item_type: str,
        work_item_id: int,
        relation_type: int,
        target_id: int,
    ) -> None:
        """单次写关系（包裹 fail-soft：失败仅 warning，绝不回滚已建看板）。"""
        try:
            await client.add_work_item_relation(
                project_key,
                work_item_type,
                work_item_id,
                relation_type=relation_type,
                target_id=target_id,
            )
        except Exception as exc:  # noqa: BLE001 — 关联失败不反噬建看板
            logger.warning(
                "board_split_relation_failed",
                work_item_id=work_item_id,
                relation_type=relation_type,
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

    async def _aupsert_and_attach(
        self,
        *,
        project: Any,
        project_key: str,
        work_item_type: str,
        work_item_id: int,
        actor: Any,
        initiated_by_user_id: Any,
    ) -> bool:
        """落本地 WorkItem（WorkItemService，INV-6）+ attach 落 link（ProjectService，INV-6）。

        无关联 Project 时仅 warning 跳过 attach（看板已建，不反噬）。返回是否落了 link。
        """
        from delivery.services.work_item_service import (
            WorkItemIdentity,
            WorkItemService,
        )

        try:
            work_item = await WorkItemService().upsert(
                WorkItemIdentity(
                    feishu_project_key=project_key,
                    work_item_type=work_item_type,
                    work_item_id=work_item_id,
                ),
                source=_COMPONENT,
                fetch=False,
            )
        except Exception as exc:  # noqa: BLE001 — 本地落库失败不反噬建看板（远端已建）
            logger.warning(
                "board_split_work_item_upsert_failed",
                work_item_id=work_item_id,
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return False

        if project is None:
            logger.warning(
                "board_split_attach_skipped",
                work_item_id=work_item_id,
                reason="no_project_for_space",
                component=_COMPONENT,
                category="caller",
            )
            return False

        try:
            await ProjectService().attach_work_item(
                project_id=project.id,
                work_item=work_item,
                provenance=LinkProvenance.BOARD_DERIVED,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 落 link 失败不反噬建看板
            logger.warning(
                "board_split_attach_failed",
                work_item_id=work_item_id,
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return False
        return True

    @staticmethod
    def _parse_parent_id(raw: Any) -> int | None:
        """解析父工作项 id（数值串 → int；非数值/空 → None）。"""
        if raw is None:
            return None
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None
