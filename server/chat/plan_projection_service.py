"""编排方案版本 → chat ``CodingPlan`` 的投影（Phase 109 · SPINE-01）。

本模块是「编排产出直连执行流」的服务端半边：把 ``delivery.ArtifactVersion``
（§7 MergedPlan content）**幂等**投影成 chat ``CodingPlan``，让编排产物直接点亮
既有执行流四步（选目标仓 → 配置分支 → 确认编码 → 飞书导出）——那四步全部只以
``CodingPlan.id`` 为锚点（见 ``tests/test_spa_coding_chain_e2e.py`` 的不变量护栏）。

两层职责刻意分开：

- ``map_merged_plan_to_coding_plan``：**纯函数**（无 IO / ORM / LLM），只做字段搬运与
  枚举转换。半可信 LLM 产物（``ArtifactVersion.content``）恒不抛异常。
- ``PlanProjectionService.aproject``：写入口（唯一），负责 conversation 解析、幂等、
  观测埋点。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

if TYPE_CHECKING:
    from chat.models import CodingPlan, Conversation
    from delivery.models import ArtifactVersion

logger = structlog.get_logger(__name__)

__all__ = [
    "PlanProjectionError",
    "PlanProjectionService",
    "map_merged_plan_to_coding_plan",
]

# 来源方案版本不存在 / content 非法（fail-closed：无来源不投影）。端点映射为 404，
# 与「非 owner」共用同一措辞，阻断 artifact_version_id 枚举探测（T-109-03-02）。
ERROR_ARTIFACT_VERSION_NOT_FOUND = "artifact_version_not_found"
# 编排会话无 conversation（workflow / MCP 入口）——裁决 D-3：本 phase 投影只做 chat 入口。
ERROR_REQUIRES_CHAT_ENTRYPOINT = "projection_requires_chat_entrypoint"

# §7 ``execution_plan[].files[].action`` → chat ``CodingPlan.affected_files[].change_type``。
#
# 🔴 这张表是一个**静默失守点**的唯一防线：§7 用 ``action: create``，而 chat
# ``CodingPlan.affected_files`` 的 schema 是 ``{"file_path": str, "change_type": str}``
# 且取值为 ``add``。既有 ``agents/tools/coding_tools.py::_normalize_affected_files``
# 只做 ``path → file_path`` 的键改名、**不做**枚举映射；前端 ``TechPlanCard.vue``
# 又原样渲染 ``change_type``（109-UI-SPEC §B.4 明确裁定前端**不做**兼容映射，
# 以免掩盖后端缺陷）。⇒ 漏做本转换**不会崩、不会报错**，只会在界面上静默显示成
# ``create``。因此测试必须对三个已知取值逐条断言 ``file_path`` **与** ``change_type``
# 两个键（只断言 file_path 是本坑的典型警示信号）。
_ACTION_TO_CHANGE_TYPE: dict[str, str] = {
    "create": "add",
    "modify": "modify",
    "delete": "delete",
}

# 未知 / 缺失 action 的保守回退：修改语义最弱，不会把「改一行」误报成「新增文件」。
_DEFAULT_CHANGE_TYPE = "modify"


def map_merged_plan_to_coding_plan(content: Any) -> dict[str, Any]:
    """§7 MergedPlan content → chat ``CodingPlan`` 四个字段的纯映射。

    Args:
        content: 半可信 ``ArtifactVersion.content``（LLM 产物，字段可能缺失/类型错）。

    Returns:
        ``{"title", "tech_plan", "affected_files", "recommended_repository_ids"}``。
        ``title`` 不在此处截断——由调用方按 ``CodingPlan.title`` 的 max_length=200 截。

    映射口径：

    - ``tech_plan``：复用 ``render_merged_plan_markdown``（唯一渲染器，**禁止**在此
      新写第二个）。它产的是飞书 lark_md 方言（``•`` 字面项目符号而非 ``- ``），在
      前端 markdown-it（GFM）下显示为纯文本项目符号——109-UI-SPEC §Unresolved 第 7 条
      裁定**接受现状**：可读、语义不丢。若观感不可接受，处置方式是给该函数加
      ``flavor: 'lark_md' | 'gfm'`` 参数，**仍不 fork 渲染器**。
    - ``affected_files``：**全仓聚合**（遍历 ``execution_plan[]`` 所有 task 的
      ``files[]``，不按 repository 筛——与 ``mcp_tools.orchestration_delegate.
      map_canonical_to_coding_plan`` 的单仓版语义不同），按 ``(file_path, change_type)``
      去重并保序。
    - ``recommended_repository_ids``：按 task 出现顺序去重保序（保序即保
      ``release_order`` 意图）。

    半可信输入恒不抛：顶层非 dict、``execution_plan`` 非 list、``files`` 项非 dict、
    ``path`` 为空串等一律降级为空结构（防御性风格照抄
    ``map_canonical_to_coding_plan`` 的 ``isinstance`` 守卫）。
    """
    from services.process_runtime.render import render_merged_plan_markdown

    safe: dict[str, Any] = content if isinstance(content, dict) else {}

    raw_tasks = safe.get("execution_plan")
    tasks: list[Any] = raw_tasks if isinstance(raw_tasks, list) else []

    affected_files: list[dict[str, str]] = []
    seen_files: set[tuple[str, str]] = set()
    repository_ids: list[str] = []
    seen_repos: set[str] = set()

    for task in tasks:
        if not isinstance(task, dict):
            continue

        repository_id = str(task.get("repository_id") or "")
        if repository_id and repository_id not in seen_repos:
            seen_repos.add(repository_id)
            repository_ids.append(repository_id)

        raw_files = task.get("files")
        files: list[Any] = raw_files if isinstance(raw_files, list) else []
        for entry in files:
            if not isinstance(entry, dict):
                continue
            file_path = str(entry.get("path") or "")
            if not file_path:
                continue
            action = str(entry.get("action") or "")
            change_type = _ACTION_TO_CHANGE_TYPE.get(action, _DEFAULT_CHANGE_TYPE)
            key = (file_path, change_type)
            if key in seen_files:
                continue
            seen_files.add(key)
            affected_files.append({"file_path": file_path, "change_type": change_type})

    return {
        "title": str(safe.get("title") or ""),
        "tech_plan": render_merged_plan_markdown(safe),
        "affected_files": affected_files,
        "recommended_repository_ids": repository_ids,
    }


class PlanProjectionError(Exception):
    """投影失败，带**稳定机器码** ``code``。

    ``code`` 是端点响应体里的契约字段：前端按 ``code`` 分支，绝不按 ``detail`` 文案
    匹配（109-UI-SPEC 后端契约要求第 4 条）。取值见模块级
    ``ERROR_ARTIFACT_VERSION_NOT_FOUND`` / ``ERROR_REQUIRES_CHAT_ENTRYPOINT``。
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PlanProjectionService:
    """编排方案版本 → chat ``CodingPlan`` 的**唯一投影写入口**（幂等 + 追溯 + 观测）。

    无状态：不持有任何实例状态，方法间不共享缓存，可随处 ``PlanProjectionService()``。

    **幂等三件套**（缺一不可，109-RESEARCH §10.4）：
    ① DB 无条件唯一约束 ``uniq_codingplan_source_artifact_version``（迁移 0033 提供，
    刻意不带 ``condition=`` 以免在 MySQL 上被 ``_unique_supported()`` 静默跳过）；
    ② ``aget_or_create(source_artifact_version_id=...)``；
    ③ ``except IntegrityError`` 重新 ``aget``（并发下双方同时 miss，落败方靠这一支
    降级为幂等命中而不是把 500 抛给用户）。
    只有 ② 等于并发下产重复行；只有 ①② 等于并发下给用户 500。

    **追溯不去范式化**：``CodingPlan`` 上**不**另写 ``work_item`` —— 经
    ``source_artifact_version_id → ArtifactVersion.artifact → Artifact.work_item``
    两跳即可达需求（109-RESEARCH §7 追溯最小完备集）。而 ``CodingPlan → MergeRequest``
    这半段本 phase **不建 FK**，沿用既有 ``pr_url`` + ``(repository, source_branch)``
    弱对齐。
    """

    # ------------------------------------------------------------------
    # 来源解析（async ORM 纪律：*_id 标量 / afirst / values，绝不裸访问同步 lazy-FK）
    # ------------------------------------------------------------------

    async def _aload_artifact_version(self, artifact_version_id: Any) -> ArtifactVersion:
        """取来源方案版本；不存在 / content 非 dict → fail-closed 拒绝投影。"""
        from delivery.models import ArtifactVersion

        try:
            av = await ArtifactVersion.objects.filter(id=str(artifact_version_id)).afirst()
        except (DjangoValidationError, ValueError, TypeError):
            # 非法 UUID 字面量（端点侧已由 DRF UUIDField 挡住，此处是纵深）。
            av = None
        if av is None or not isinstance(av.content, dict):
            raise PlanProjectionError(
                "方案版本不存在或内容非法",
                code=ERROR_ARTIFACT_VERSION_NOT_FOUND,
            )
        return av

    async def _aresolve_conversation_of(self, av: ArtifactVersion) -> Conversation:
        """``ArtifactVersion`` → ``ConvergenceSession`` → ``Conversation``（只走 chat 入口）。

        **边界（裁决 D-3）**：本 phase 的投影**只支持 chat 入口**。三者任一为空/不存在
        （workflow / MCP 入口的编排会话 ``conversation_id`` 为空）一律抛
        ``PlanProjectionError(code="projection_requires_chat_entrypoint")``：

        - **不建合成会话**——会在用户会话列表里凭空多出对话；
        - **不按 repository 反查 space**——``ConvergenceSession`` 无 space FK，反查有歧义
          （109-RESEARCH Open Q1 建议限定范围规避）。

        覆盖其余入口是后续 plan 的事，不是这里悄悄猜一个 space。
        """
        from chat.models import Conversation
        from delivery.models import ConvergenceSession

        session_id = str(av.produced_by_session_id or "").strip()
        conversation_id: Any = None
        if session_id:
            try:
                row = (
                    await ConvergenceSession.objects.filter(id=session_id)
                    .values("conversation_id")
                    .afirst()
                )
            except (DjangoValidationError, ValueError, TypeError):
                # produced_by_session_id 是 CharField，历史数据可能不是 UUID 字面量。
                row = None
            conversation_id = (row or {}).get("conversation_id")

        conversation = None
        if conversation_id:
            conversation = await Conversation.objects.filter(id=str(conversation_id)).afirst()
        if conversation is None:
            raise PlanProjectionError(
                "该方案版本不是由对话发起的编排产出，无法投影为编码方案",
                code=ERROR_REQUIRES_CHAT_ENTRYPOINT,
            )
        return conversation

    async def aresolve_conversation(self, *, artifact_version_id: Any) -> Conversation:
        """只解析归属会话、**不写库** —— 供端点在投影前做前置 owner 校验。

        存在这个只读入口的理由：owner 校验若只放在投影之后，越权请求会先在他人会话下
        建出 ``CodingPlan`` 再被拒（垃圾对象 + 数据污染）。
        """
        av = await self._aload_artifact_version(artifact_version_id)
        return await self._aresolve_conversation_of(av)

    # ------------------------------------------------------------------
    # 投影（唯一写入口）
    # ------------------------------------------------------------------

    async def aproject(
        self,
        *,
        artifact_version_id: str,
        initiated_by_user_id: str = "system",
    ) -> tuple[CodingPlan, bool]:
        """把 ``ArtifactVersion`` 幂等投影成 ``CodingPlan``，返回 ``(plan, created)``。

        Args:
            artifact_version_id: 来源方案版本 id（兼作幂等键）。
            initiated_by_user_id: 触发用户 id（观测归因）；后台/系统调用记 ``"system"``。

        Raises:
            PlanProjectionError: ``code`` 为 ``artifact_version_not_found`` 或
                ``projection_requires_chat_entrypoint``。

        归属判定当前**不在** service 内：唯一调用方是投影端点，其视图有 owner gate
        （前置 + 复核两道）。109-05 让 chat ``@tool`` 成为第二个调用方时，本参数会改为
        必填的 ``actor_user_id`` 并把归属判定下移进来（机器码
        ``artifact_version_forbidden``），视图 gate 降为纵深 —— 因此**不要**把
        「归属由调用方保证」当作本 service 的长期契约。
        """
        from chat.models import CodingPlan, CodingPlanProvenance

        started = time.perf_counter()
        try:
            logger.info(
                "plan_projection_started",
                category="caller",
                component="chat",
                artifact_version_id=str(artifact_version_id),
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

        try:
            av = await self._aload_artifact_version(artifact_version_id)
            payload = map_merged_plan_to_coding_plan(av.content)
            conversation = await self._aresolve_conversation_of(av)

            source_key = str(av.id)
            try:
                plan, created = await CodingPlan.objects.aget_or_create(
                    source_artifact_version_id=source_key,
                    defaults={
                        # 已 await 到手的实例（禁止传 lazy FK）。
                        "conversation": conversation,
                        "title": payload["title"][:200],
                        "tech_plan": payload["tech_plan"],
                        "affected_files": payload["affected_files"],
                        "recommended_repository_ids": payload["recommended_repository_ids"],
                        "provenance": CodingPlanProvenance.ORCHESTRATED,
                    },
                )
            except IntegrityError:
                # 并发：双方同时 get miss，落败方的 INSERT 撞 uniq_codingplan_source_
                # artifact_version → 重新 aget 取胜者那一行（照抄 coding_session_service
                # 的 IntegrityError 降级模式），对调用方表现为幂等命中而非 500。
                plan = await CodingPlan.objects.aget(source_artifact_version_id=source_key)
                created = False
        except PlanProjectionError as exc:
            self._log_failed(
                started=started,
                artifact_version_id=artifact_version_id,
                reason=str(exc),
                code=exc.code,
            )
            raise
        except Exception as exc:  # noqa: BLE001 — 未预期异常同样留痕后再抛
            self._log_failed(
                started=started,
                artifact_version_id=artifact_version_id,
                reason=str(exc),
                code="unexpected_error",
            )
            raise

        if not created:
            try:
                logger.info(
                    "plan_projection_idempotent_hit",
                    category="caller",
                    component="chat",
                    artifact_version_id=str(av.id),
                    coding_plan_id=str(plan.id),
                )
            except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
                pass
        else:
            # aget_or_create 不像 aget_or_create_for_conversation 那样自带摄取调度，
            # 故新建分支显式调度一次（best-effort：摄取失败绝不让投影失败）。
            try:
                from knowledge import ingestion  # lazy import 防循环

                await ingestion.aschedule_ingestion(
                    ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_plan_created"),
                    # 后台摄取任务显式携带触发用户（无触发用户记 "system"）。
                    initiated_by_user_id=initiated_by_user_id,
                )
            except Exception:  # noqa: BLE001 — 知识库摄取 best-effort，不反噬投影
                pass

        try:
            logger.info(
                "plan_projection_completed",
                category="caller",
                component="chat",
                duration_ms=max(int((time.perf_counter() - started) * 1000), 0),
                artifact_version_id=str(av.id),
                coding_plan_id=str(plan.id),
                created=created,
                repo_count=len(payload["recommended_repository_ids"]),
                provenance=plan.provenance,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

        return plan, created

    @staticmethod
    def _log_failed(
        *,
        started: float,
        artifact_version_id: Any,
        reason: str,
        code: str,
    ) -> None:
        """失败留痕；``reason`` 来自异常文本 ⇒ 先脱敏再落日志（T-109-03-07）。"""
        try:
            from common.logging import redact_secrets_in_text

            logger.warning(
                "plan_projection_failed",
                category="caller",
                component="chat",
                duration_ms=max(int((time.perf_counter() - started) * 1000), 0),
                artifact_version_id=str(artifact_version_id),
                code=code,
                reason=redact_secrets_in_text(reason),
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass
