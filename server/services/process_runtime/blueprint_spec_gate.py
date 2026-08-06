"""BlueprintSpecGateAdapter —— 阶段 0 规格门（Phase 112-02，FLOW-01）。

契约四段：

- **谁调用**：只被 112-05 注册的 ``technical_blueprint.spec_gate`` stage handler 调用。
  本 adapter 只返回结果 dict，**stage 转移由 handler 的 ``StageOutcome`` 决定**（engine
  纯度：adapter 不写 session.status / current_stage）。
- **fail-closed**：打分不可得（LLM 无 model / 响应不可解析 / 内部异常）、蓝图内容校验
  失败，一律判「需澄清」而非放行。规格门是全链路唯一 fail-closed 点，放行例外**仅两条**
  且都必须在 ``ambiguity_report.capped`` + ``release_reason`` 留痕（T-112-06）：
  ``round_cap``（显式轮数上界）与 ``no_new_questions``（超阈值但打分可得、未满歧义、
  确实问不出新问题）。**打分不可得或满歧义（total ≥ 1.0）时一律不得按「无新问题」放行**
  ——兜底问题恒为同一条常量，指纹去重会把它整条吃掉，那不是「不歧义」。
- **INV-6**：澄清线程一律经 ``BlueprintLifecycleService``、蓝图新版本一律经
  ``ArtifactService.add_version``——本文件零 ORM 写（只读查询）。
- **澄清载体只用 BlueprintThread**（``kind=ai_clarification``、``blocking=True``）：
  112-CONTEXT 明令不新建澄清表，也不复用旧编排链 ``clarify_adapter`` 那套澄清轮模型
  （两者的 pending 判据与恢复语义都对不上蓝图线程）。

回路六步：pending 短路 → 轮数上界 → 已答结论拼装（不重复提问）→ 四维打分 →
超阈值开线程挂起 → 放行时规格锁定（requirement_spec + ambiguity_report + decision_log
一次性落新蓝图版本）。日志与事件 payload 只记标量与关联键，需求/澄清正文不进
（T-112-08）。
"""

from __future__ import annotations

