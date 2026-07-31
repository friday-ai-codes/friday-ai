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
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

if TYPE_CHECKING:
    from chat.models import CodingPlan, Conversation
    from delivery.models import ArtifactVersion

logger = structlog.get_logger(__name__)

__all__ = [
    "ERROR_ARTIFACT_VERSION_ALREADY_PROJECTED",
    "ERROR_ARTIFACT_VERSION_FORBIDDEN",
    "ERROR_ARTIFACT_VERSION_NOT_FOUND",
    "ERROR_REQUIRES_CHAT_ENTRYPOINT",
    "PlanProjectionError",
    "PlanProjectionService",
    "filter_valid_uuids",
    "map_merged_plan_to_coding_plan",
]


def filter_valid_uuids(values: object) -> list[str]:
    """半可信来源的 id 过筛：非 UUID 字面量直接丢，绝不带进 ORM 查询。

    109-REVIEW MN-03：``recommended_repository_ids`` 由
    ``map_merged_plan_to_coding_plan`` 从 ``execution_plan[].repository_id`` 聚合，那里
    只做 ``str(...)`` 不校验形状——「半可信输入恒不抛」的契约只保证**映射层**自己不抛，
    抛的是消费方。把这些值直接喂 ``filter(id__in=...)``，一个写歪的字面量就会抛
    ``ValidationError``。本函数是所有消费方共用的那道筛子（工具路径与投影端点各写一份
    必然漂移）。
    """
    out: list[str] = []
    for value in values if isinstance(values, (list, tuple)) else []:
        try:
            out.append(str(uuid.UUID(str(value))))
        except (ValueError, AttributeError, TypeError):
            continue
    return out


