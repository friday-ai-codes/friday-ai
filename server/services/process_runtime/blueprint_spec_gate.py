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
_MAX_SPEC_GATE_ROUNDS = 3

# 合法 intent 集合（与 blueprint_schema 的必填枚举同源，只作 adapter 侧沿用值判断）。
_VALID_INTENTS = ("greenfield", "brownfield", "fix")

# 满歧义（四维全 1.0 的加权总分上界）。到达此值时**任何情况都不得**按「无新问题」放行——
# 唯一放行例外仍是显式轮数上界（_MAX_SPEC_GATE_ROUNDS，留 capped=True 痕）。
_MAX_AMBIGUITY_TOTAL = 1.0

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
        content = version.content if isinstance(version.content, dict) else {}

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

        # 3. 轮数上界：达上界带现有信息放行并留痕，绝不无限挂起（镜像 clarify_adapter 兜底）。
        if round_no >= _MAX_SPEC_GATE_ROUNDS:
            logger.warning(
                "blueprint_spec_gate_cap_reached",
                category="caller",
                component="process_runtime",
                session_id=str(session.id),
                artifact_id=str(artifact.id),
                round=round_no,
                max_rounds=_MAX_SPEC_GATE_ROUNDS,
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
                started=started,
            )

        # 4. 四维打分；不可得即 fail-closed（保守全 1.0 + 一条通用规格澄清题）。
        scores = await self.scorer(
            goal=self._goal_text(content),
            feature_points=self._feature_points(content),
            constraints=self._constraints(content),
            prior_context=prior["text"],
            session_id=str(session.id),
        )
        scorer_unavailable = not isinstance(scores, dict)
        if scorer_unavailable:
            scores = normalize_ambiguity_scores(None)
            scores["questions"] = [dict(_FALLBACK_QUESTION)]

        config = await aload_spec_gate_config()
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
            # （轮数由 _MAX_SPEC_GATE_ROUNDS 兜底，不会无限挂）。
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
        started: float,
    ) -> dict[str, Any]:
        """规格锁定：intent 补齐 + ambiguity_report + decision_log 一次性落新蓝图版本。"""
        if config is None:
            config = await aload_spec_gate_config()
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
        return self._result("spec_locked", None, spec["ambiguity_report"], round_no)

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
    ) -> dict[str, Any]:
        return {
            "dimensions": scores["dimensions"],
            "weighted_total": total,
            "threshold": config["threshold"],
            "weights": config["weights"],
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
            await self.session_service._emit_event(event_name, session, payload)
        except Exception:  # noqa: BLE001 — 事件失败绝不阻断挂起/锁定
            logger.warning(
                "blueprint_spec_gate_event_emit_failed",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                event_name=event_name,
            )
