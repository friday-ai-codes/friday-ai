"""BlueprintConfirmGateAdapter —— 阶段 1 出口硬确认门（Phase 112-05，FLOW-03 / CHARTER-03）。

契约四段：

- **谁调用**：只被 112-05 注册的 ``technical_blueprint.repo_confirmation`` stage handler
  调用（``_h_bp_repo_confirmation``）。adapter 只返回结果 dict，**stage 转移由 handler 的
  ``StageOutcome`` 承担**（engine 纯度：adapter 不写 session.status / current_stage）。
- **INV-6**：线程写入经 ``BlueprintLifecycleService``、蓝图版本写入经
  ``ArtifactService.add_version``——本文件**零 ORM 写**（只读查询）。
- **锁定后变更须重开确认门**：``confirm`` 一次性把仓库集与职责写进 ``repo_associations``
  （``confirmed_at_gate=true`` / ``decided_by=human`` / ``responsibility``）并记
  ``decision_log``；此后任何仓库集变更都必须重开一条 ``repo_confirmation`` 线程
  （114 的 AI 审查据此判 BLOCKER）。
- **章程回灌只产 ai_draft**：职责聚合 → ``owned_domains`` 草案、移除仓 → ``boundaries``
  草案，一律经 ``charter_draft_writeback.asubmit_charter_draft`` 落 ``source=ai_draft``；
  对 ``human_confirmed`` 章程只写 ``draft_content``，人工 confirm 才生效。

回路：pending 门（已有 open 确认门线程即不重开）→ 组装结构化仓库清单快照 → 经 lifecycle
开一条 ``BlueprintThread``（``kind=repo_confirmation``、``blocking=True``）→ emit → 用户
动作经 REST（见 ``delivery/api/blueprint_gate_views.py``）→ ``confirm`` 触发 :meth:`alock`。

**待调研判据单一实现**：模块级 :func:`acollect_pending_research_repos` 同时被
``_h_bp_repo_confirmation``（决定 ``research_required`` 出边）与
``blueprint_resume``（决定 ``waiting_clarification`` 是否放行一步 advance）复用——
两处各写一份判据即 SC-4 断链（确认门线程恒 open，resume 会把该放行的 advance 短路掉）。
"""

from __future__ import annotations