# 来源方案版本不存在 / content 非法（fail-closed：无来源不投影）。端点映射为 404，
# 与「非 owner」共用同一措辞，阻断 artifact_version_id 枚举探测（T-109-03-02）。
ERROR_ARTIFACT_VERSION_NOT_FOUND = "artifact_version_not_found"
# 编排会话无 conversation（workflow / MCP 入口）——裁决 D-3：本 phase 投影只做 chat 入口。
ERROR_REQUIRES_CHAT_ENTRYPOINT = "projection_requires_chat_entrypoint"
# 归属不匹配：来源方案版本（或被 re-bind 的 plan）不属于 actor 的会话。措辞与
# 「不存在」一致、端点同样映射 404，不泄漏存在性（T-109-05-04 / T-109-05-07）。
ERROR_ARTIFACT_VERSION_FORBIDDEN = "artifact_version_forbidden"
# re-bind 目标版本已被另一条 plan 占用 —— fail-closed，绝不静默改写他人投影。
ERROR_ARTIFACT_VERSION_ALREADY_PROJECTED = "artifact_version_already_projected"

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

    @staticmethod
    def _assert_owner(conversation: Conversation, actor_user_id: str) -> None:
        """归属判定 —— **必须在渲染 / 写入任何方案正文之前**调用。

        为什么判定必须在 service 内而不是各调用方：109-03 把 owner gate 放在视图里，
        `aproject` 自身不判归属；109-05 让 chat ``@tool`` 成为第二个调用方，它的既有
        校验只查存在性 ⇒ 判定留在调用方就意味着每个新调用方都要重新实现一遍，而工具
        路径已经漏了一次。

        为什么必须在渲染之前：``arebind`` 会把来源版本的 ``content`` 渲染成
        ``tech_plan`` 写进调用方自己的 plan —— 判定晚一步就等于**跨会话读取他人完整
        技术方案正文**（T-109-05-07）。

        措辞与「不存在」一致，不泄漏存在性。
        """
        actor = str(actor_user_id or "").strip()
        if not actor or str(conversation.created_by_id or "") != actor:
            raise PlanProjectionError(
                "方案版本不存在或内容非法",
                code=ERROR_ARTIFACT_VERSION_FORBIDDEN,
            )

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
        actor_user_id: str,
    ) -> tuple[CodingPlan, bool]:
        """把 ``ArtifactVersion`` 幂等投影成 ``CodingPlan``，返回 ``(plan, created)``。

        Args:
            artifact_version_id: 来源方案版本 id（兼作幂等键）。
            actor_user_id: 归属主体 —— **必填、无默认值**。带默认值会让任何漏传的
                调用方静默获得 ``"system"`` 身份从而绕过归属判定，那正是 109-03 遗留
                blocker 的成因形状。无触发用户的系统调用方须**显式**传 ``"system"``。
                观测侧 kv 键名仍是 ``initiated_by_user_id``（取值来自本参数），以符合
                ``.cursor/rules/observability-logging.mdc``。

        Raises:
            PlanProjectionError: ``code`` 为 ``artifact_version_not_found`` /
                ``projection_requires_chat_entrypoint`` / ``artifact_version_forbidden``。

        归属判定在本 service 内（``_assert_owner``），工具路径与 HTTP 端点因此共享同
        一道门；视图侧的 owner gate 保留为纵深，不是替代。
        """
        from chat.models import CodingPlan, CodingPlanProvenance

        started = time.perf_counter()
        try:
            logger.info(
                "plan_projection_started",
                category="caller",
                component="chat",
                artifact_version_id=str(artifact_version_id),
                initiated_by_user_id=actor_user_id,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

        try:
            av = await self._aload_artifact_version(artifact_version_id)
            # 归属判定必须早于 map_merged_plan_to_coding_plan —— 后者会把他人方案
            # content 渲染成正文，判定晚一步即构成跨会话读取（T-109-05-07）。
            conversation = await self._aresolve_conversation_of(av)
            self._assert_owner(conversation, actor_user_id)
            payload = map_merged_plan_to_coding_plan(av.content)

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
                    initiated_by_user_id=actor_user_id,
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

    async def arebind(
        self,
        *,
        plan: CodingPlan,
        artifact_version_id: str,
        actor_user_id: str,
    ) -> CodingPlan:
        """把既有 ``CodingPlan`` 重新指向**另一个**编排方案版本（re-bind，不是任意改写）。

        SPINE-02 裁决 D-1：``update_coding_plan`` 收窄后不再接受方案正文，只能换来源。
        正文一律由 ``map_merged_plan_to_coding_plan`` 从来源版本渲染。

        Args:
            plan: 被重新指向的编码方案（调用方已解析出实例）。
            artifact_version_id: 新的来源方案版本 id。
            actor_user_id: 归属主体，**必填无默认值**（同 ``aproject``）。

        Raises:
            PlanProjectionError: ``artifact_version_not_found`` /
                ``projection_requires_chat_entrypoint`` / ``artifact_version_forbidden``
                / ``artifact_version_already_projected``。
        """
        from chat.models import CodingPlan, CodingPlanProvenance, Conversation

        started = time.perf_counter()
        try:
            logger.info(
                "plan_projection_started",
                category="caller",
                component="chat",
                artifact_version_id=str(artifact_version_id),
                coding_plan_id=str(plan.id),
                initiated_by_user_id=actor_user_id,
                rebind=True,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

        try:
            av = await self._aload_artifact_version(artifact_version_id)

            # ① 来源版本归属：必须早于渲染（跨会话读取他人正文的直接锁）。
            source_conversation = await self._aresolve_conversation_of(av)
            self._assert_owner(source_conversation, actor_user_id)

            # ② 被改写 plan 自身的归属：拿他人 plan 当写入目标同样以同一机器码拒绝。
            plan_conversation = await Conversation.objects.filter(id=plan.conversation_id).afirst()
            if plan_conversation is None:
                raise PlanProjectionError(
                    "方案版本不存在或内容非法",
                    code=ERROR_ARTIFACT_VERSION_FORBIDDEN,
                )
            self._assert_owner(plan_conversation, actor_user_id)

            # ③ 唯一约束前置查询。必须写成 async 形态：同步 ``.exists()`` / 直接对
            #    queryset 做布尔判定会在 async 上下文抛 SynchronousOnlyOperation。
            #    这一层不依赖后端能力 —— IntegrityError 兜底的前提是 DB 约束真的存在。
            if (
                await CodingPlan.objects.filter(source_artifact_version_id=str(av.id))
                .exclude(pk=plan.pk)
                .aexists()
            ):
                raise PlanProjectionError(
                    "该方案版本已被另一条编码方案占用",
                    code=ERROR_ARTIFACT_VERSION_ALREADY_PROJECTED,
                )

            payload = map_merged_plan_to_coding_plan(av.content)
            new_title = payload["title"][:200] or plan.title

            # 🔴 109-REVIEW MN-02：正文与来源指针必须一次写完，不得分裂。
            #
            # 原实现是两次独立写（`aupdate_plan` 先落新正文，再 `asave` 写来源指针），
            # 外面没有事务。后一次失败（唯一约束的并发窗口是设计上预期会发生的那种
            # 失败）会留下「正文=新版本 Y、source_artifact_version_id=旧版本 X」的混
            # 合态，而工具对用户报的是「什么都没变」——追溯链从此指向一个与正文无关的
            # 版本，不报错、只能靠人肉比对发现。
            #
            # 用 `.update()` 而非 `asave()`：单条 UPDATE 语句，会撞唯一约束的那一列
            # 与正文在同一次写里，不存在「正文已落、指针未落」的中间态。auto_now 不
            # 作用于 `.update()`，故显式带 `updated_at`。
            @sync_to_async
            def _rebind_atomic() -> None:
                with transaction.atomic():
                    CodingPlan.objects.filter(pk=plan.pk).update(
                        title=new_title,
                        recommended_repository_ids=payload["recommended_repository_ids"],
                        provenance=CodingPlanProvenance.ORCHESTRATED,
                        source_artifact_version_id=av.id,
                        tech_plan=payload["tech_plan"],
                        affected_files=payload["affected_files"],
                        updated_at=timezone.now(),
                    )

            try:
                await _rebind_atomic()
            except IntegrityError as exc:
                # 前置查询与写入之间的并发窗口 —— 抛同一机器码（fail-closed）。
                # 单事务保证：走到这里时 DB 里的正文与来源指针都还是改写前的旧值。
                raise PlanProjectionError(
                    "该方案版本已被另一条编码方案占用",
                    code=ERROR_ARTIFACT_VERSION_ALREADY_PROJECTED,
                ) from exc

            # 事务已提交，把新值同步回内存实例（调用方直接读 plan.tech_plan）。
            plan.title = new_title
            plan.recommended_repository_ids = payload["recommended_repository_ids"]
            plan.provenance = CodingPlanProvenance.ORCHESTRATED
            plan.source_artifact_version_id = av.id
            plan.tech_plan = payload["tech_plan"]
            plan.affected_files = payload["affected_files"]
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

        # 知识库重摄取移到事务之后（原先由 `aupdate_plan` 内联触发）：摄取是网络 IO，
        # 留在事务里会把事务时长绑到外部服务上；且它 best-effort —— 摄取失败绝不让
        # 已提交的 re-bind 变成失败。后台任务显式携带触发用户（无则 "system"）。
        try:
            from knowledge import ingestion  # lazy import 防循环

            await ingestion.aschedule_ingestion(
                ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_plan_updated"),
                initiated_by_user_id=actor_user_id,
            )
        except Exception:  # noqa: BLE001 — 知识库摄取 best-effort，不反噬 re-bind
            pass

        try:
            logger.info(
                "plan_projection_completed",
                category="caller",
                component="chat",
                duration_ms=max(int((time.perf_counter() - started) * 1000), 0),
                artifact_version_id=str(av.id),
                coding_plan_id=str(plan.id),
                created=False,
                rebound=True,
                repo_count=len(payload["recommended_repository_ids"]),
                provenance=plan.provenance,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

        return plan

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
