"""BlueprintContextService —— 蓝图上下文总线的唯一写入口（Phase 113-01，DESIGN §5.6）。

- **``BlueprintContextEntry`` 的唯一 writer（INV-6）**：容器 MCP view / 回调 / adapter
  一律零裸 ORM 写，只经本 service 的公开方法读写总线。
- **``seq`` 分配锁父 ``ConvergenceSession`` 行串行化**——不锁子表（``select_for_update``
  对空结果集无可靠 gap lock，MySQL/PG 行为不一）；``UniqueConstraint(session, seq)``
  是**兜底不是主手段**，捕 ``IntegrityError`` 有界重试。
- **waiter 落 ``kind="dependency_claim"`` 行而非 ``stage_state``**：并行容器高频登记/命中
  会绕过 barrier 的单点串行，单行 JSON 必然 lost-update（RESEARCH P3）。
- **入库前脱敏不可绕过**：``content`` 是 JSON dict 而非 str，走本模块自建的
  ``_redact_json`` **递归叶子脱敏**；**禁止** ``redact_secrets_in_text(json.dumps(...))``
  再 ``loads``（破坏结构且可能产生非法 JSON）。脱敏失败 **fail-closed**（回落空串，
  不回落原文）。
- **观测**：条目读写记 ``category="sampling"``，waiter 登记/命中/超时记
  ``category="caller"``，统一 ``component="blueprint_context"``；**``content`` 正文与
  ``key`` 以外的自由文本绝不进日志与事件 payload**。
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from common.logging import redact_secrets_in_text
from delivery.models import (
    BlueprintContextEntry,
    ContextEntryKind,
    ContextEntryStatus,
    ConvergenceSession,
    ThreadKind,
)
from delivery.services.event_taxonomy import (
    EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED,
    EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED,
    EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintContextService",
    "find_wait_cycles",
    "matches_wait_pattern",
]

_COMPONENT = "blueprint_context"

# 单条 content 序列化上界：超限截断并置 {"_truncated": True}，防单条巨 JSON 撑爆总线（T-113-03）
_MAX_CONTENT_BYTES = 32768
# read_entries 的硬上界（调用方传再大也夹紧，防无界拉取吃满读取预算）
_MAX_READ_LIMIT = 200
_DEFAULT_READ_LIMIT = 50
# 唯一约束兜底重试次数（正常路径锁父行已串行化，不应触发）
_SEQ_RETRY_ATTEMPTS = 2
# waiter 条目 key 前缀（CONTEXT 锁定 dependency:{from}->{to}）
_WAITER_KEY_PREFIX = "dependency:"
# BlueprintThread.return_stage 的 max_length（service 内已截断，这里对齐避免超长传参）
_MAX_RETURN_STAGE_CHARS = 16


def _redact_json(value: Any) -> Any:
    """JSON 递归叶子脱敏（本相位自建：``common.logging`` 只有字符串版，无 JSON 递归版）。

    对 ``dict`` 的**键与值**、``list`` / ``tuple`` 的每个元素递归；字符串叶子逐个过
    ``redact_secrets_in_text``；``int`` / ``float`` / ``bool`` / ``None`` 原样返回
    （结构与非字符串叶子必须保真——脱敏不得让 JSON 塌成字符串）。

    单点调用失败 **fail-closed**：回落**空串**而不是原文（脱敏是安全边界，宁可丢内容
    也不泄漏），并记 warning 让失败可见。
    """
    if isinstance(value, str):
        try:
            return redact_secrets_in_text(value)
        except Exception as exc:  # noqa: BLE001 — fail-closed：脱敏失败回落空串，不回落原文
            logger.warning(
                "blueprint_context_redact_failed",
                category="sampling",
                component=_COMPONENT,
                error_kind=type(exc).__name__,
            )
            return ""
    if isinstance(value, dict):
        return {
            (_redact_json(k) if isinstance(k, str) else k): _redact_json(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_json(item) for item in value]
    return value


def _truncate_content(content: dict) -> dict:
    """content 序列化超 ``_MAX_CONTENT_BYTES`` 时丢正文、只留截断标记（T-113-03）。"""
    try:
        size = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    except Exception:  # noqa: BLE001 — 不可序列化的 content 一律按超限处理
        return {"_truncated": True, "_reason": "unserializable"}
    if size <= _MAX_CONTENT_BYTES:
        return content
    return {"_truncated": True, "_original_bytes": size}


def matches_wait_pattern(key: str, pattern: str) -> bool:
    """waiter 的 ``wait_key_pattern`` 是否匹配某条目 ``key``（纯函数，零 DB）。

    极简语义（够用即止，不引入正则用户输入面）：

    - ``*`` 结尾 → 前缀匹配（``repo:B.*`` 匹配 ``repo:B.api_surface``）；
    - 单个 ``*`` → 匹配任意 key；
    - 其余 → 精确相等。
    """
    key = str(key or "")
    pattern = str(pattern or "")
    if not pattern:
        return False
    if pattern == "*":
        return bool(key)
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return key == pattern


def find_wait_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """在「谁等谁」有向图上找环（纯函数，零 DB，便于单测）。

    ``edges`` 形如 ``{from_repo: {to_repo, …}}``。返回环上节点序列的清单（含自环）；
    同一个环只返回一次（按规范化后的节点集合去重）。DFS + 递归栈回溯取环体。
    """
    cycles: list[list[str]] = []
    seen_signatures: set[frozenset[str]] = set()
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def _visit(node: str) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(edges.get(node, set())):
            if nxt in on_stack:
                cycle = stack[stack.index(nxt) :]
                signature = frozenset(cycle)
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    cycles.append(list(cycle))
            elif nxt not in visited:
                _visit(nxt)
        stack.pop()
        on_stack.discard(node)

    for node in sorted(edges):
        if node not in visited:
            _visit(node)
    return cycles


def _parse_wait_target(pattern: str) -> str:
    """从 ``wait_key_pattern`` 解析被等待的仓 id（``repo:{id}.…`` 前缀）。

    解析不出（如 ``contract:{name}`` 类跨仓契约）返回空串 —— 该边不入环检测图，
    因为它不构成「仓 A 等仓 B」的可判定互等关系。
    """
    pattern = str(pattern or "")
    if not pattern.startswith("repo:"):
        return ""
    rest = pattern[len("repo:") :]
    for sep in (".", "*"):
        idx = rest.find(sep)
        if idx >= 0:
            rest = rest[:idx]
    return rest


class BlueprintContextService:
    """蓝图上下文总线读写 + waiter 生命周期（``BlueprintContextEntry`` 唯一 writer）。"""

    def __init__(self, *, lifecycle_service: Any = None) -> None:
        if lifecycle_service is None:
            from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

            lifecycle_service = BlueprintLifecycleService()
        self.lifecycle_service = lifecycle_service

    # ------------------------------------------------------------------
    # 条目读写（category="sampling"）
    # ------------------------------------------------------------------

    async def append_entry(
        self,
        *,
        session: Any,
        key: str,
        kind: str,
        content: dict,
        repository_id: str = "",
        produced_by: str = "system",
        project_id: Any = None,
        initiated_by_user_id: str = "system",
    ) -> BlueprintContextEntry:
        """写一条总线条目（``seq`` 由 service 锁父会话行分配，写入即对同会话所有读者可见）。

        - ``kind`` 必须 ∈ ``ContextEntryKind.values``、``key`` 非空，否则 ``ValueError``
          且 **DB 零写入**（半可信入参 fail-loud，不静默落脏行）。
        - ``content`` 入库前经 ``_redact_json`` 递归脱敏 + 超限截断。
        - ``project_id`` 可空：``ConvergenceSession`` 无 project FK，调用方知道归属时传，
          不知道就留空（distill 侧再 best-effort 反查，不伪造归属）。
        """
        started = time.monotonic()
        if kind not in ContextEntryKind.values:
            raise ValueError(
                f"非法总线条目 kind={kind!r}；合法值={sorted(ContextEntryKind.values)}"
            )
        if not str(key or "").strip():
            raise ValueError("总线条目 key 不得为空（前缀约定见模型注释）")

        safe_content = _truncate_content(_redact_json(content if isinstance(content, dict) else {}))

        entry = await self._append_entry_locked(
            session_id=session.id,
            project_id=project_id,
            key=str(key)[:200],
            kind=kind,
            content=safe_content,
            repository_id=str(repository_id or "")[:64],
            produced_by=str(produced_by or "system")[:64],
            initiated_by_user_id=str(initiated_by_user_id or "system")[:64],
        )
        logger.info(
            "blueprint_context_entry_appended",
            category="sampling",
            component=_COMPONENT,
            session_id=str(session.id),
            entry_id=str(entry.id),
            key=str(key),
            kind=kind,
            seq=entry.seq,
            repository_id=str(repository_id or ""),
            initiated_by_user_id=str(initiated_by_user_id or "system"),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        await self._emit(
            EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED,
            session,
            {
                "entry_id": str(entry.id),
                "key": str(key),
                "kind": kind,
                "seq": entry.seq,
                "repository_id": str(repository_id or ""),
                "initiated_by_user_id": str(initiated_by_user_id or "system"),
            },
        )
        return entry

    def _next_seq(self, session_id: Any) -> int:
        """会话内下一个 ``seq``（独立方法 = 可打桩接缝）。

        单独抽出来是为了让「两 writer 读到同一 ``max(seq)``」的冲突重试路径能被**确定性**
        测试覆盖（monkeypatch 本方法首次返回陈旧值即可触发 ``IntegrityError`` 兜底），
        不依赖真并发调度。
        """
        rows = BlueprintContextEntry.objects.filter(convergence_session_id=session_id)
        current = rows.aggregate(Max("seq"))["seq__max"]
        return (current or 0) + 1

    @sync_to_async
    def _append_entry_locked(
        self,
        *,
        session_id: Any,
        project_id: Any,
        key: str,
        kind: str,
        content: dict,
        repository_id: str,
        produced_by: str,
        initiated_by_user_id: str,
    ) -> BlueprintContextEntry:
        """锁父 ``ConvergenceSession`` 行分配 ``seq`` 并落行（唯一约束冲突有界重试）。

        不锁子表：``select_for_update()`` 对空结果集不产生可靠 gap lock（MySQL/PG 行为
        不一），锁父行是确定的串行点。``IntegrityError`` 是唯一约束**兜底**路径，正常
        不触发；重试时重新读 ``max(seq)``，故不会重复占用同一号。
        """
        last_error: IntegrityError | None = None
        for attempt in range(_SEQ_RETRY_ATTEMPTS + 1):
            try:
                with transaction.atomic():
                    ConvergenceSession.objects.select_for_update().get(pk=session_id)
                    return BlueprintContextEntry.objects.create(
                        convergence_session_id=session_id,
                        project_id=project_id,
                        key=key,
                        kind=kind,
                        content=content,
                        repository_id=repository_id,
                        produced_by=produced_by,
                        seq=self._next_seq(session_id),
                        status=ContextEntryStatus.ACTIVE,
                        initiated_by_user_id=initiated_by_user_id,
                    )
            except IntegrityError as exc:
                last_error = exc
                logger.warning(
                    "blueprint_context_seq_conflict_retry",
                    category="sampling",
                    component=_COMPONENT,
                    session_id=str(session_id),
                    kind=kind,
                    attempt=attempt + 1,
                )
        raise last_error if last_error is not None else RuntimeError("seq 分配失败")

    async def read_entries(
        self,
        *,
        session: Any,
        since_seq: int = 0,
        key_prefix: str = "",
        kind: str = "",
        repository_id: str = "",
        status: str = ContextEntryStatus.ACTIVE,
        limit: int = _DEFAULT_READ_LIMIT,
    ) -> list[dict]:
        """增量拉取本会话条目（``seq > since_seq``，可叠加前缀/种类/仓/状态过滤）。

        **恒返回 list**：无条目返回 ``[]``，绝不抛 —— 容器侧轮询靠这条保证不会因空总线
        进入错误分支。``limit`` 被 ``_MAX_READ_LIMIT`` 硬夹紧。
        """
        started = time.monotonic()
        rows = await self._read_entries_sync(
            session_id=session.id,
            since_seq=max(int(since_seq or 0), 0),
            key_prefix=str(key_prefix or ""),
            kind=str(kind or ""),
            repository_id=str(repository_id or ""),
            status=str(status or ""),
            limit=min(max(int(limit or _DEFAULT_READ_LIMIT), 1), _MAX_READ_LIMIT),
        )
        logger.info(
            "blueprint_context_entries_read",
            category="sampling",
            component=_COMPONENT,
            session_id=str(session.id),
            since_seq=max(int(since_seq or 0), 0),
            count=len(rows),
            filtered_by_key_prefix=bool(key_prefix),
            filtered_by_kind=bool(kind),
            filtered_by_repository=bool(repository_id),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return rows

    @sync_to_async
    def _read_entries_sync(
        self,
        *,
        session_id: Any,
        since_seq: int,
        key_prefix: str,
        kind: str,
        repository_id: str,
        status: str,
        limit: int,
    ) -> list[dict]:
        """查询 + 归一成 JSON 可序列化 dict（``id`` / ``created_at`` 转 str）。"""
        queryset = BlueprintContextEntry.objects.filter(
            convergence_session_id=session_id, seq__gt=since_seq
        )
        if key_prefix:
            queryset = queryset.filter(key__startswith=key_prefix)
        if kind:
            queryset = queryset.filter(kind=kind)
        if repository_id:
            queryset = queryset.filter(repository_id=repository_id)
        if status:
            queryset = queryset.filter(status=status)
        rows = queryset.order_by("seq").values(
            "id",
            "key",
            "kind",
            "repository_id",
            "content",
            "produced_by",
            "seq",
            "status",
            "created_at",
        )[:limit]
        return [
            {
                **row,
                "id": str(row["id"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # waiter 生命周期（category="caller"）
    # ------------------------------------------------------------------

    async def register_waiter(
        self,
        *,
        session: Any,
        from_repository_id: str,
        wait_key_pattern: str,
        partial_plan_id: str = "",
        reason: str = "",
        artifact: Any = None,
        initiated_by_user_id: str = "system",
    ) -> dict:
        """登记一条依赖等待声明，并**同步做互等环检测**（不靠超时兜底，T-113-04）。

        命中含 ``from_repository_id`` 的环 → 立刻经 ``BlueprintLifecycleService.open_thread``
        开一条 ``ai_clarification`` 阻塞线程抛用户裁决，并把本条 waiter 置 ``superseded``
        （已交人裁决，不再等）。

        返回**形状恒定**的 dict（下游无需判空分支）：
        ``{"entry_id": str, "cycle_detected": bool, "cycle": [[repo, …], …], "thread_id": str}``。
        """
        entry = await self.append_entry(
            session=session,
            key=f"{_WAITER_KEY_PREFIX}{from_repository_id}->{wait_key_pattern}",
            kind=ContextEntryKind.DEPENDENCY_CLAIM,
            content={
                "from_repository_id": str(from_repository_id or ""),
                "wait_key_pattern": str(wait_key_pattern or ""),
                "partial_plan_id": str(partial_plan_id or ""),
                "reason": str(reason or ""),
            },
            repository_id=str(from_repository_id or ""),
            produced_by=str(from_repository_id or "system"),
            initiated_by_user_id=initiated_by_user_id,
        )

        cycles = await self.adetect_wait_cycles(session)
        involved = [c for c in cycles if str(from_repository_id) in c]
        thread_id = ""
        if involved:
            thread_id = await self._open_cycle_clarification(
                session=session,
                artifact=artifact,
                cycles=involved,
                initiated_by_user_id=initiated_by_user_id,
            )
            await self._supersede_entries(entry_ids=[entry.id])

        logger.info(
            "blueprint_context_waiter_registered",
            category="caller",
            component=_COMPONENT,
            session_id=str(session.id),
            entry_id=str(entry.id),
            from_repository_id=str(from_repository_id or ""),
            to_key=str(wait_key_pattern or ""),
            cycle_detected=bool(involved),
            thread_id=thread_id,
            initiated_by_user_id=str(initiated_by_user_id or "system"),
        )
        await self._emit(
            EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED,
            session,
            {
                "entry_id": str(entry.id),
                "from_repository_id": str(from_repository_id or ""),
                "to_key": str(wait_key_pattern or ""),
                "cycle_detected": bool(involved),
                "thread_id": thread_id,
                "initiated_by_user_id": str(initiated_by_user_id or "system"),
            },
        )
        return {
            "entry_id": str(entry.id),
            "cycle_detected": bool(involved),
            "cycle": involved,
            "thread_id": thread_id,
        }

    async def adetect_wait_cycles(self, session: Any) -> list[list[str]]:
        """读本会话全部 active ``dependency_claim`` 行 → 建有向图 → 找环。

        ``to_repo`` 从 ``wait_key_pattern`` 的 ``repo:{id}.`` 前缀解析；解析不出（跨仓
        契约类 key）的边不入图 —— 它不构成可判定的「仓等仓」关系。
        """
        claims = await self._active_claims(session_id=session.id)
        edges: dict[str, set[str]] = {}
        for claim in claims:
            content = claim.get("content") or {}
            source = str(content.get("from_repository_id") or claim.get("repository_id") or "")
            target = _parse_wait_target(str(content.get("wait_key_pattern") or ""))
            if not source or not target:
                continue
            edges.setdefault(source, set()).add(target)
        return find_wait_cycles(edges)

    @sync_to_async
    def _active_claims(self, *, session_id: Any) -> list[dict]:
        """本会话 active waiter 行（只取环检测与匹配需要的列）。"""
        return list(
            BlueprintContextEntry.objects.filter(
                convergence_session_id=session_id,
                kind=ContextEntryKind.DEPENDENCY_CLAIM,
                status=ContextEntryStatus.ACTIVE,
            )
            .order_by("seq")
            .values("id", "repository_id", "content", "seq")
        )

    async def satisfy_waiters(
        self,
        *,
        session: Any,
        key: str,
        repository_id: str = "",
        initiated_by_user_id: str = "system",
    ) -> list[str]:
        """某 key 就绪后满足匹配的 waiter，返回**待重派的仓 id 清单**（去重保序）。

        判定与置 ``superseded`` 在**同一事务**内（分两个事务会重复重派、烧容器额度，
        T-113-05）。**本方法不 dispatch** —— 重派由调用方（113-04）负责，service 只管
        数据与判定，故二次调用同 key 恒返回 ``[]``（幂等）。
        """
        started = time.monotonic()
        repository_ids = await self._satisfy_waiters_locked(
            session_id=session.id, key=str(key or "")
        )
        logger.info(
            "blueprint_context_waiters_satisfied",
            category="caller",
            component=_COMPONENT,
            session_id=str(session.id),
            key=str(key or ""),
            repository_id=str(repository_id or ""),
            satisfied_count=len(repository_ids),
            initiated_by_user_id=str(initiated_by_user_id or "system"),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        await self._emit(
            EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED,
            session,
            {
                "key": str(key or ""),
                "satisfied_count": len(repository_ids),
                "redispatch_repository_ids": repository_ids,
                "reason": "key_available",
                "initiated_by_user_id": str(initiated_by_user_id or "system"),
            },
        )
        return repository_ids

    @sync_to_async
    def _satisfy_waiters_locked(self, *, session_id: Any, key: str) -> list[str]:
        """同事务内「逐行判匹配 + 置 superseded」（``.update()`` 绕过 auto_now，显式带 updated_at）。"""
        with transaction.atomic():
            claims = list(
                BlueprintContextEntry.objects.select_for_update()
                .filter(
                    convergence_session_id=session_id,
                    kind=ContextEntryKind.DEPENDENCY_CLAIM,
                    status=ContextEntryStatus.ACTIVE,
                )
                .order_by("seq")
                .values("id", "repository_id", "content")
            )
            matched_ids: list[Any] = []
            repository_ids: list[str] = []
            for claim in claims:
                content = claim.get("content") or {}
                pattern = str(content.get("wait_key_pattern") or "")
                if not matches_wait_pattern(key, pattern):
                    continue
                matched_ids.append(claim["id"])
                source = str(content.get("from_repository_id") or claim.get("repository_id") or "")
                if source and source not in repository_ids:
                    repository_ids.append(source)
            if matched_ids:
                BlueprintContextEntry.objects.filter(id__in=matched_ids).update(
                    status=ContextEntryStatus.SUPERSEDED, updated_at=timezone.now()
                )
            return repository_ids

    async def expire_waiters(
        self,
        *,
        session: Any,
        max_age_seconds: int,
        initiated_by_user_id: str = "system",
    ) -> list[str]:
        """清理超龄 waiter（置 ``superseded``），返回被清理的仓 id 清单。

        **不新起定时任务** —— 由 113-04 挂在 barrier 续驱路径上调用（CONTEXT 锁定）。
        """
        started = time.monotonic()
        cutoff = timezone.now() - timedelta(seconds=max(int(max_age_seconds or 0), 0))
        repository_ids = await self._expire_waiters_locked(session_id=session.id, cutoff=cutoff)
        logger.info(
            "blueprint_context_waiters_expired",
            category="caller",
            component=_COMPONENT,
            session_id=str(session.id),
            max_age_seconds=int(max_age_seconds or 0),
            satisfied_count=len(repository_ids),
            initiated_by_user_id=str(initiated_by_user_id or "system"),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        await self._emit(
            EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED,
            session,
            {
                "key": "",
                "satisfied_count": len(repository_ids),
                "redispatch_repository_ids": repository_ids,
                "reason": "expired",
                "initiated_by_user_id": str(initiated_by_user_id or "system"),
            },
        )
        return repository_ids

    @sync_to_async
    def _expire_waiters_locked(self, *, session_id: Any, cutoff: Any) -> list[str]:
        """同事务内取超龄 active waiter 并置 superseded（幂等：二次调用返回空清单）。"""
        with transaction.atomic():
            claims = list(
                BlueprintContextEntry.objects.select_for_update()
                .filter(
                    convergence_session_id=session_id,
                    kind=ContextEntryKind.DEPENDENCY_CLAIM,
                    status=ContextEntryStatus.ACTIVE,
                    created_at__lt=cutoff,
                )
                .order_by("seq")
                .values("id", "repository_id", "content")
            )
            repository_ids: list[str] = []
            for claim in claims:
                content = claim.get("content") or {}
                source = str(content.get("from_repository_id") or claim.get("repository_id") or "")
                if source and source not in repository_ids:
                    repository_ids.append(source)
            if claims:
                BlueprintContextEntry.objects.filter(id__in=[c["id"] for c in claims]).update(
                    status=ContextEntryStatus.SUPERSEDED, updated_at=timezone.now()
                )
            return repository_ids

    # ------------------------------------------------------------------
    # 内部：环澄清线程 / 置位 / 事件
    # ------------------------------------------------------------------

    async def _open_cycle_clarification(
        self,
        *,
        session: Any,
        artifact: Any,
        cycles: list[list[str]],
        initiated_by_user_id: str,
    ) -> str:
        """互等环命中 → 开 blocking 澄清线程交人裁决；解析不到 artifact 则只告警不静默失败。

        ``question`` **只含仓 id 与 key 模式**（无 content 正文）。``return_stage`` 必填
        （B3）：``BlueprintThread.return_stage`` 是澄清恢复目标的持久承载，漏传会让阶段
        2/3 的恢复退回阶段 1；取 ``session.current_stage`` 当时值，不硬编码。
        """
        if artifact is None:
            artifact = await self._resolve_artifact(session)
        if artifact is None:
            logger.warning(
                "blueprint_context_cycle_without_artifact",
                category="caller",
                component=_COMPONENT,
                session_id=str(session.id),
                cycle_count=len(cycles),
            )
            return ""
        chains = "；".join(" → ".join([*cycle, cycle[0]]) for cycle in cycles)
        question = (
            "检测到跨仓互等环，编排已停止等待并交由你裁决："
            f"{chains}。请指定先由哪个仓给出接口契约（或确认拆分/合并该依赖）。"
        )
        try:
            thread = await self.lifecycle_service.open_thread(
                artifact,
                kind=ThreadKind.AI_CLARIFICATION,
                blocking=True,
                question=question,
                initiated_by_user_id=str(initiated_by_user_id or "system"),
                return_stage=str(getattr(session, "current_stage", "") or "")[
                    :_MAX_RETURN_STAGE_CHARS
                ],
            )
        except Exception as exc:  # noqa: BLE001 — 开线程失败不得吞掉环的存在（返回值仍标 cycle）
            logger.warning(
                "blueprint_context_cycle_thread_failed",
                category="caller",
                component=_COMPONENT,
                session_id=str(session.id),
                error=redact_secrets_in_text(str(exc))[:500],
            )
            return ""
        return str(thread.id)

    @sync_to_async
    def _resolve_artifact(self, session: Any) -> Any:
        """会话 → 当前蓝图 Artifact（经 ``current_artifact_version``；无则 None）。"""
        version_id = getattr(session, "current_artifact_version_id", None)
        if not version_id:
            return None
        from delivery.models import ArtifactVersion

        row = ArtifactVersion.objects.filter(id=version_id).select_related("artifact").first()
        return row.artifact if row is not None else None

    @sync_to_async
    def _supersede_entries(self, *, entry_ids: list[Any]) -> int:
        """把指定条目置 ``superseded``（``.update()`` 绕过 auto_now，显式带 updated_at）。"""
        if not entry_ids:
            return 0
        return BlueprintContextEntry.objects.filter(id__in=entry_ids).update(
            status=ContextEntryStatus.SUPERSEDED, updated_at=timezone.now()
        )

    async def _emit(self, event: str, session: Any, payload: dict) -> None:
        """``ConvergenceSessionEvent`` 留痕（best-effort，失败吞掉绝不阻断总线主链）。"""
        if session is None:
            return
        from delivery.services.convergence_session_service import ConvergenceSessionService

        try:
            await ConvergenceSessionService().aemit_event(event, session, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort：事件持久化失败不反噬业务
            logger.warning(
                "blueprint_context_event_persist_failed",
                category="sampling",
                component=_COMPONENT,
                event_name=event,
                error=redact_secrets_in_text(str(exc))[:500],
            )