import copy
import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.logging import redact_secrets_in_text
from delivery.models import (
    ArtifactVersion,
    BlueprintStatus,
    BlueprintThread,
    RepoResearchTaskStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactContentInvalid, ArtifactService, ConvergenceSessionService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from delivery.services.event_taxonomy import (
    EVENT_BLUEPRINT_CONFIRMATION_LOCKED,
    EVENT_BLUEPRINT_CONFIRMATION_OPENED,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintConfirmGateAdapter",
    "STAGE_STATE_KEY",
    "LOCK_BLOCKED_PENDING_RESEARCH",
    "LOCK_BLOCKED_SNAPSHOT_CHANGED",
    "acollect_pending_research_repos",
    "acollect_confirmation_state",
    "build_locked_associations",
]

# session.stage_state 内确认门的键（112-04 的增量 dispatch 从这里读 pending_research）。
STAGE_STATE_KEY = "confirmation"

# `alock` 拒绝落锁的两个并发理由（视图据此选 409 文案；handler 不读）。
LOCK_BLOCKED_PENDING_RESEARCH = "pending_research"
LOCK_BLOCKED_SNAPSHOT_CHANGED = "snapshot_changed"

# 快照「小摘要」纪律：正文类字段截断，明细由 115 按 id 自取。
_MAX_RESPONSIBILITY_CHARS = 2000
_MAX_SUMMARY_CHARS = 1000
_MAX_LIST_ITEMS = 10

# 章程 `owned_domains[].domain` 是**领域名**（会被 score_charter_match 拿去做子串/n-gram
# 匹配），不是职责正文：超长 domain 与任意需求几乎必然有交集，等于让该仓恒命中。
_MAX_DOMAIN_CHARS = 40

_VALID_ROLES = ("direct", "indirect")
_VALID_VERDICTS = ("suitable", "partial", "unsuitable")

# 待重调研判据的第二个合取项：只有 task 仍可派发时标记才算「有待调研」。
_DISPATCHABLE_STATUSES = (RepoResearchTaskStatus.PENDING, RepoResearchTaskStatus.STALE)

_GATE_QUESTION = (
    "请确认本次需求涉及的仓库集与各仓职责。可执行的动作："
    "移除不该参与的仓、手动补充遗漏的仓（会触发该仓调研）、改判 direct/indirect 角色、"
    "修改职责描述；确认后仓库集与职责将锁定进蓝图，后续变更需重开本确认门。"
)


# ══════════════════════════════════════════════════════════════════════════
# 模块级：待调研判据（唯一实现，两个消费方共用）
# ══════════════════════════════════════════════════════════════════════════


def iter_snapshot_repos(snapshot: Any) -> list[dict[str, Any]]:
    """确认门快照的仓清单（兼容 ``{"repos": [...]}`` 与裸 list，形状与 112-04 对齐）。"""
    if isinstance(snapshot, dict):
        for key in ("repos", "repositories", "candidates"):
            value = snapshot.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(snapshot, list):
        return [item for item in snapshot if isinstance(item, dict)]
    return []


async def acollect_pending_research_repos(session: Any) -> list[str]:
    """待重调研仓 id 列表（**判据唯一实现**，绝不抛）。

    判据是**合取**：① 确认门快照里该仓 ``pending_research is True``；② 该仓的
    ``RepoResearchTask`` 仍在 ``pending`` / ``stale``。合取使标记**无需清位**——
    task 一旦被 dispatch 推到 ``running`` 判据即自然为假，遗留标记不会造成重复回边
    或死循环。

    标记来源取「``stage_state["confirmation"]`` ∪ 活跃确认门线程 ``options``」的并集：
    动作端点只写线程行（service 是线程唯一 writer），``stage_state`` 要等下一次
    ``transition`` 才刷新——只读 ``stage_state`` 会让紧随动作的那次续驱判据为空，
    ``research_required`` 边永远走不到（SC-4 断链）。

    Returns:
        仓 id 字符串列表（去重、排序）；无待调研仓 / 读失败 / 状态形状非法 → ``[]``。
    """
    try:
        marked = await _acollect_marked_repository_ids(session)
        if not marked:
            return []
        return await _afilter_dispatchable_repos(getattr(session, "id", None), sorted(marked))
    except Exception as exc:  # noqa: BLE001 — 判据绝不抛（抛了会把 advance 变成 fail）
        logger.warning(
            "blueprint_confirm_gate_pending_probe_failed",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
        return []


async def acollect_confirmation_state(session: Any) -> dict[str, Any] | None:
    """从活跃确认门线程重建 ``stage_state["confirmation"]`` 落盘值（只读）。

    handler 在返回 ``research_required`` 时用它把最新快照写进 ``stage_state``——
    112-04 的增量 ``dispatch`` 只认 ``stage_state["confirmation"]``，不刷就派不到新仓。
    """
    try:
        artifact_id = await _aresolve_artifact_id(session)
        if artifact_id is None:
            return None
        row = await _aload_active_gate_row(artifact_id)
        if row is None:
            return None
        return {
            "thread_id": str(row["id"]),
            "thread_status": str(row["status"]),
            "repos": iter_snapshot_repos(row["options"]),
        }
    except Exception:  # noqa: BLE001 — 只读装配失败按「无快照」处理，绝不阻断 advance
        return None


async def _acollect_marked_repository_ids(session: Any) -> set[str]:
    marked: set[str] = set()
    stage_state = getattr(session, "stage_state", None)
    if isinstance(stage_state, dict):
        for item in iter_snapshot_repos(stage_state.get(STAGE_STATE_KEY)):
            if item.get("pending_research") is True:
                marked.add(str(item.get("repository_id") or ""))
    artifact_id = await _aresolve_artifact_id(session)
    if artifact_id is not None:
        marked |= await _acollect_thread_marked_repos(artifact_id)
    marked.discard("")
    return marked


async def _aresolve_artifact_id(session: Any) -> Any:
    version_id = getattr(session, "current_artifact_version_id", None)
    if not version_id:
        return None
    return await (
        ArtifactVersion.objects.filter(id=version_id).values_list("artifact_id", flat=True).afirst()
    )


@sync_to_async
def _acollect_thread_marked_repos(artifact_id: Any) -> set[str]:
    """活跃确认门线程 options 里打了 ``pending_research`` 的仓（动作端点的即时写入面）。"""
    marked: set[str] = set()
    rows = BlueprintThread.objects.filter(
        artifact_id=artifact_id,
        kind=ThreadKind.REPO_CONFIRMATION,
        status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
    ).values_list("options", flat=True)
    for options in rows:
        for item in iter_snapshot_repos(options):
            if item.get("pending_research") is True:
                marked.add(str(item.get("repository_id") or ""))
    return marked


@sync_to_async
def _aload_active_gate_row(artifact_id: Any) -> dict[str, Any] | None:
    return (
        BlueprintThread.objects.filter(
            artifact_id=artifact_id,
            kind=ThreadKind.REPO_CONFIRMATION,
            status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
        )
        .order_by("-created_at")
        .values("id", "status", "options")
        .first()
    )


@sync_to_async
def _afilter_dispatchable_repos(session_id: Any, repository_ids: list[str]) -> list[str]:
    from delivery.models import RepoResearchTask

    if session_id is None or not repository_ids:
        return []
    rows = RepoResearchTask.objects.filter(
        session_id=session_id,
        repository_id__in=repository_ids,
        status__in=_DISPATCHABLE_STATUSES,
    ).values_list("repository_id", flat=True)
    return sorted({str(rid) for rid in rows})


# ══════════════════════════════════════════════════════════════════════════
# 模块级纯函数：快照 → 蓝图 repo_associations
# ══════════════════════════════════════════════════════════════════════════


def _block(block_id: str, text: Any) -> dict[str, Any]:
    return {"block_id": block_id, "type": "paragraph", "text": text}


def _as_block_list(text: Any, *, block_id: str) -> list[dict[str, Any]]:
    """纯文本 → block_list（schema 的 ``$defs/block_list``）；空文本产空数组。"""
    if isinstance(text, list):
        blocks = [item for item in text if isinstance(item, dict) and item.get("block_id")]
        return blocks
    value = str(text or "").strip()
    if not value:
        return []
    return [_block(block_id, value[:_MAX_RESPONSIBILITY_CHARS])]


def build_locked_associations(
    *,
    snapshot: list[dict[str, Any]],
    decisions: dict[str, Any] | None = None,
    citation_pool: set[str] | None = None,
) -> list[dict[str, Any]]:
    """快照 + 用户裁决 → 蓝图 ``repo_associations`` 条目（**纯函数**）。

    - 被 ``remove_repo`` 的仓**不进** associations（其信息进 ``boundaries`` 草案与
      ``decision_log``）。
    - 一律写 ``decided_by="human"`` / ``confirmed_at_gate=True``：确认门是人工裁决点。
    - 字段名严格对齐 ``blueprint_schema`` 的 ``repo_associations`` 子集，不新增 schema 外键；
      ``responsibility`` / ``fitness.reasons`` 落 block_list 形状。
    - ``citation_pool`` 非 None 时对 ``fitness.citations`` 做**白名单过滤**：schema 后置检查
      要求任何块内 ``citations`` id 必须存在于文档级引用池，调研产出的裸文件路径若直接落进
      去会让整份蓝图校验失败（fail-closed 时确认门永远锁不上）。
    - ``decisions`` 是按 ``repository_id`` 的覆盖层（``{rid: {role, responsibility, removed}}``），
      缺省空 —— 快照本身已承载动作结果，覆盖层只服务于调用方的显式最终裁决。
    """
    overrides = decisions if isinstance(decisions, dict) else {}
    associations: list[dict[str, Any]] = []
    for entry in snapshot or []:
        if not isinstance(entry, dict):
            continue
        repository_id = str(entry.get("repository_id") or "")
        if not repository_id:
            continue
        override = (
            overrides.get(repository_id) if isinstance(overrides.get(repository_id), dict) else {}
        )
        if entry.get("removed") is True or override.get("removed") is True:
            continue

        role = str(override.get("role") or entry.get("role_suggestion") or "").strip()
        if role not in _VALID_ROLES:
            # 保守回落 direct：把「要改的仓」误判成「不用改」的代价远高于反过来。
            role = "direct"
        responsibility = override.get("responsibility", entry.get("responsibility"))

        association: dict[str, Any] = {
            "repository_id": repository_id,
            # schema 要求 minLength 1：无名时回落 id（绝不产非法版本）
            "repository_name": str(entry.get("repository_name") or "") or repository_id,
            "role": role,
            "responsibility": _as_block_list(
                responsibility, block_id=f"blk_gate_resp_{repository_id}"
            ),
            "routing_evidence": _clean_routing_evidence(entry.get("routing_evidence")),
            "decided_by": "human",
            "confirmed_at_gate": True,
        }
        fitness = _clean_fitness(
            entry.get("fitness"), repository_id=repository_id, citation_pool=citation_pool
        )
        if fitness:
            association["fitness"] = fitness
        associations.append(association)
    return associations


def _clean_fitness(
    raw: Any, *, repository_id: str, citation_pool: set[str] | None
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    fitness: dict[str, Any] = {}
    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict in _VALID_VERDICTS:
        fitness["verdict"] = verdict
    reasons = raw.get("reasons")
    blocks: list[dict[str, Any]] = []
    if isinstance(reasons, list):
        for index, reason in enumerate(reasons[:_MAX_LIST_ITEMS]):
            if isinstance(reason, dict) and reason.get("block_id"):
                blocks.append(reason)
            elif str(reason or "").strip():
                blocks.append(
                    _block(
                        f"blk_gate_fit_{repository_id}_{index}",
                        str(reason).strip()[:_MAX_SUMMARY_CHARS],
                    )
                )
    if blocks:
        fitness["reasons"] = blocks
    citations = [str(c) for c in (raw.get("citations") or []) if str(c or "").strip()]
    if citation_pool is not None:
        citations = [c for c in citations if c in citation_pool]
    if citations:
        fitness["citations"] = citations[:_MAX_LIST_ITEMS]
    return fitness


def _clean_routing_evidence(raw: Any) -> dict[str, Any]:
    """routing_evidence 只留标量与短清单（正文明细由 115 按 id 自取）。"""
    src = raw if isinstance(raw, dict) else {}
    return {
        "total": _as_float(src.get("total")),
        "router_base": _as_float(src.get("router_base")),
        "charter_match": _as_float(src.get("charter_match")),
        "history_match": _as_float(src.get("history_match")),
        "router_version": str(src.get("router_version") or ""),
        "confidence": str(src.get("confidence") or ""),
        "matched_domains": [str(item) for item in (src.get("matched_domains") or [])][
            :_MAX_LIST_ITEMS
        ],
        "violated_boundaries": [str(item) for item in (src.get("violated_boundaries") or [])][
            :_MAX_LIST_ITEMS
        ],
        "history_match_unavailable": str(src.get("history_match_unavailable") or ""),
    }


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ══════════════════════════════════════════════════════════════════════════
# 确认门 adapter
# ══════════════════════════════════════════════════════════════════════════


class BlueprintConfirmGateAdapter:
    """确认门 adapter（依赖全 keyword-only 可注入，与 ``BlueprintSpecGateAdapter`` 同形）。"""

    def __init__(
        self,
        *,
        lifecycle: BlueprintLifecycleService | None = None,
        artifacts: ArtifactService | None = None,
        fitness_loader: Any = None,
        charter_writer: Any = None,
        session_service: ConvergenceSessionService | None = None,
    ) -> None:
        self.lifecycle = lifecycle or BlueprintLifecycleService()
        self.artifacts = artifacts or ArtifactService()
        self._fitness_loader = fitness_loader
        self._charter_writer = charter_writer
        self.session_service = session_service or ConvergenceSessionService()

    # ── 开门 ──────────────────────────────────────────────────────────────

    async def open_gate(self, session: Any) -> dict[str, Any]:
        """开确认门（或短路），返回形状恒定的结果 dict。

        Returns:
            ``{"event": "awaiting_confirmation" | "confirmed", "thread_id": str | None,
            "stage_state": {"confirmation": {...}} | None, "repo_count": int}``
        """
        started = time.monotonic()
        version = await self._aload_current_version(session)
        if version is None:
            # 无蓝图版本 = 既无从组装快照也无处挂线程：保持挂起等上游补齐（fail-closed）。
            logger.warning(
                "blueprint_confirm_gate_no_artifact_version",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
            )
            return self._result("awaiting_confirmation", None, None, 0)

        artifact = version.artifact

        # 1. pending 门：已有 open+blocking 确认门线程 → 不重复开门、不重算快照。
        if await self.lifecycle.ahas_open_blocking_threads(
            artifact, kind=ThreadKind.REPO_CONFIRMATION
        ):
            state = await acollect_confirmation_state(session)
            thread_id = str((state or {}).get("thread_id") or "") or None
            return self._result(
                "awaiting_confirmation",
                thread_id,
                {STAGE_STATE_KEY: state} if state else None,
                len(iter_snapshot_repos((state or {}).get("repos"))),
            )

        # 2. 已锁定（confirm 已把线程收尾）→ confirmed 边通往终态。
        locked = await self._aload_locked_gate_row(artifact.id)
        if locked is not None:
            return self._result(
                "confirmed",
                str(locked["id"]),
                {STAGE_STATE_KEY: {"thread_id": str(locked["id"]), "confirmed": True, "repos": []}},
                0,
            )

        # 3. 首次进门：组装结构化仓库清单快照并开一条阻塞线程。
        snapshot = await self._abuild_snapshot(session)
        thread = await self.lifecycle.open_thread(
            artifact,
            kind=ThreadKind.REPO_CONFIRMATION,
            blocking=True,
            question=_GATE_QUESTION,
            options=snapshot,
            initiated_by_user_id=self._initiated_by(session),
            created_on_version=version,
            return_stage=BlueprintStatus.RESEARCHING,
        )
        unsuitable = sum(
            1
            for entry in snapshot
            if str((entry.get("fitness") or {}).get("verdict") or "") == "unsuitable"
        )
        escalated = bool(self._stage_state(session).get("escalation"))
        await self._emit(
            session,
            EVENT_BLUEPRINT_CONFIRMATION_OPENED,
            {
                "thread_id": str(thread.id),
                "repo_count": len(snapshot),
                "unsuitable_count": unsuitable,
                "escalated": escalated,
            },
        )
        logger.info(
            "blueprint_confirmation_opened",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            artifact_id=str(artifact.id),
            thread_id=str(thread.id),
            repo_count=len(snapshot),
            unsuitable_count=unsuitable,
            escalated=escalated,
            initiated_by_user_id=self._initiated_by(session),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return self._result(
            "awaiting_confirmation",
            str(thread.id),
            {STAGE_STATE_KEY: {"thread_id": str(thread.id), "repos": snapshot}},
            len(snapshot),
        )

    # ── 锁定 ──────────────────────────────────────────────────────────────

    async def alock(
        self,
        session: Any,
        *,
        acting_user: Any = None,
        decisions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """确认锁定：仓库集与职责写进 ``repo_associations`` + ``decision_log`` 逐动作留痕。

        fail-closed：``ArtifactContentInvalid`` 不放行也不落 failed，返回
        ``awaiting_confirmation`` 等人修规格；章程草案逐仓 best-effort，失败只 warning。
        """
        started = time.monotonic()
        version = await self._aload_current_version(session)
        if version is None:
            return self._result("awaiting_confirmation", None, None, 0)
        artifact = version.artifact

        thread = await self._aload_active_gate_thread(artifact.id)
        if thread is None:
            logger.warning(
                "blueprint_confirm_gate_no_open_thread",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                artifact_id=str(artifact.id),
            )
            return self._result("awaiting_confirmation", None, None, 0)

        snapshot = iter_snapshot_repos(thread.options)
        # 锁前重查待调研仓：有仓在调研途中就绝不落锁——否则 `confirm` 会拿着不含新仓的
        # 旧快照锁定并 `resolve_thread` 关门，而 `_acollect_thread_marked_repos` 只查
        # OPEN/ANSWERED 线程，已 RESOLVED 线程里的 `pending_research` 标记再也读不到：
        # 用户的 `add_repo` 静默丢失，那个 PENDING task 成为既不派发也不终态的孤儿。
        pending = await acollect_pending_research_repos(session)
        if pending:
            logger.warning(
                "blueprint_confirm_gate_lock_blocked_by_pending_research",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                artifact_id=str(artifact.id),
                pending_count=len(pending),
            )
            return self._result(
                "awaiting_confirmation",
                str(thread.id),
                None,
                0,
                reason=LOCK_BLOCKED_PENDING_RESEARCH,
            )
        # 快照 CAS 基线：动作端点每次写快照都会推进 `updated_at`，落锁前比对即可发现
        # 「读快照之后又有动作提交」的交错，避免按过期快照锁定（用户动作静默丢失）。
        snapshot_baseline = getattr(thread, "updated_at", None)
        # 锁定基线取 artifact 的**最新**版本而非 session 钉住的那一版：规格门放行时
        # add_version 已推进 current_version，而 session.current_artifact_version 只在
        # 显式 StageOutcome 里才更新——读 session 那一版会把规格门的成果覆盖回旧内容。
        latest = await self._aload_latest_version(artifact.id)
        base = latest if latest is not None else version
        content = copy.deepcopy(base.content if isinstance(base.content, dict) else {})
        pool = content.get("citations")
        citation_pool = set(pool.keys()) if isinstance(pool, dict) else set()

        associations = build_locked_associations(
            snapshot=snapshot, decisions=decisions, citation_pool=citation_pool
        )
        content["repo_associations"] = associations
        content["decision_log"] = _merge_decision_log(
            content.get("decision_log"),
            _build_decision_entries(snapshot, thread_id=str(thread.id)),
        )

        if not await self._asnapshot_unchanged(thread.id, snapshot_baseline):
            logger.warning(
                "blueprint_confirm_gate_lock_snapshot_changed",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                artifact_id=str(artifact.id),
                thread_id=str(thread.id),
            )
            return self._result(
                "awaiting_confirmation",
                str(thread.id),
                None,
                0,
                reason=LOCK_BLOCKED_SNAPSHOT_CHANGED,
            )

        try:
            new_version = await self.artifacts.add_version(
                artifact,
                content,
                produced_by_session_id=str(getattr(session, "id", "")),
                produced_by_ref="blueprint_confirm_gate",
            )
        except ArtifactContentInvalid as exc:
            logger.warning(
                "blueprint_confirm_gate_invalid_content",
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                artifact_id=str(artifact.id),
                error=redact_secrets_in_text(str(exc)),
            )
            return self._result("awaiting_confirmation", str(thread.id), None, len(associations))

        await self.lifecycle.resolve_thread(
            thread,
            resolution="仓库集与职责已确认锁定。",
            initiated_by_user_id=self._initiated_by(session),
        )
        if acting_user is not None:
            await self.lifecycle.add_reviewer(artifact, acting_user, "repo_confirmation")

        draft_count = await self._asubmit_charter_drafts(
            snapshot, initiated_by_user_id=self._initiated_by(session)
        )

        removed = [entry for entry in snapshot if entry.get("removed") is True]
        await self._emit(
            session,
            EVENT_BLUEPRINT_CONFIRMATION_LOCKED,
            {
                "locked_repo_count": len(associations),
                "removed_count": len(removed),
                "decided_by": "human",
                "charter_draft_count": draft_count,
            },
        )
        logger.info(
            "blueprint_confirmation_locked",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            artifact_id=str(artifact.id),
            thread_id=str(thread.id),
            locked_repo_count=len(associations),
            removed_count=len(removed),
            charter_draft_count=draft_count,
            version_no=getattr(new_version, "version_no", 0),
            initiated_by_user_id=self._initiated_by(session),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return self._result("confirmed", str(thread.id), None, len(associations))

    # ── 章程草案回灌（一律 ai_draft，逐仓 best-effort） ────────────────────

    async def _asubmit_charter_drafts(
        self, snapshot: list[dict[str, Any]], *, initiated_by_user_id: str
    ) -> int:
        writer = self._charter_writer
        if writer is None:
            from repositories.services.charter_draft_writeback import asubmit_charter_draft

            writer = asubmit_charter_draft

        submitted = 0
        for entry in snapshot:
            repository_id = str(entry.get("repository_id") or "")
            if not repository_id:
                continue
            draft = _build_charter_draft(entry)
            if not draft:
                continue
            try:
                # 逐仓独立隔离：单仓草案失败绝不反噬锁定（锁定已是人工裁决的结果）。
                await writer(repository_id, draft, initiated_by_user_id=initiated_by_user_id)
                submitted += 1
            except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬确认锁定
                logger.warning(
                    "blueprint_confirm_gate_charter_draft_failed",
                    category="caller",
                    component="process_runtime",
                    repository_id=repository_id,
                    error=redact_secrets_in_text(str(exc)),
                )
        return submitted

    # ── 只读装配 helper（adapter 零 ORM 写，INV-6） ────────────────────────

    async def _abuild_snapshot(self, session: Any) -> list[dict[str, Any]]:
        """组装结构化仓库清单快照（路由候选 ∪ fitness 聚合 ∪ escalation 现状）。"""
        state = self._stage_state(session)
        routing = state.get("routing") if isinstance(state.get("routing"), dict) else {}
        candidates: dict[str, dict[str, Any]] = {}
        for item in routing.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            repository_id = str(item.get("repository_id") or "")
            if repository_id:
                candidates[repository_id] = item

        fitness = await self._acollect_fitness(session)
        escalation = state.get("escalation") if isinstance(state.get("escalation"), dict) else {}
        escalated_repos = {
            str(item.get("repository_id") or ""): item
            for item in (escalation.get("repos") or [])
            if isinstance(item, dict)
        }

        repository_ids = list(candidates) + [
            rid for rid in list(fitness) + list(escalated_repos) if rid not in candidates
        ]
        router_version = str(routing.get("router_version") or "")

        snapshot: list[dict[str, Any]] = []
        for repository_id in repository_ids:
            if not repository_id:
                continue
            candidate = candidates.get(repository_id) or {}
            conclusion = fitness.get(repository_id) or escalated_repos.get(repository_id) or {}
            snapshot.append(
                _build_snapshot_entry(
                    repository_id,
                    candidate=candidate,
                    conclusion=conclusion,
                    router_version=router_version,
                )
            )
        return snapshot

    async def _acollect_fitness(self, session: Any) -> dict[str, dict[str, Any]]:
        loader = self._fitness_loader
        if loader is None:
            from services.process_runtime.blueprint_research_adapter import (
                BlueprintResearchAdapter,
            )

            loader = BlueprintResearchAdapter().acollect_fitness
        try:
            result = await loader(session)
        except Exception as exc:  # noqa: BLE001 — 聚合失败按「无结论」组装（快照仍开得出）
            logger.warning(
                "blueprint_confirm_gate_fitness_collect_failed",
                category="sampling",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
            )
            return {}
        return result if isinstance(result, dict) else {}

    async def _aload_current_version(self, session: Any) -> Any:
        version_id = getattr(session, "current_artifact_version_id", None)
        if not version_id:
            return None
        return await (
            ArtifactVersion.objects.select_related("artifact").filter(id=version_id).afirst()
        )

    @staticmethod
    async def _aload_latest_version(artifact_id: Any) -> Any:
        return await (
            ArtifactVersion.objects.filter(artifact_id=artifact_id).order_by("-version_no").afirst()
        )

    @staticmethod
    async def _aload_active_gate_thread(artifact_id: Any) -> Any:
        return await (
            BlueprintThread.objects.filter(
                artifact_id=artifact_id,
                kind=ThreadKind.REPO_CONFIRMATION,
                status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
            )
            .order_by("-created_at")
            .afirst()
        )

    @staticmethod
    async def _asnapshot_unchanged(thread_id: Any, baseline: Any) -> bool:
        """确认门快照自读取以来未被别的动作改过（``updated_at`` 乐观锁）。"""
        if baseline is None:
            return True
        current = await (
            BlueprintThread.objects.filter(id=thread_id)
            .values_list("updated_at", flat=True)
            .afirst()
        )
        return current == baseline

    @staticmethod
    @sync_to_async
    def _aload_locked_gate_row(artifact_id: Any) -> dict[str, Any] | None:
        return (
            BlueprintThread.objects.filter(
                artifact_id=artifact_id,
                kind=ThreadKind.REPO_CONFIRMATION,
                status=ThreadStatus.RESOLVED,
            )
            .order_by("-created_at")
            .values("id")
            .first()
        )

    @staticmethod
    def _stage_state(session: Any) -> dict[str, Any]:
        state = getattr(session, "stage_state", None)
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _initiated_by(session: Any) -> str:
        return (
            str(getattr(session, "initiated_by_user_id", "") or "")
            or str(getattr(session, "created_by_id", "") or "")
            or "system"
        )

    @staticmethod
    def _result(
        event: str,
        thread_id: str | None,
        stage_state: dict[str, Any] | None,
        repo_count: int,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        """结果形状恒定：handler 只据 ``event`` 决定 StageOutcome。

        ``reason`` 只给视图层区分 409 文案（并发/待调研 vs 内容非法），handler 不读。
        """
        return {
            "event": event,
            "thread_id": thread_id,
            "stage_state": stage_state,
            "repo_count": repo_count,
            "reason": reason,
        }

    async def _emit(self, session: Any, event_name: str, payload: dict[str, Any]) -> None:
        """事件 emit best-effort（payload 只含计数与关联键，绝不含职责/需求正文）。"""
        try:
            await self.session_service._emit_event(event_name, session, payload)
        except Exception:  # noqa: BLE001 — 观测绝不反噬确认门
            logger.warning(
                "blueprint_confirm_gate_event_emit_failed",
                category="sampling",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                event_name=event_name,
            )


# ══════════════════════════════════════════════════════════════════════════
# 快照条目与决策留痕（模块级纯函数）
# ══════════════════════════════════════════════════════════════════════════


def _build_snapshot_entry(
    repository_id: str,
    *,
    candidate: dict[str, Any],
    conclusion: dict[str, Any],
    router_version: str,
) -> dict[str, Any]:
    """单仓快照条目：role 建议 / 职责 / fitness 结论 / 现状摘要 / 证据引用。"""
    breakdown = candidate.get("breakdown") if isinstance(candidate.get("breakdown"), dict) else {}
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    role = str(conclusion.get("role_suggestion") or candidate.get("role_suggestion") or "").strip()
    if role not in _VALID_ROLES:
        role = "direct"
    verdict = str(conclusion.get("verdict") or "").strip().lower()
    return {
        "repository_id": repository_id,
        "repository_name": str(candidate.get("repository_name") or ""),
        "role_suggestion": role,
        "responsibility": str(conclusion.get("responsibility") or "")[:_MAX_RESPONSIBILITY_CHARS],
        "confidence": str(candidate.get("confidence") or ""),
        "fitness": {
            "verdict": verdict if verdict in _VALID_VERDICTS else "",
            "reasons": [],
            "citations": [],
        },
        "current_state_summary": _summarize_findings(conclusion.get("findings")),
        "routing_evidence": {
            "total": _as_float(candidate.get("total")),
            "router_base": _as_float(breakdown.get("router_base")),
            "charter_match": _as_float(breakdown.get("charter_match")),
            "history_match": _as_float(breakdown.get("history_match")),
            "router_version": str(evidence.get("router_version") or router_version),
            "confidence": str(candidate.get("confidence") or ""),
            "matched_domains": [
                str(item.get("domain", "")) if isinstance(item, dict) else str(item)
                for item in (evidence.get("matched_domains") or [])
            ][:_MAX_LIST_ITEMS],
            "violated_boundaries": [
                str(item) for item in (evidence.get("violated_boundaries") or [])
            ][:_MAX_LIST_ITEMS],
            "history_match_unavailable": str(evidence.get("history_match_unavailable") or ""),
        },
        "task_status": str(conclusion.get("task_status") or ""),
        "pending_research": False,
        "removed": False,
        "actions": [],
    }


def _summarize_findings(findings: Any) -> str:
    if not isinstance(findings, list):
        return ""
    parts: list[str] = []
    for item in findings[:_MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if title or detail:
            parts.append(f"{title}：{detail}" if title and detail else (title or detail))
    return "\n".join(parts)[:_MAX_SUMMARY_CHARS]


def _build_decision_entries(
    snapshot: list[dict[str, Any]], *, thread_id: str
) -> list[dict[str, Any]]:
    """逐动作 decision_log 条目（形状 ``{thread_id, action, repository_id, before, after, ...}``）。"""
    entries: list[dict[str, Any]] = []
    fallback_at = timezone.now().isoformat()
    for entry in snapshot or []:
        if not isinstance(entry, dict):
            continue
        repository_id = str(entry.get("repository_id") or "")
        for action in entry.get("actions") or []:
            if not isinstance(action, dict):
                continue
            name = str(action.get("action") or "").strip()
            if not name:
                continue
            entries.append(
                {
                    "thread_id": thread_id,
                    "action": name,
                    "repository_id": repository_id,
                    "before": action.get("before")
                    if isinstance(action.get("before"), dict)
                    else {},
                    "after": action.get("after") if isinstance(action.get("after"), dict) else {},
                    "decided_at": str(action.get("decided_at") or fallback_at),
                    "decided_by": str(action.get("decided_by") or "human"),
                }
            )
    return entries


def _merge_decision_log(existing: Any, entries: list[dict[str, Any]]) -> list[Any]:
    """按 ``(thread_id, action, repository_id)`` 去重追加（幂等重跑不堆积）。"""
    merged = list(existing) if isinstance(existing, list) else []
    seen = {
        (
            str(item.get("thread_id") or ""),
            str(item.get("action") or ""),
            str(item.get("repository_id") or ""),
        )
        for item in merged
        if isinstance(item, dict)
    }
    for entry in entries:
        key = (entry["thread_id"], entry["action"], entry["repository_id"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged


def _build_charter_draft(entry: dict[str, Any]) -> dict[str, Any]:
    """单仓章程草案：确认/改判 → owned_domains；被移除 → boundaries（一律 ai_draft）。"""
    repository_name = str(entry.get("repository_name") or "")
    if entry.get("removed") is True:
        reason = str(entry.get("remove_reason") or "").strip()
        rule = f"本类需求不落此仓（用户在蓝图确认门移除{('：' + reason) if reason else ''}）"
        return {"boundaries": [{"rule": rule[:500], "decided_by": "human", "citations": []}]}

    responsibility = str(entry.get("responsibility") or "").strip()
    if not responsibility:
        return {}
    domain = _extract_domain_name(entry)
    if not domain:
        # 宁可不回灌，也不写一条会污染路由的「领域」：`domain` 会被 `score_charter_match`
        # 拿去做子串 / n-gram 匹配，把一整段职责正文塞进去等于让该仓对任意需求近乎恒命中
        # （owned_implemented=1.0），而 ai_draft 对既有 ai_draft 章程是就地生效、无需人工
        # confirm —— 一次确认门操作就能把这个仓变成「什么需求都归我」。
        return {}
    role = str(entry.get("role_suggestion") or "")
    return {
        "owned_domains": [
            {
                "domain": domain,
                "status": "implemented" if role == "direct" else "planned",
                # 职责正文落 note（不参与匹配），领域名才是匹配面
                "note": f"{responsibility[:500]}（来自蓝图确认门的人工确认"
                f"{('：' + repository_name) if repository_name else ''}）",
                "citations": [],
            }
        ]
    }


def _extract_domain_name(entry: dict[str, Any]) -> str:
    """取短领域名：路由证据的 ``matched_domains`` 首项，取不到返空串（调用方不产草案）。"""
    evidence = entry.get("routing_evidence")
    domains = evidence.get("matched_domains") if isinstance(evidence, dict) else None
    for item in domains or []:
        name = str(item.get("domain", "") if isinstance(item, dict) else item).strip()
        if name:
            return name[:_MAX_DOMAIN_CHARS]
    return ""
