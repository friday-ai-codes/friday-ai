"""BlueprintContextService 行为守护（PLAN 113-01 Task 3，DESIGN §5.6）。

守九件事：

1. ⭐ **脱敏结构保真**：``content`` 里的凭证样本（``friday_pat_`` / ``Bearer sk-``）入库后
   字面量零出现，**且** JSON 结构与非字符串叶子（int / bool / 嵌套层级）逐键保真——
   不因脱敏塌成字符串（这条同时证明没走 ``dumps → 脱敏 → loads`` 的错误做法）。
2. **增量拉取**：``since_seq`` 只返回更大的 seq；``key_prefix`` / ``kind`` /
   ``repository_id`` 可叠加；空结果返回 ``[]`` 不抛；``limit`` 超上界被夹紧。
3. **环检测纯函数**：互等环 / 无环链 / 自环三例（零 DB）。
4. **register_waiter 命中环开线程**：A 等 B 后再登记 B 等 A → 第二次 ``cycle_detected``
   为真、``thread_id`` 非空，DB 里有一条 ``ai_clarification`` + ``blocking=True`` 线程且带
   ``return_stage``（B3），第二条 waiter 条目已置 ``superseded``（已交人裁决不再等）。
5. **无环时不开线程**：单向等待返回 ``cycle_detected`` 为假且 ``thread_id`` 为空串（形状恒定）。
6. ⭐ **satisfy_waiters 同事务 + 幂等**：返回待重派仓清单且该行置 ``superseded``；**再调
   一次同 key 返回 ``[]``**（判定与置位分事务会在这里重复返回，从而被逮到）。
7. **matches_wait_pattern 纯函数**：精确 / 前缀通配 / 不匹配三例。
8. **expire_waiters**：``created_at`` 回拨后被清理并返回仓 id；二次调用返回 ``[]``。
9. **非法入参 fail-loud**：非法 ``kind`` / 空 ``key`` 抛 ``ValueError`` 且 DB 零新增行；
   观测事件里不含 ``content`` 任何字符串值。

async service 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import structlog
from django.utils import timezone

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintContextEntry,
    BlueprintThread,
    ContextEntryKind,
    ContextEntryStatus,
    ConvergenceSession,
    ThreadKind,
)
from delivery.services.blueprint_context_service import (
    _MAX_READ_LIMIT,
    BlueprintContextService,
    find_wait_cycles,
    matches_wait_pattern,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

# 凭证样本：SENSITIVE_VALUE_PATTERN 要求前缀后 ≥20 字符才判定为凭证，故样本足够长
_PAT_SAMPLE = "friday_pat_abcdefghij1234567890"
_BEARER_SAMPLE = "Bearer sk-0123456789abcdefghijklmn"


# ---- 工厂 ----


async def _make_session(*, with_artifact: bool = False) -> ConvergenceSession:
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint="chat",
        current_stage="repo_plan",
    )
    if with_artifact:
        artifact = await Artifact.objects.acreate(artifact_type="technical_blueprint")
        version = await ArtifactVersion.objects.acreate(artifact=artifact, version_no=1)
        session.current_artifact_version = version
        await session.asave(update_fields=["current_artifact_version"])
    return session


# ---- 1. 脱敏结构保真 ----


async def test_content_credentials_redacted_without_breaking_json_shape() -> None:
    session = await _make_session()
    entry = await BlueprintContextService().append_entry(
        session=session,
        key="repo:a.api_surface",
        kind=ContextEntryKind.API_SURFACE,
        content={
            "raw": f"token={_PAT_SAMPLE}",
            "nested": {"list": [_BEARER_SAMPLE, 42], "ok": True, "none": None},
        },
    )

    fresh = await BlueprintContextEntry.objects.aget(id=entry.id)
    dumped = json.dumps(fresh.content, ensure_ascii=False)

    # ① 凭证字面量零出现
    assert "friday_pat_" not in dumped
    assert "sk-0123456789" not in dumped
    assert "***REDACTED***" in dumped
    # ② 结构与非字符串叶子保真（没塌成字符串、层级未变）
    assert isinstance(fresh.content, dict)
    assert set(fresh.content) == {"raw", "nested"}
    assert fresh.content["nested"]["list"][1] == 42
    assert fresh.content["nested"]["ok"] is True
    assert fresh.content["nested"]["none"] is None
    assert isinstance(fresh.content["nested"]["list"], list)


# ---- 2. 增量拉取 ----


async def test_read_entries_incremental_and_filters() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    for i in range(5):
        await service.append_entry(
            session=session,
            key=f"repo:r{i}.api_surface",
            kind=ContextEntryKind.API_SURFACE,
            content={"i": i},
            repository_id=f"r{i}",
        )
    await service.append_entry(
        session=session,
        key="contract:pay",
        kind=ContextEntryKind.CONTRACT,
        content={"c": 1},
    )

    incremental = await service.read_entries(session=session, since_seq=3)
    assert [row["seq"] for row in incremental] == [4, 5, 6]

    by_prefix = await service.read_entries(session=session, key_prefix="repo:")
    assert len(by_prefix) == 5
    assert all(row["key"].startswith("repo:") for row in by_prefix)

    by_kind = await service.read_entries(session=session, kind=ContextEntryKind.CONTRACT)
    assert [row["key"] for row in by_kind] == ["contract:pay"]

    by_repo = await service.read_entries(session=session, repository_id="r2")
    assert [row["repository_id"] for row in by_repo] == ["r2"]

    combined = await service.read_entries(
        session=session, kind=ContextEntryKind.API_SURFACE, repository_id="r4"
    )
    assert [row["seq"] for row in combined] == [5]


async def test_read_entries_empty_returns_list_and_clamps_limit() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    assert await service.read_entries(session=session) == []
    assert await service.read_entries(session=session, since_seq=999) == []
    assert await service.read_entries(session=session, key_prefix="nope:") == []

    await service.append_entry(
        session=session,
        key="repo:a.api_surface",
        kind=ContextEntryKind.FINDING,
        content={},
    )
    # 超上界被夹紧（不抛、不无界拉取）
    rows = await service.read_entries(session=session, limit=_MAX_READ_LIMIT * 10)
    assert len(rows) == 1
    assert rows[0]["id"] and isinstance(rows[0]["id"], str)
    assert rows[0]["created_at"]


# ---- 3. 环检测纯函数 ----


def test_find_wait_cycles_pure() -> None:
    assert find_wait_cycles({"A": {"B"}, "B": {"A"}})
    assert find_wait_cycles({"A": {"B"}, "B": {"C"}}) == []
    assert find_wait_cycles({"A": {"A"}}) == [["A"]]
    assert find_wait_cycles({}) == []
    three = find_wait_cycles({"A": {"B"}, "B": {"C"}, "C": {"A"}})
    assert len(three) == 1
    assert set(three[0]) == {"A", "B", "C"}


# ---- 4/5. register_waiter ----


async def test_register_waiter_without_cycle_does_not_open_thread() -> None:
    session = await _make_session(with_artifact=True)
    service = BlueprintContextService()

    result = await service.register_waiter(
        session=session,
        from_repository_id="A",
        wait_key_pattern="repo:B.api_surface",
        reason="需要 B 的下单接口契约",
    )

    assert result["cycle_detected"] is False
    assert result["cycle"] == []
    assert result["thread_id"] == ""
    assert result["entry_id"]
    assert await BlueprintThread.objects.acount() == 0

    entry = await BlueprintContextEntry.objects.aget(id=result["entry_id"])
    assert entry.kind == ContextEntryKind.DEPENDENCY_CLAIM
    assert entry.key == "dependency:A->repo:B.api_surface"
    assert entry.status == ContextEntryStatus.ACTIVE


async def test_register_waiter_cycle_opens_blocking_clarification() -> None:
    session = await _make_session(with_artifact=True)
    service = BlueprintContextService()

    await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.api_surface"
    )
    result = await service.register_waiter(
        session=session, from_repository_id="B", wait_key_pattern="repo:A.api_surface"
    )

    assert result["cycle_detected"] is True
    assert result["thread_id"]
    assert any("A" in cycle and "B" in cycle for cycle in result["cycle"])

    thread = await BlueprintThread.objects.aget(id=result["thread_id"])
    assert thread.kind == ThreadKind.AI_CLARIFICATION
    assert thread.blocking is True
    # B3：return_stage 必填（澄清恢复目标的持久承载）
    assert thread.return_stage == "repo_plan"

    # 已交人裁决 → 该 waiter 不再等
    entry = await BlueprintContextEntry.objects.aget(id=result["entry_id"])
    assert entry.status == ContextEntryStatus.SUPERSEDED


async def test_register_waiter_cycle_without_artifact_still_reports_cycle() -> None:
    """artifact 解析不到时不得静默吞掉环（返回值仍标 cycle，只是无 thread）。"""
    session = await _make_session()
    service = BlueprintContextService()

    await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.api_surface"
    )
    result = await service.register_waiter(
        session=session, from_repository_id="B", wait_key_pattern="repo:A.api_surface"
    )

    assert result["cycle_detected"] is True
    assert result["thread_id"] == ""
    assert await BlueprintThread.objects.acount() == 0


# ---- 6. satisfy_waiters ----


async def test_satisfy_waiters_supersedes_in_one_transaction_and_is_idempotent() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    registered = await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.api_surface"
    )

    first = await service.satisfy_waiters(session=session, key="repo:B.api_surface")
    assert first == ["A"]
    entry = await BlueprintContextEntry.objects.aget(id=registered["entry_id"])
    assert entry.status == ContextEntryStatus.SUPERSEDED

    # 幂等：判定与置位同事务 ⇒ 二次调用绝不重复返回（否则会重复重派烧容器额度）
    assert await service.satisfy_waiters(session=session, key="repo:B.api_surface") == []


async def test_satisfy_waiters_dedupes_and_ignores_non_matching() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.*"
    )
    await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.api_surface"
    )
    await service.register_waiter(
        session=session, from_repository_id="C", wait_key_pattern="repo:D.api_surface"
    )

    assert await service.satisfy_waiters(session=session, key="repo:B.api_surface") == ["A"]
    # C 等的是 D，未被误满足
    remaining = await service.read_entries(session=session, kind=ContextEntryKind.DEPENDENCY_CLAIM)
    assert [row["repository_id"] for row in remaining] == ["C"]


# ---- 7. matches_wait_pattern ----


def test_matches_wait_pattern_pure() -> None:
    assert matches_wait_pattern("repo:B.api_surface", "repo:B.api_surface") is True
    assert matches_wait_pattern("repo:B.api_surface", "repo:B.*") is True
    assert matches_wait_pattern("repo:B.api_surface", "repo:C.*") is False
    assert matches_wait_pattern("repo:B.api_surface", "") is False
    assert matches_wait_pattern("", "repo:B.*") is False


# ---- 8. expire_waiters ----


async def test_expire_waiters_clears_stale_claims() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    registered = await service.register_waiter(
        session=session, from_repository_id="A", wait_key_pattern="repo:B.api_surface"
    )
    # 人工回拨 created_at（auto_now_add 字段只能 update 绕过）
    await BlueprintContextEntry.objects.filter(id=registered["entry_id"]).aupdate(
        created_at=timezone.now() - timedelta(hours=2)
    )

    emitted: list[tuple[str, dict]] = []

    async def _record(event: str, _session: object, payload: dict) -> None:
        emitted.append((event, payload))

    service._emit = _record  # type: ignore[method-assign]

    expired = await service.expire_waiters(session=session, max_age_seconds=60)
    assert expired == ["A"]
    entry = await BlueprintContextEntry.objects.aget(id=registered["entry_id"])
    assert entry.status == ContextEntryStatus.SUPERSEDED
    assert await service.expire_waiters(session=session, max_age_seconds=60) == []

    # ⭐ 真清理发一条（带 reason=expired，供前端与「已对齐」区分文案）；
    # ⭐ **空清理一条都不发** —— 本方法挂在 barrier 续驱路径上、每次续驱都调，无条件发会在
    # 活动流里堆一串 `satisfied_count=0` + 空 payload 的事件，用户只能理解成埋点坏了。
    assert len(emitted) == 1, f"空清理不该发事件，实际发了 {len(emitted)} 条"
    event, payload = emitted[0]
    assert event == "blueprint.context.waiter_satisfied"
    assert payload["reason"] == "expired"
    assert payload["satisfied_count"] == 1
    assert payload["redispatch_repository_ids"] == ["A"]


# ---- 9. fail-loud 与观测 ----


@pytest.mark.parametrize(
    ("kind", "key"),
    [("bogus", "repo:a.api_surface"), (ContextEntryKind.FINDING, "  ")],
)
async def test_invalid_input_raises_and_writes_nothing(kind: str, key: str) -> None:
    session = await _make_session()

    with pytest.raises(ValueError):
        await BlueprintContextService().append_entry(
            session=session, key=key, kind=kind, content={"x": 1}
        )

    assert await BlueprintContextEntry.objects.acount() == 0


async def test_append_log_event_carries_no_content_values() -> None:
    session = await _make_session()
    secret_marker = "内部下单接口正文不得进日志"

    with structlog.testing.capture_logs() as logs:
        await BlueprintContextService().append_entry(
            session=session,
            key="repo:a.api_surface",
            kind=ContextEntryKind.API_SURFACE,
            content={"description": secret_marker, "raw": _PAT_SAMPLE},
            repository_id="a",
            initiated_by_user_id="u-1",
        )

    appended = [row for row in logs if row.get("event") == "blueprint_context_entry_appended"]
    assert len(appended) == 1
    record = appended[0]
    assert record["category"] == "sampling"
    assert record["component"] == "blueprint_context"
    assert record["initiated_by_user_id"] == "u-1"
    assert record["key"] == "repo:a.api_surface"
    assert "duration_ms" in record
    # content 任何字符串值都不得出现在事件里（正文与凭证同等对待）
    serialized = json.dumps(record, default=str, ensure_ascii=False)
    assert secret_marker not in serialized
    assert "friday_pat_" not in serialized
    assert "content" not in record


async def test_waiter_logs_use_caller_category() -> None:
    session = await _make_session()
    service = BlueprintContextService()

    with structlog.testing.capture_logs() as logs:
        await service.register_waiter(
            session=session,
            from_repository_id="A",
            wait_key_pattern="repo:B.api_surface",
            initiated_by_user_id="u-2",
        )
        await service.satisfy_waiters(
            session=session, key="repo:B.api_surface", initiated_by_user_id="u-2"
        )

    registered = next(row for row in logs if row["event"] == "blueprint_context_waiter_registered")
    satisfied = next(row for row in logs if row["event"] == "blueprint_context_waiters_satisfied")
    for record in (registered, satisfied):
        assert record["category"] == "caller"
        assert record["component"] == "blueprint_context"
        assert record["initiated_by_user_id"] == "u-2"