import copy
import time
from typing import Any

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text
from delivery.models import (
    ArtifactVersion,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAuthorType,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactContentInvalid, ArtifactService, ConvergenceSessionService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from delivery.services.event_taxonomy import (
    EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED,
    EVENT_BLUEPRINT_SPEC_GATE_LOCKED,
    EVENT_BLUEPRINT_SPEC_GATE_SCORED,
)
from services.process_runtime.blueprint_ambiguity_score import (
    ASSUMPTIONS_TIERS,
    aload_spec_gate_config,
    ascore_ambiguity,
    is_ambiguous,
    normalize_ambiguity_scores,
    weighted_total,
)
from services.process_runtime.blueprint_intent_classify import (
    DEFAULT_INTENT,
    aclassify_intents,
)

logger = structlog.get_logger(__name__)

__all__ = ["BlueprintSpecGateAdapter", "STAGE_STATE_KEY"]

# session.stage_state 内本阶段的键（112-05 handler 与 blueprint_resume 共用）。
STAGE_STATE_KEY = "spec_gate"

# 重问上界（镜像 clarify_adapter 的 _MAX_CLARIFY_ROUNDS「达上界带现有信息放行」语义）：
# 挂死比放行更糟——超界时带 capped 留痕放行，人可在后续阶段继续澄清。
#
# ⭐ 116-06：该上界的**单一事实源**是配置键 ``spec_gate.config.max_rounds``
# （``blueprint_ambiguity_score.DEFAULT_SPEC_GATE_CONFIG["max_rounds"]`` 是它的兜底默认，
# 值 3 与改动前的模块级常量逐字相等）。本文件原先那个模块级常量**已删除**——保留它会与
# 配置形成两份可漂移的默认值，而 assumptions 档位正需要运行时调它。

# 合法 intent 集合（与 blueprint_schema 的必填枚举同源，只作 adapter 侧沿用值判断）。
_VALID_INTENTS = ("greenfield", "brownfield", "fix")

# 满歧义（四维全 1.0 的加权总分上界）。到达此值时**任何情况都不得**按「无新问题」放行——
# 唯一放行例外仍是显式轮数上界（配置键 `spec_gate.config.max_rounds`，留 capped=True 痕）。
_MAX_AMBIGUITY_TOTAL = 1.0

# assumptions 档位在 stage_state 里的落点（⭐ 放 `decomposition` 下：`_current_round` 读的是
# `stage_state["spec_gate"]["round"]`，两者不冲突；入口在建会话时就把档位写进 decomposition）。
_TIER_STATE_KEY = "assumptions_tier"

# 放行例外的留痕枚举（落 ambiguity_report.release_reason 与 spec_locked 事件）：
# 下游（114 AI 审查 / 115 呈现面）据此区分「这次放行走的是哪条例外」。
RELEASE_REASON_UNAMBIGUOUS = ""
RELEASE_REASON_ROUND_CAP = "round_cap"
RELEASE_REASON_NO_NEW_QUESTIONS = "no_new_questions"

# 打分不可得时退化的通用规格澄清题（fail-closed：宁可多问一句也不静默放行）。
_FALLBACK_QUESTION: dict[str, Any] = {
    "text": "自动歧义评估暂不可用。请补充：本次需求的目标（做成什么样算成功）、范围边界"
    "（明确不做什么）、关键约束（性能/兼容/依赖方）、验收标准中仍不明确的部分。",
    "options": [],
    "citations": [],
    "related_feature_points": [],
    "recommended": "",
}


def _fingerprint(text: Any) -> str:
    """问题指纹：去空白 + 小写。用于「同一问题不再重复问」的集合比对。"""
    return "".join(str(text or "").split()).lower()


class BlueprintSpecGateAdapter:
    """规格门 adapter（策略可注入，镜像 ClarifyAdapter 的依赖注入形）。"""

    def __init__(
        self,
        *,
        lifecycle: BlueprintLifecycleService | None = None,
        artifacts: ArtifactService | None = None,
        scorer: Any = None,
        classifier: Any = None,
        session_service: ConvergenceSessionService | None = None,
    ) -> None:
        self.lifecycle = lifecycle or BlueprintLifecycleService()
        self.artifacts = artifacts or ArtifactService()
        self.scorer = scorer or ascore_ambiguity
        self.classifier = classifier or aclassify_intents
        self.session_service = session_service or ConvergenceSessionService()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def run(self, session: Any) -> dict[str, Any]:
        """跑一轮规格门，返回形状恒定的结果 dict。

        Returns:
            ``{"event": "needs_clarification" | "spec_locked", "thread_id": str | None,
            "ambiguity": dict, "round": int, "stage_state": dict}``——``stage_state``
            是本阶段的增量（``{"spec_gate": {...}}``），由 handler 合并进 session。
        """
        started = time.monotonic()
        round_no = self._current_round(session)
        tier = self._assumptions_tier(session)

        version = await self._aload_current_version(session)
        if version is None:
            # 没有蓝图版本就既无从打分也无处挂线程：判需澄清（绝不当作「无歧义」放行）。
            logger.warning(
                "blueprint_spec_gate_no_artifact_version",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
            )
            return self._result(
                "needs_clarification",
                None,
                {"scorer_unavailable": True, "resolved_thread_ids": []},
                round_no,
            )

        artifact = version.artifact
        # ⭐ 打分与锁定基线取 artifact 的**最新**版本而非 session 钉住的那一版（镜像
        # 确认门 alock 的同款修复，见 blueprint_confirm_gate.py:546-549）：确认门锁定与
        # 澄清回灌（ai_review_reflow）都推进 artifact 的 current_version，而
        # session.current_artifact_version 只在显式 StageOutcome 里才更新——按钉住版本
        # 作基线，放行锁定会把确认门写入的 repo_associations 与回灌成果整体回滚
        # （实测：v3-v6 的 repo_associations=4 被 v7 清零，下游分仓无仓可派、融合全空、
        # AI 审查 blocker 死循环）。scorer 的仓库集上下文（_repo_research_context）同样
        # 依赖最新正文，故在 run() 入口统一换基线，不只修锁定路径。
        latest = await self._aload_latest_version(artifact.id)
        base = latest if latest is not None else version
        content = base.content if isinstance(base.content, dict) else {}

        # 1. pending 短路：已有 open+blocking 澄清线程 → 保持挂起，不再打分、不重复提问。
        if await self.lifecycle.ahas_open_blocking_threads(
            artifact, kind=ThreadKind.AI_CLARIFICATION
        ):
            logger.info(
                "blueprint_spec_gate_pending",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
                artifact_id=str(artifact.id),
                round=round_no,
            )
            return self._result(
                "needs_clarification", None, {"resolved_thread_ids": []}, round_no, pending=True
            )

        # 2. 已答结论拼装（「不重复提问」的核心）：已 answered/resolved 的澄清线程问答 +
        #    蓝图 decision_log 条目，既进重判 prompt，也给出问题指纹集合。
        prior = await self._collect_prior_answers(artifact, content)

        # ⭐ 配置读取**上提到轮数判定之前**（116-06）：轮数上界改读 `config["max_rounds"]`，
        # 而判定发生在原先那次读取之前 ⇒ 不上提就拿不到值。同一个 `config` 对象随后复用给
        # 阈值判定与 `_lock_spec`（⛔ 不再读第二次）。
        config = await aload_spec_gate_config(tier=tier)

        # 3. 轮数上界：达上界带现有信息放行并留痕，绝不无限挂起（镜像 clarify_adapter 兜底）。
        if round_no >= int(config["max_rounds"]):
            logger.warning(
                "blueprint_spec_gate_cap_reached",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
                artifact_id=str(artifact.id),
                round=round_no,
                assumptions_tier=tier,
                max_rounds=int(config["max_rounds"]),
            )
            return await self._lock_spec(
                session,
                artifact,
                content,
                scores=normalize_ambiguity_scores(None),
                prior=prior,
                round_no=round_no,
                capped=True,
                release_reason=RELEASE_REASON_ROUND_CAP,
                scorer_unavailable=False,
                config=config,
                tier=tier,
                started=started,
            )

        # 4. 四维打分；不可得即 fail-closed（保守全 1.0 + 一条通用规格澄清题）。
        # ⭐ `tier=` 必须传下去：scorer 体内**自己也读一次配置**并据它打 sampling 日志的
        # `threshold` / `above_threshold`，不传即「日志报的阈值 ≠ 判定用的阈值」（T-116-53）。
        # ⭐ 116 重排后规格门位于确认门之后：把已锁定的仓库集与调研结论（fitness）拼进
        # prior_context —— 澄清问题应带着调研证据问，而不是两眼一抹黑。
        # 节点重跑的操作员补充指令（quick 260806）：拼进打分 prior_context——重跑规格门时
        # 指令是「已知信息」，缺它会把用户刚说清楚的事再问一遍。无指令时零扰动。
        from services.process_runtime.blueprint_stage_rerun import operator_instruction_section

        prior_context = "\n".join(
            part
            for part in (
                prior["text"],
                self._repo_research_context(content),
                operator_instruction_section(session),
            )
            if part
        )
        scores = await self.scorer(
            goal=self._goal_text(content),
            feature_points=self._feature_points(content),
            constraints=self._constraints(content),
            prior_context=prior_context,
            session_id=str(session.id),
            tier=tier,
        )
        scorer_unavailable = not isinstance(scores, dict)
        if scorer_unavailable:
            scores = normalize_ambiguity_scores(None)
            scores["questions"] = [dict(_FALLBACK_QUESTION)]

        total = weighted_total(scores["dimensions"], config["weights"])
        above = is_ambiguous(total, config["threshold"])

        # 5. 超阈值 → 剔除已答过的同一问题，仍有问题则开阻塞线程挂起。
        release_reason = RELEASE_REASON_UNAMBIGUOUS
        if above:
            questions = [
                q
                for q in scores["questions"]
                if _fingerprint(q.get("text")) not in prior["fingerprints"]
            ]
            # 「超阈值 + 无新问题」不等于「不歧义」：打分不可得时兜底问题恒为同一条常量，
            # 指纹必然命中；满歧义时同理不能靠去重把门开了。两种情形一律重新挂起
            # （轮数由配置键 `spec_gate.config.max_rounds` 兜底，不会无限挂）。
            if not questions and (scorer_unavailable or total >= _MAX_AMBIGUITY_TOTAL):
                questions = [dict(q) for q in scores["questions"]] or [dict(_FALLBACK_QUESTION)]
                logger.warning(
                    "blueprint_spec_gate_reasked_without_new_questions",
                    category="caller",
                    component="process_runtime",
                    session_id=str(session.id),
                    artifact_id=str(artifact.id),
                    weighted_total=total,
                    scorer_unavailable=scorer_unavailable,
                    round=round_no,
                )
            if questions:
                return await self._open_clarification(
                    session,
                    artifact,
                    version,
                    scores=scores,
                    questions=questions,
                    config=config,
                    total=total,
                    round_no=round_no,
                    scorer_unavailable=scorer_unavailable,
                    tier=tier,
                    started=started,
                )
            # 打分可得、未满歧义、但确实问不出新问题 → 这是第二条放行例外，必须留痕。
            release_reason = RELEASE_REASON_NO_NEW_QUESTIONS
            logger.warning(
                "blueprint_spec_gate_released_without_new_questions",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
                artifact_id=str(artifact.id),
                weighted_total=total,
                threshold=config["threshold"],
                dropped_question_count=len(scores["questions"]),
            )

        # 6. 放行 → 规格锁定。
        return await self._lock_spec(
            session,
            artifact,
            content,
            scores=scores,
            prior=prior,
            round_no=round_no,
            capped=bool(release_reason),
            release_reason=release_reason,
            scorer_unavailable=scorer_unavailable,
            config=config,
            total=total,
            tier=tier,
            started=started,
        )

    # ------------------------------------------------------------------
    # 步骤实现
    # ------------------------------------------------------------------

    async def _open_clarification(
        self,
        session: Any,
        artifact: Any,
        version: Any,
        *,
        scores: dict[str, Any],
        questions: list[dict[str, Any]],
        config: dict[str, Any],
        total: float,
        round_no: int,
        scorer_unavailable: bool,
        tier: str = "",
        started: float,
    ) -> dict[str, Any]:
        """开一条带候选选项与证据引用的阻塞澄清线程并挂起。"""
        question_text = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(questions, start=1))
        thread = await self.lifecycle.open_thread(
            artifact,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            question=question_text,
            options=questions,
            initiated_by_user_id=self._initiated_by(session),
            created_on_version=version,
            return_stage=BlueprintStatus.RESEARCHING,
        )
        ambiguity = self._ambiguity_report(
            scores,
            config=config,
            total=total,
            resolved_thread_ids=[],
            capped=False,
            release_reason=RELEASE_REASON_UNAMBIGUOUS,
            scorer_unavailable=scorer_unavailable,
            tier=tier,
        )
        # ⭐ CLAR-04 的另一半：澄清同时推飞书卡片。**唯一接线点**（⛔ 不在四个入口各接一次），
        # 整段 best-effort 收敛在 blueprint_notify 内 ⇒ 发卡失败绝不反噬挂起。
        from services.process_runtime.blueprint_notify import anotify_blueprint_clarification

        await anotify_blueprint_clarification(
            artifact=artifact,
            session=session,
            questions=questions,
            initiated_by_user_id=self._initiated_by(session),
        )
        await self._emit(
            session,
            EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED,
            {
                "thread_id": str(thread.id),
                "question_count": len(questions),
                "weighted_total": total,
            },
        )
        logger.info(
            "blueprint_spec_gate_clarification_asked",
            category="caller",
            component="process_runtime",
            session_id=str(session.id),
            artifact_id=str(artifact.id),
            thread_id=str(thread.id),
            question_count=len(questions),
            weighted_total=total,
            threshold=config["threshold"],
            round=round_no + 1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return self._result("needs_clarification", str(thread.id), ambiguity, round_no + 1)

    async def _lock_spec(
        self,
        session: Any,
        artifact: Any,
        content: dict[str, Any],
        *,
        scores: dict[str, Any],
        prior: dict[str, Any],
        round_no: int,
        capped: bool,
        release_reason: str,
        scorer_unavailable: bool,
        config: dict[str, Any] | None = None,
        total: float | None = None,
        tier: str = "",
        started: float,
    ) -> dict[str, Any]:
        """规格锁定：intent 补齐 + ambiguity_report + decision_log 一次性落新蓝图版本。

        ``tier`` 只服务于 ``config is None`` 的兜底分支（调用方通常已把上提读到的
        ``config`` 一并传下来 ⇒ 那条分支不再触发）与 ``ambiguity_report`` 的留痕。
        """
        if config is None:
            config = await aload_spec_gate_config(tier=tier)
        if total is None:
            total = weighted_total(scores["dimensions"], config["weights"])

        locked = copy.deepcopy(content)
        spec = locked.get("requirement_spec")
        if not isinstance(spec, dict):
            spec = {}
            locked["requirement_spec"] = spec

        await self._apply_intents(spec, session_id=str(session.id))
        spec["ambiguity_report"] = self._ambiguity_report(
            scores,
            config=config,
            total=total,
            resolved_thread_ids=prior["resolved_thread_ids"],
            capped=capped,
            release_reason=release_reason,
            scorer_unavailable=scorer_unavailable,
            tier=tier,
        )
        decision_log = self._merge_decision_log(locked.get("decision_log"), prior["entries"])
        if decision_log:
            locked["decision_log"] = decision_log

        try:
            version = await self.artifacts.add_version(
                artifact,
                locked,
                produced_by_session_id=str(session.id),
                produced_by_ref="blueprint_spec_gate",
            )
        except ArtifactContentInvalid as exc:
            # 校验失败绝不上抛让 engine 落 failed——判需澄清（fail-closed）等人补规格。
            logger.warning(
                "blueprint_spec_gate_invalid_content",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
                artifact_id=str(artifact.id),
                error=redact_secrets_in_text(str(exc)),
            )
            return self._result(
                "needs_clarification",
                None,
                self._ambiguity_report(
                    scores,
                    config=config,
                    total=total,
                    resolved_thread_ids=prior["resolved_thread_ids"],
                    capped=capped,
                    release_reason=release_reason,
                    scorer_unavailable=scorer_unavailable,
                    tier=tier,
                ),
                round_no,
            )

        # 仍停在 answered 的线程在此收尾（结论已物化进 decision_log）。
        for thread in prior["answered_threads"]:
            await self.lifecycle.resolve_thread(
                thread, initiated_by_user_id=self._initiated_by(session)
            )

        await self._emit(
            session,
            EVENT_BLUEPRINT_SPEC_GATE_SCORED,
            {
                "weighted_total": total,
                "threshold": config["threshold"],
                "above_threshold": is_ambiguous(total, config["threshold"]),
                "capped": capped,
                "release_reason": release_reason,
                "scorer_unavailable": scorer_unavailable,
            },
        )
        await self._emit(
            session,
            EVENT_BLUEPRINT_SPEC_GATE_LOCKED,
            {
                "resolved_thread_count": len(prior["resolved_thread_ids"]),
                "decision_log_count": len(decision_log),
                "version_no": getattr(version, "version_no", 0),
                "capped": capped,
                "release_reason": release_reason,
            },
        )
        logger.info(
            "blueprint_spec_gate_locked",
            category="caller",
            component="process_runtime",
            session_id=str(session.id),
            artifact_id=str(artifact.id),
            weighted_total=total,
            threshold=config["threshold"],
            capped=capped,
            release_reason=release_reason,
            scorer_unavailable=scorer_unavailable,
            resolved_thread_count=len(prior["resolved_thread_ids"]),
            decision_log_count=len(decision_log),
            round=round_no,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        result = self._result("spec_locked", None, spec["ambiguity_report"], round_no)
        # ⭐ 用锁定后的规格刷新 stage_state 顶层的 requirement_spec 快照（decompose 首写）：
        # 下游 repo_plan / 调研容器的 prompt 经 `_requirement_spec_from_state` 读 stage_state，
        # 不刷新会让分仓方案拿到澄清前的旧规格。
        result["stage_state"]["requirement_spec"] = spec
        return result

    async def _apply_intents(self, spec: dict[str, Any], *, session_id: str) -> None:
        """给每个 feature_point 补 ``intent``：已有合法值 > 分类器 > 保守值 brownfield。

        保证 ``blueprint_schema`` 的必填枚举永不违约——分类器返回 ``None`` 或漏项时
        一律落 ``brownfield``，绝不写非法值、绝不留空。
        """
        points = spec.get("feature_points")
        if not isinstance(points, list):
            return
        pending = [
            p
            for p in points
            if isinstance(p, dict) and str(p.get("intent", "")).strip() not in _VALID_INTENTS
        ]
        classified: dict[str, str] = {}
        if pending:
            try:
                result = await self.classifier(feature_points=pending, session_id=session_id)
            except Exception as exc:  # noqa: BLE001 — 分类失败落保守值，绝不阻断锁定
                logger.warning(
                    "blueprint_spec_gate_intent_classify_failed",
                    category="caller",
                    component="process_runtime",
                    session_id=session_id,
                    error=redact_secrets_in_text(str(exc)),
                )
                result = None
            if isinstance(result, dict):
                classified = result
        for point in pending:
            candidate = str(classified.get(str(point.get("id", "")), "")).strip()
            point["intent"] = candidate if candidate in _VALID_INTENTS else DEFAULT_INTENT

    def _merge_decision_log(self, existing: Any, entries: list[dict[str, Any]]) -> list[Any]:
        """按 ``thread_id`` 去重追加决策快照（幂等重跑不重复堆积）。"""
        merged = list(existing) if isinstance(existing, list) else []
        seen = {
            str(item.get("thread_id"))
            for item in merged
            if isinstance(item, dict) and item.get("thread_id")
        }
        for entry in entries:
            if entry["thread_id"] in seen:
                continue
            seen.add(entry["thread_id"])
            merged.append(entry)
        return merged

    # ------------------------------------------------------------------
    # 只读装配 helper（adapter 零 ORM 写，INV-6）
    # ------------------------------------------------------------------

    async def _aload_current_version(self, session: Any) -> Any:
        """取会话当前蓝图版本（带 artifact，避免 async 裸 lazy-FK）。"""
        version_id = getattr(session, "current_artifact_version_id", None)
        if not version_id:
            return None
        return await (
            ArtifactVersion.objects.select_related("artifact").filter(id=version_id).afirst()
        )

    @staticmethod
    async def _aload_latest_version(artifact_id: Any) -> Any:
        """取 artifact 的最新版本（与确认门 `_aload_latest_version` 同款，作打分/锁定基线）。"""
        return await (
            ArtifactVersion.objects.filter(artifact_id=artifact_id).order_by("-version_no").afirst()
        )

    async def _collect_prior_answers(
        self, artifact: Any, content: dict[str, Any]
    ) -> dict[str, Any]:
        """汇总已答/已解决澄清线程与既有 decision_log。

        产出四件套：喂重判 prompt 的 ``text``、去重用的问题 ``fingerprints``、写进
        ``ambiguity_report`` 的 ``resolved_thread_ids``、待物化的 ``entries``，外加仍
        停在 answered 待收尾的线程实例。**只读**——线程写入一律经 lifecycle service。
        """
        rows = [
            row
            async for row in BlueprintThreadMessage.objects.filter(
                thread__artifact=artifact,
                thread__kind=ThreadKind.AI_CLARIFICATION,
                thread__status__in=[ThreadStatus.ANSWERED, ThreadStatus.RESOLVED],
            )
            .order_by("thread__created_at", "created_at")
            .values("thread_id", "author_type", "body", "author_id")
        ]
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            thread_id = str(row["thread_id"])
            bucket = grouped.setdefault(
                thread_id, {"question": "", "answers": [], "decided_by": "human"}
            )
            body = str(row.get("body") or "").strip()
            if not body:
                continue
            if row["author_type"] == ThreadAuthorType.AI:
                if not bucket["question"]:
                    bucket["question"] = body
            else:
                bucket["answers"].append(body)
                if row.get("author_id"):
                    bucket["decided_by"] = str(row["author_id"])

        decided_at = timezone.now().isoformat()
        entries: list[dict[str, Any]] = []
        lines: list[str] = []
        fingerprints: set[str] = set()
        for thread_id, bucket in grouped.items():
            answer = "；".join(bucket["answers"])
            if not answer:
                continue
            entries.append(
                {
                    "thread_id": thread_id,
                    "question": bucket["question"],
                    "answer": answer,
                    "decided_at": decided_at,
                    "decided_by": bucket["decided_by"],
                }
            )
            lines.append(f"- {bucket['question']}：{answer}")
            for line in str(bucket["question"]).splitlines():
                # 线程问题正文可能是多题合并的编号列表，逐行取指纹才能逐题去重。
                fingerprints.add(_fingerprint(self._strip_numbering(line)))

        for item in content.get("decision_log") or []:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question:
                continue
            for line in question.splitlines():
                fingerprints.add(_fingerprint(self._strip_numbering(line)))
            if answer:
                lines.append(f"- {question}：{answer}")

        fingerprints.discard("")
        answered_threads = [
            thread
            async for thread in BlueprintThread.objects.filter(
                artifact=artifact,
                kind=ThreadKind.AI_CLARIFICATION,
                status=ThreadStatus.ANSWERED,
            )
        ]
        return {
            "text": "\n".join(lines),
            "fingerprints": fingerprints,
            "resolved_thread_ids": sorted(grouped),
            "entries": entries,
            "answered_threads": answered_threads,
        }

    @staticmethod
    def _strip_numbering(line: str) -> str:
        """去掉合并提问时加的 ``N. `` 前缀，让指纹回到原始题面。"""
        stripped = line.strip()
        head, sep, tail = stripped.partition(". ")
        if sep and head.isdigit():
            return tail
        return stripped

    def _current_round(self, session: Any) -> int:
        state = getattr(session, "stage_state", None)
        bucket = (state or {}).get(STAGE_STATE_KEY) if isinstance(state, dict) else None
        try:
            return int((bucket or {}).get("round", 0))
        except (TypeError, ValueError):
            return 0

    def _assumptions_tier(self, session: Any) -> str:
        """本次会话生效的 assumptions 档位（116-06）；非三档之一一律回 ``""``（默认档）。

        落点是 ``stage_state["decomposition"]["assumptions_tier"]`` —— 入口建会话时写进
        ``decomposition``，与 ``_current_round`` 读的 ``stage_state["spec_gate"]["round"]``
        不冲突。⭐ 档位只覆盖 ``threshold`` / ``max_rounds``，⛔ **绝不跳过本 stage**。
        """
        state = getattr(session, "stage_state", None)
        bucket = (state or {}).get("decomposition") if isinstance(state, dict) else None
        tier = (
            str((bucket or {}).get(_TIER_STATE_KEY, "") or "") if isinstance(bucket, dict) else ""
        )
        return tier if tier in ASSUMPTIONS_TIERS else ""

    def _initiated_by(self, session: Any) -> str:
        return str(getattr(session, "created_by_id", "") or "system")

    def _goal_text(self, content: dict[str, Any]) -> str:
        spec = content.get("requirement_spec")
        blocks = spec.get("goal") if isinstance(spec, dict) else None
        return self._blocks_to_text(blocks)

    def _feature_points(self, content: dict[str, Any]) -> list[dict[str, Any]]:
        spec = content.get("requirement_spec")
        points = spec.get("feature_points") if isinstance(spec, dict) else None
        return [p for p in points if isinstance(p, dict)] if isinstance(points, list) else []

    def _constraints(self, content: dict[str, Any]) -> list:
        spec = content.get("requirement_spec")
        constraints = spec.get("constraints") if isinstance(spec, dict) else None
        return list(constraints) if isinstance(constraints, list) else []

    def _repo_research_context(self, content: dict[str, Any]) -> str:
        """确认门锁定后落在正文里的仓库集与调研结论 → 喂 scorer 的紧凑摘要（恒不抛）。

        116 重排后本 gate 位于确认门之后，``repo_associations``（含 fitness verdict 与
        reasons 首块）此时已在当前版本正文里。重排前的旧会话（尚未路由）该键为空 ⇒
        返回空串，行为与改动前逐字一致。
        """
        try:
            rows = content.get("repo_associations")
            if not isinstance(rows, list) or not rows:
                return ""
            lines: list[str] = []
            for row in rows[:20]:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("repository_name") or row.get("repository_id") or "").strip()
                if not name:
                    continue
                fitness = row.get("fitness") if isinstance(row.get("fitness"), dict) else {}
                verdict = str(fitness.get("verdict") or "").strip()
                reason = self._blocks_to_text(fitness.get("reasons")).splitlines()
                head = reason[0].strip() if reason else ""
                parts = [name]
                if verdict:
                    parts.append(f"结论 {verdict}")
                if head:
                    parts.append(head[:120])
                lines.append("- " + "：".join(parts[:1]) + ("（" + "；".join(parts[1:]) + "）" if len(parts) > 1 else ""))
            if not lines:
                return ""
            return "已确认的仓库集与调研结论：\n" + "\n".join(lines)
        except Exception:  # noqa: BLE001 — 上下文装配 best-effort，绝不反噬打分主流程
            return ""

    @staticmethod
    def _blocks_to_text(blocks: Any) -> str:
        """block_list 抽纯文本（只取 paragraph/list 的 text，供 prompt 用）。"""
        if not isinstance(blocks, list):
            return str(blocks or "")
        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(text, list):
                parts.extend(str(t) for t in text)
        return "\n".join(parts)

    def _ambiguity_report(
        self,
        scores: dict[str, Any],
        *,
        config: dict[str, Any],
        total: float,
        resolved_thread_ids: list[str],
        capped: bool,
        release_reason: str = RELEASE_REASON_UNAMBIGUOUS,
        scorer_unavailable: bool,
        tier: str = "",
    ) -> dict[str, Any]:
        return {
            "dimensions": scores["dimensions"],
            "weighted_total": total,
            "threshold": config["threshold"],
            "weights": config["weights"],
            # ⭐ 116-06：本轮生效的 assumptions 档位与轮数上界。`_ambiguity_report` 是
            # `ambiguity_report` 的**唯一装配点** ⇒ 加一次即全链留痕，运维据此回答
            # 「这轮为什么问 / 为什么不问」时看到的阈值与判定用的必然同源。
            "assumptions_tier": str(tier or ""),
            "max_rounds": int(config.get("max_rounds") or 0),
            "resolved_thread_ids": list(resolved_thread_ids),
            "capped": capped,
            # 放行例外的具名理由：""=未超阈值的正常放行 / "round_cap"=轮数上界 /
            # "no_new_questions"=超阈值但问不出新问题。capped 恒等于 bool(release_reason)。
            "release_reason": release_reason,
            "scorer_unavailable": scorer_unavailable,
        }

    def _result(
        self,
        event: str,
        thread_id: str | None,
        ambiguity: dict[str, Any],
        round_no: int,
        *,
        pending: bool = False,
    ) -> dict[str, Any]:
        """结果形状恒定：handler 只据 ``event`` 决定 StageOutcome，不解析其它字段。"""
        return {
            "event": event,
            "thread_id": thread_id,
            "ambiguity": ambiguity,
            "round": round_no,
            "stage_state": {
                STAGE_STATE_KEY: {
                    "round": round_no,
                    "thread_id": thread_id,
                    "pending": pending,
                }
            },
        }

    async def _emit(self, session: Any, event_name: str, payload: dict[str, Any]) -> None:
        """事件 emit best-effort（吞异常，观测绝不反噬规格门主流程）。"""
        try:
            await self.session_service.aemit_event(event_name, session, payload)
        except Exception:  # noqa: BLE001 — 事件失败绝不阻断挂起/锁定
            logger.warning(
                "blueprint_spec_gate_event_emit_failed",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                event_name=event_name,
            )
