"""编排方案版本 → chat CodingPlan 投影的映射与幂等断言（Phase 109 · SPINE-01）。

分组（``-k`` 选择器）：

- ``mapping``：§7 → CodingPlan 四字段的纯映射（含 ``create → add`` 穷举与 fail-safe）
- ``conversation`` / ``idempotent`` / ``concurrent`` / ``new_version_keeps_old`` /
  ``traceability``：投影 service 的行为断言（Task 2 追加）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from chat.models import CodingPlan, CodingPlanProvenance, Conversation
from chat.plan_projection_service import (
    _ACTION_TO_CHANGE_TYPE,
    PlanProjectionError,
    PlanProjectionService,
    map_merged_plan_to_coding_plan,
)
from delivery.models import (
    Artifact,
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    WorkItem,
    WorkItemOrigin,
)
from projects.models import Space

User = get_user_model()

# ============================================================================
# Helpers
# ============================================================================


def _task(
    *,
    repository_id: str,
    files: Any = None,
    name: str = "任务",
    task_id: str = "t1",
) -> dict[str, Any]:
    """构造一条 §7 ``execution_plan[]`` task（只填映射关心的键）。"""
    return {
        "id": task_id,
        "name": name,
        "repository_id": repository_id,
        "repository_name": f"repo-{repository_id}",
        "branch_strategy": "feature",
        "coding_instruction": f"实现 {name}",
        "files": [] if files is None else files,
    }


def _content(*tasks: dict[str, Any], title: str = "跨仓改造方案") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "把 A 仓的接口改造后同步 B 仓调用方。",
        "execution_plan": list(tasks),
        "compat_risks": ["调用方需同步升级"],
    }


# ============================================================================
# mapping —— §7 → CodingPlan 四字段
# ============================================================================


def test_mapping_returns_exactly_four_keys() -> None:
    payload = map_merged_plan_to_coding_plan(_content(_task(repository_id="r1")))
    assert set(payload) == {
        "title",
        "tech_plan",
        "affected_files",
        "recommended_repository_ids",
    }
    assert payload["title"] == "跨仓改造方案"
    # tech_plan 由唯一渲染器 render_merged_plan_markdown 产出，非空且含标题。
    assert "跨仓改造方案" in payload["tech_plan"]


@pytest.mark.parametrize(
    ("action", "expected_change_type"),
    [
        ("create", "add"),
        ("modify", "modify"),
        ("delete", "delete"),
    ],
)
def test_mapping_action_to_change_type_enum_exhaustive(
    action: str, expected_change_type: str
) -> None:
    """三个已知 action 逐条穷举。

    每条**同时**断言 ``file_path`` 与 ``change_type`` —— 只断言 file_path 正是
    ``create → add`` 静默漂移（漏转换不崩、只静默显示成 create）的典型警示信号。
    """
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                files=[{"path": "src/api.py", "action": action}],
            )
        )
    )
    assert payload["affected_files"] == [
        {"file_path": "src/api.py", "change_type": expected_change_type}
    ]
    entry = payload["affected_files"][0]
    assert entry["file_path"] == "src/api.py"
    assert entry["change_type"] == expected_change_type


def test_mapping_action_table_is_exactly_create_add() -> None:
    """转换表本体的形状断言（防后人改表时把 create 悄悄映成 create）。"""
    assert _ACTION_TO_CHANGE_TYPE == {
        "create": "add",
        "modify": "modify",
        "delete": "delete",
    }


@pytest.mark.parametrize(
    "file_entry",
    [
        {"path": "src/renamed.py", "action": "rename"},  # 未知 action
        {"path": "src/renamed.py"},  # 缺 action 键
        {"path": "src/renamed.py", "action": None},  # action 为 None
    ],
)
def test_mapping_unknown_or_missing_action_falls_back_to_modify(
    file_entry: dict[str, Any],
) -> None:
    payload = map_merged_plan_to_coding_plan(
        _content(_task(repository_id="r1", files=[file_entry]))
    )
    assert payload["affected_files"] == [{"file_path": "src/renamed.py", "change_type": "modify"}]
    assert payload["affected_files"][0]["change_type"] == "modify"


def test_mapping_aggregates_files_across_repositories() -> None:
    """多仓聚合：两个 task 分属两仓 → 文件全收、repo id 按 task 顺序去重保序。"""
    repo_a, repo_b = str(uuid.uuid4()), str(uuid.uuid4())
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id=repo_a,
                task_id="t1",
                files=[
                    {"path": "a/service.py", "action": "modify"},
                    {"path": "a/new_module.py", "action": "create"},
                ],
            ),
            _task(
                repository_id=repo_b,
                task_id="t2",
                files=[{"path": "b/caller.ts", "action": "modify"}],
            ),
            # 第三个 task 回到 repo_a → repo id 不重复出现。
            _task(
                repository_id=repo_a,
                task_id="t3",
                files=[{"path": "a/legacy.py", "action": "delete"}],
            ),
        )
    )
    assert payload["affected_files"] == [
        {"file_path": "a/service.py", "change_type": "modify"},
        {"file_path": "a/new_module.py", "change_type": "add"},
        {"file_path": "b/caller.ts", "change_type": "modify"},
        {"file_path": "a/legacy.py", "change_type": "delete"},
    ]
    # 保序即保 release_order 意图：repo_a 先出现。
    assert payload["recommended_repository_ids"] == [repo_a, repo_b]


def test_mapping_dedupes_repeated_path_action_and_keeps_order() -> None:
    """同一 (path, action) 在两个 task 重复 → 只留一条且保序。"""
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                task_id="t1",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "r1/only.py", "action": "create"},
                ],
            ),
            _task(
                repository_id="r2",
                task_id="t2",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "r2/only.py", "action": "modify"},
                ],
            ),
        )
    )
    paths = [f["file_path"] for f in payload["affected_files"]]
    assert paths == ["shared/util.py", "r1/only.py", "r2/only.py"]
    assert paths.count("shared/util.py") == 1
    # 同 path 不同 action 视为两条（change_type 不同，语义不同）。
    payload2 = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "shared/util.py", "action": "delete"},
                ],
            )
        )
    )
    assert payload2["affected_files"] == [
        {"file_path": "shared/util.py", "change_type": "modify"},
        {"file_path": "shared/util.py", "change_type": "delete"},
    ]


@pytest.mark.parametrize(
    "hostile_content",
    [
        None,
        "不是 dict 而是字符串",
        {"title": "无 execution_plan 键"},
        {"title": "execution_plan 非 list", "execution_plan": {"oops": 1}},
        {"execution_plan": ["task 不是 dict", 42, None]},
        {"execution_plan": [{"repository_id": "r1", "files": "files 非 list"}]},
        {"execution_plan": [{"repository_id": "r1", "files": ["项非 dict", 7]}]},
        {"execution_plan": [{"repository_id": "r1", "files": [{"path": "", "action": "create"}]}]},
        {"execution_plan": [{"repository_id": "", "files": [{"action": "create"}]}]},
    ],
)
def test_mapping_fail_safe_on_semi_trusted_content(hostile_content: Any) -> None:
    """半可信输入恒不抛异常，且返回结构合法（LLM 产物防御，T-109-03-04）。"""
    payload = map_merged_plan_to_coding_plan(hostile_content)
    assert set(payload) == {
        "title",
        "tech_plan",
        "affected_files",
        "recommended_repository_ids",
    }
    assert isinstance(payload["title"], str)
    assert isinstance(payload["tech_plan"], str)
    # 文件侧一律降级为空 list（没有任何一条能凑出合法 file_path）。
    assert payload["affected_files"] == []
    # repository_id 是独立的一支：``files`` 非法不该连带丢掉合法的 repo id
    # （多仓 fan-out 的目标仓仍可用），只断言结构合法。
    assert isinstance(payload["recommended_repository_ids"], list)
    assert all(isinstance(r, str) for r in payload["recommended_repository_ids"])


@pytest.mark.parametrize("hostile_content", [None, 42, "字符串", [], {}])
def test_mapping_fail_safe_top_level_non_dict_yields_empty_lists(
    hostile_content: Any,
) -> None:
    """顶层完全不可用时两个 list 都为空、``tech_plan`` 为空串（不抛）。"""
    payload = map_merged_plan_to_coding_plan(hostile_content)
    assert payload["title"] == ""
    assert payload["tech_plan"] == ""
    assert payload["affected_files"] == []
    assert payload["recommended_repository_ids"] == []


# ============================================================================
# 投影 service —— 造数 helper
# ============================================================================


def _make_user(prefix: str = "projection_owner"):
    return User.objects.create_user(
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@projection.local",
        password="testpass123",
    )


def _make_conversation(user: Any = None) -> Conversation:
    suffix = uuid.uuid4().hex[:8]
    space = Space.objects.create(
        name=f"投影测试空间-{suffix}",
        feishu_project_key=f"projection-{suffix}",
    )
    return Conversation.objects.create(
        space=space,
        title="编排会话对应的 chat 对话",
        created_by=user or _make_user(),
    )


def _make_work_item() -> WorkItem:
    return WorkItem.objects.create(
        feishu_project_key=f"pk-{uuid.uuid4().hex[:8]}",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 10_000_000),
        origin=WorkItemOrigin.MANUAL,
        title="把 A 仓接口改造后同步 B 仓调用方",
    )


def _make_session(conversation: Conversation | None) -> ConvergenceSession:
    """编排会话；``conversation is None`` 即 workflow / MCP 入口（D-3 的拒绝分支）。"""
    return ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=(
            ConvergenceSessionEntrypoint.CHAT
            if conversation is not None
            else ConvergenceSessionEntrypoint.WORKFLOW
        ),
        current_stage="merge",
        status=ConvergenceSessionStatus.DONE,
        conversation_id=conversation.id if conversation is not None else None,
    )


def _make_artifact_version(
    *,
    session: ConvergenceSession | None = None,
    content: dict[str, Any] | None = None,
    artifact: Artifact | None = None,
    version_no: int = 1,
    work_item: WorkItem | None = None,
) -> ArtifactVersion:
    """WorkItem → Artifact → ArtifactVersion 一条完整来源链（追溯两跳的造数侧）。"""
    if artifact is None:
        artifact = Artifact.objects.create(
            artifact_type="technical_plan",
            work_item=work_item or _make_work_item(),
            title="跨仓改造方案",
        )
    version = ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=version_no,
        content=content
        if content is not None
        else _content(
            _task(
                repository_id=str(uuid.uuid4()),
                files=[{"path": "src/api.py", "action": "create"}],
            )
        ),
        produced_by_session_id=str(session.id) if session is not None else "",
    )
    return version


def _project(artifact_version_id: Any, *, initiated_by_user_id: str = "system"):
    return async_to_sync(PlanProjectionService().aproject)(
        artifact_version_id=str(artifact_version_id),
        initiated_by_user_id=initiated_by_user_id,
    )


# ============================================================================
# conversation —— 只走 chat 入口（裁决 D-3）
# ============================================================================


@pytest.mark.django_db
def test_conversation_is_resolved_from_convergence_session() -> None:
    """有 ``conversation_id`` 的编排会话 → 投影落在该 conversation 下（不新建会话）。"""
    user = _make_user()
    conversation = _make_conversation(user)
    version = _make_artifact_version(session=_make_session(conversation))
    before = Conversation.objects.count()

    plan, created = _project(version.id, initiated_by_user_id=str(user.id))

    assert created is True
    assert plan.conversation_id == conversation.id
    assert plan.provenance == CodingPlanProvenance.ORCHESTRATED
    assert str(plan.source_artifact_version_id) == str(version.id)
    # 复用既有会话，不凭空建第二个。
    assert Conversation.objects.count() == before


@pytest.mark.django_db
def test_conversation_absent_raises_requires_chat_entrypoint() -> None:
    """workflow 入口（``conversation_id`` 为空）→ 稳定机器码拒绝，且**不建合成会话**。"""
    version = _make_artifact_version(session=_make_session(None))
    conversations_before = Conversation.objects.count()

    with pytest.raises(PlanProjectionError) as exc_info:
        _project(version.id)

    assert exc_info.value.code == "projection_requires_chat_entrypoint"
    # D-3 边界：不猜 space、不建合成会话、不留半成品 plan。
    assert Conversation.objects.count() == conversations_before
    assert CodingPlan.objects.filter(source_artifact_version_id=version.id).count() == 0


@pytest.mark.django_db
def test_conversation_link_broken_raises_requires_chat_entrypoint() -> None:
    """``produced_by_session_id`` 为空 / 指向不存在的会话 → 同一机器码（链断即拒）。"""
    orphan = _make_artifact_version(session=None)
    with pytest.raises(PlanProjectionError) as exc_info:
        _project(orphan.id)
    assert exc_info.value.code == "projection_requires_chat_entrypoint"

    dangling = _make_artifact_version(session=None)
    ArtifactVersion.objects.filter(id=dangling.id).update(produced_by_session_id=str(uuid.uuid4()))
    with pytest.raises(PlanProjectionError) as exc_info:
        _project(dangling.id)
    assert exc_info.value.code == "projection_requires_chat_entrypoint"


@pytest.mark.django_db
def test_conversation_lookup_of_unknown_version_raises_not_found() -> None:
    """来源方案版本不存在 → ``artifact_version_not_found``（fail-closed，无来源不投影）。"""
    with pytest.raises(PlanProjectionError) as exc_info:
        _project(uuid.uuid4())
    assert exc_info.value.code == "artifact_version_not_found"


# ============================================================================
# idempotent —— 同一版本重复投影只产一行
# ============================================================================


@pytest.mark.django_db
def test_idempotent_projection_returns_same_plan_and_single_row() -> None:
    version = _make_artifact_version(session=_make_session(_make_conversation()))

    first, first_created = _project(version.id)
    second, second_created = _project(version.id)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert CodingPlan.objects.filter(source_artifact_version_id=version.id).count() == 1


@pytest.mark.django_db
def test_idempotent_projection_does_not_rewrite_existing_row() -> None:
    """第二次投影是**读**不是写：即便 content 被改，已投影的 plan 正文不被改写。"""
    session = _make_session(_make_conversation())
    version = _make_artifact_version(session=session)
    plan, _ = _project(version.id)
    original_tech_plan = plan.tech_plan

    ArtifactVersion.objects.filter(id=version.id).update(
        content=_content(
            _task(repository_id=str(uuid.uuid4()), files=[{"path": "x.py", "action": "delete"}]),
            title="被篡改的标题",
        )
    )
    again, created = _project(version.id)

    assert created is False
    assert again.id == plan.id
    assert again.tech_plan == original_tech_plan
    assert "被篡改的标题" not in again.tech_plan


# ============================================================================
# concurrent —— 并发只留一行且不向调用方抛异常
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_concurrent_projection_yields_single_row_without_raising() -> None:
    """``asyncio.gather`` 并发投影同一版本：两路都拿到同一条 plan，DB 只 1 行。"""
    version = _make_artifact_version(session=_make_session(_make_conversation()))

    async def _both() -> list[Any]:
        service = PlanProjectionService()
        return await asyncio.gather(
            service.aproject(artifact_version_id=str(version.id)),
            service.aproject(artifact_version_id=str(version.id)),
        )

    results = async_to_sync(_both)()

    plan_ids = {str(plan.id) for plan, _created in results}
    assert len(plan_ids) == 1
    # 恰好一路是新建（另一路必须表现为幂等命中，而不是第二行）。
    assert sum(1 for _plan, created in results if created) == 1
    assert CodingPlan.objects.filter(source_artifact_version_id=version.id).count() == 1


@pytest.mark.django_db
def test_concurrent_integrity_error_degrades_to_idempotent_hit() -> None:
    """并发落败方分支：``aget_or_create`` 抛 ``IntegrityError`` → 重 ``aget`` 而非 500。

    幂等三件套的第 ③ 件（``except IntegrityError``）在真实并发下才会被 DB 唯一约束
    触发，用 patch 把该分支变成可确定性覆盖的路径 —— 没有它，落败方会把 500 抛给用户。
    """
    version = _make_artifact_version(session=_make_session(_make_conversation()))
    existing, created = _project(version.id)
    assert created is True

    with patch.object(
        CodingPlan.objects,
        "aget_or_create",
        side_effect=IntegrityError(
            "UNIQUE constraint failed: uniq_codingplan_source_artifact_version"
        ),
    ):
        plan, created_again = _project(version.id)

    assert created_again is False
    assert plan.id == existing.id
    assert CodingPlan.objects.filter(source_artifact_version_id=version.id).count() == 1


# ============================================================================
# new_version_keeps_old —— 方案更新后旧投影保留（历史可查）
# ============================================================================


@pytest.mark.django_db
def test_new_version_keeps_old_projection_intact() -> None:
    conversation = _make_conversation()
    session = _make_session(conversation)
    work_item = _make_work_item()
    v1 = _make_artifact_version(
        session=session,
        work_item=work_item,
        version_no=1,
        content=_content(
            _task(repository_id="r1", files=[{"path": "v1.py", "action": "create"}]),
            title="方案 v1",
        ),
    )
    old_plan, _ = _project(v1.id)
    old_plan_id, old_tech_plan = old_plan.id, old_plan.tech_plan

    v2 = _make_artifact_version(
        session=session,
        artifact=v1.artifact,
        version_no=2,
        content=_content(
            _task(repository_id="r2", files=[{"path": "v2.py", "action": "delete"}]),
            title="方案 v2",
        ),
    )
    new_plan, new_created = _project(v2.id)

    assert new_created is True
    assert new_plan.id != old_plan_id
    assert CodingPlan.objects.filter(source_artifact_version_id__in=[v1.id, v2.id]).count() == 2

    # 旧投影未被改写 —— 历史可查是本用例存在的理由。
    old_plan.refresh_from_db()
    assert old_plan.id == old_plan_id
    assert old_plan.tech_plan == old_tech_plan
    assert "方案 v1" in old_plan.tech_plan
    assert "方案 v2" in new_plan.tech_plan


# ============================================================================
# traceability —— 两跳回到需求（不去范式化）
# ============================================================================


@pytest.mark.django_db
def test_traceability_two_hops_from_plan_to_work_item() -> None:
    """``CodingPlan.source_artifact_version_id`` → ArtifactVersion → Artifact → WorkItem。

    ``CodingPlan`` 上刻意**不**冗余写 ``work_item``（109-RESEARCH §7 追溯最小完备集），
    这条用例证明不写也追得到。
    """
    work_item = _make_work_item()
    version = _make_artifact_version(
        session=_make_session(_make_conversation()), work_item=work_item
    )
    plan, _ = _project(version.id)

    # 两跳：plan → ArtifactVersion → Artifact.work_item
    hop1 = ArtifactVersion.objects.get(id=plan.source_artifact_version_id)
    hop2 = hop1.artifact.work_item

    assert hop2 is not None
    assert hop2.id == work_item.id
    assert hop2.work_item_id == work_item.work_item_id
    assert hop2.feishu_project_key == work_item.feishu_project_key
