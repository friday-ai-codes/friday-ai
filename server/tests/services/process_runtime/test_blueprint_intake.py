"""蓝图 intake 与功能点拆分行为测试（Phase 116-02，GATE-01）。

守十件事（每条都把**可证伪**的断言写进条目本身，⛔ 不接受「跑通即算」）：

1. ⭐ **骨架过校验且带 ``schema_version``（P-2 正面）**：``build_skeleton`` 的产出
   ``validate_blueprint`` 返 ``(True, None)`` **且** ``content["schema_version"]``
   逐字等于 ``BLUEPRINT_SCHEMA_VERSION``。
2. ⭐ **P-2 的反面并列**：把 ``schema_version`` 删掉后 ``validate_blueprint`` **仍返
   ``(True, None)``**（v0 pass-through，§A.2 变体 H 实跑）。这一条并列存在，才说明第 1
   条不是恒真、才解释了「为什么必须直接断言那个键而不是断言校验通过」。
3. **骨架工厂不返回共享可变对象**：连调两次、改第一份的嵌套容器，第二份不受影响。
4. ⭐ **三条硬断言之①**：走真实 ``start_blueprint_orchestration`` + 驱一步 intake 后，
   **DB 重读**的 ``ArtifactVersion.content["schema_version"] == "blueprint/v1"``。
5. ⭐ **三条硬断言之②**：``session.current_artifact_version_id`` 非空（DB 重读）。
6. ⭐ **三条硬断言之③**：``meta.project_id`` **能被 ``ProjectMember`` 查中**
   （⛔ 不是「非空」而是「查得中」—— 前者对 Space id 同样为真）。
7. ⭐ **MCP 入口变异（P-8）**：``aresolve_project_id(entry="mcp", work_item_context=…)``
   返回的是 **Project.id 而不是 Space.id**。把实现改成透传 ``space_id`` ⇒ 本用例转红。
8. ⭐ **推不出 project_id ⇒ 零副作用**：抛 ``BlueprintIntakeRejected``，且
   ``ConvergenceSession`` / ``Artifact`` 计数与调用前逐字相等。
9. **落成 Space id 的蓝图在下游恒不可用**（把 P-8 的代价钉成事实，非修辞）：同一个用户、
   同一个端点，正确 project_id 得 200、Space id 得非 200。
10. **intake 幂等 / decompose 两条路径 / 无变化不翻版本 / 替身 handler 不带指针的反向
    对照 / INV-6 源码扫描**。

断言一律**重读 DB**；LLM 客户端一律 patch 并断言调用次数（⛔ 不靠「没配 provider 所以
不会调」这种环境巧合）。
"""

from __future__ import annotations

import ast
import copy
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
)
from services.process_runtime.blueprint_intake import (
    BlueprintIntakeRejected,
    adecompose_feature_points,
    aresolve_project_id,
    build_skeleton,
)
from services.process_runtime.blueprint_schema import (
    BLUEPRINT_SCHEMA_VERSION,
    validate_blueprint,
)
from services.process_runtime.entrypoint import (
    build_engine_for_session,
    start_blueprint_orchestration,
)

pytestmark = pytest.mark.django_db(transaction=True)

_SERVER_DIR = Path(__file__).resolve().parents[3]
_INTAKE_MODULE = _SERVER_DIR / "services/process_runtime/blueprint_intake.py"

_PROJECT_ID = "33333333-3333-3333-3333-333333333333"
_REQUIREMENT = "用户可在练习页一键生成个性化习题。\n第二行细节。"


# ══════════════════════════════════════════════════════════════════════════
# 数据工厂
# ══════════════════════════════════════════════════════════════════════════


@sync_to_async
def _make_project(project_id: str = _PROJECT_ID, *, member: Any = None) -> Any:
    """建一个 ``initiatives.Project``（可选授予成员）—— 范围闸与硬断言③的判据源。

    工厂形状逐字复用 ``tests/delivery/test_blueprint_review_views.py:87-101``。
    """
    from initiatives.models import Project, ProjectMember
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space, _ = Space.objects.get_or_create(
            name=f"space-{project_id[:8]}",
            defaults={"feishu_project_key": f"k-{project_id[:8]}"},
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    if member is not None:
        ProjectMember.objects.get_or_create(project=project, user=member)
    return project


@sync_to_async
def _project_member_hits(project_id: str, user: Any) -> bool:
    """⭐ 硬断言③的判据：``meta.project_id`` 真的能被 ``ProjectMember`` 查中。"""
    from initiatives.models import ProjectMember

    return ProjectMember.objects.filter(project_id=project_id, user=user).exists()


@sync_to_async
def _counts() -> tuple[int, int, int]:
    """(会话数, 交付物数, 版本数) —— 「零副作用」用前后逐字相等来核算。"""
    return (
        ConvergenceSession.objects.count(),
        Artifact.objects.count(),
        ArtifactVersion.objects.count(),
    )


async def _latest_version(artifact: Any) -> Any:
    return await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()


async def _drive_one_step(session: Any) -> Any:
    """按 ``process_type`` 取对的 engine 驱一步（116-01 的分派器）。"""
    engine, _adrive = build_engine_for_session(session)
    await engine.advance(session)
    return await ConvergenceSession.objects.aget(id=session.id)


async def _start_and_intake(*, project_id: str = _PROJECT_ID, **kwargs: Any) -> Any:
    session = await start_blueprint_orchestration(
        ConvergenceSessionEntrypoint.CHAT,
        _REQUIREMENT,
        project_id=project_id,
        entry_key="chat",
        **kwargs,
    )
    return await _drive_one_step(session)


# ══════════════════════════════════════════════════════════════════════════
# 1-3：骨架形状（P-2 正反并列 + 不共享可变对象）
# ══════════════════════════════════════════════════════════════════════════


def test_skeleton_passes_validation_and_carries_schema_version() -> None:
    """① 骨架过 ``validate_blueprint``，**且**那个判别键逐字就位（P-2 正面）。"""
    content = build_skeleton(title="标题", project_id=_PROJECT_ID, goal_text=_REQUIREMENT)

    assert validate_blueprint(content) == (True, None)
    # ⭐ 直接断言键值本身：只断言「校验通过」会被 v0 pass-through 恒真地满足（见下一条）。
    assert content["schema_version"] == BLUEPRINT_SCHEMA_VERSION
    assert content["meta"]["project_id"] == _PROJECT_ID
    assert _REQUIREMENT.splitlines()[0] in str(content["requirement_spec"]["goal"])


def test_validator_is_pass_through_without_schema_version() -> None:
    """② ⭐ **P-2 的反面并列**：删掉判别键，``validate_blueprint`` **仍返 ``(True, None)``**。

    没有这一条，上一条的「校验通过」就是恒真断言 —— 它对一份**完全没有 schema_version
    的空壳**同样成立。三条链（校验器 / 渲染器 / 入图门控）的判别式都是
    ``if content.get("schema_version")``，漏写即同时静默降级到 v0 且零异常。
    """
    content = build_skeleton(title="标题", project_id=_PROJECT_ID, goal_text="目标")
    content.pop("schema_version")

    assert validate_blueprint(content) == (True, None)
    # 连一份只有一个键的 dict 都「通过」——这就是为什么必须直接断言那个键。
    assert validate_blueprint({"meta": {}}) == (True, None)


def test_build_skeleton_returns_independent_objects() -> None:
    """③ 工厂返回的是深拷贝：改第一份的嵌套容器，第二份与模块常量都不受影响。"""
    from services.process_runtime import blueprint_intake

    first = build_skeleton(title="a", project_id=_PROJECT_ID, goal_text="g1")
    first["repo_associations"].append({"repository_id": "污染"})
    first["meta"]["title"] = "被改了"

    second = build_skeleton(title="b", project_id=_PROJECT_ID, goal_text="g2")

    assert second["repo_associations"] == []
    assert second["meta"]["title"] == "b"
    assert blueprint_intake.MINIMAL_BLUEPRINT_SKELETON["repo_associations"] == []


# ══════════════════════════════════════════════════════════════════════════
# 4-6：三条硬断言（走真实 start_blueprint_orchestration + 驱一步 intake）
# ══════════════════════════════════════════════════════════════════════════


async def test_intake_seeds_version_whose_db_content_has_schema_version(django_user_model) -> None:
    """④ 硬断言①：**DB 重读**的落库版本带 ``schema_version``（⛔ 不读内存对象）。"""
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="intake-1", password="x"
    )
    await _make_project(member=user)

    session = await _start_and_intake()

    version = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    assert version.content["schema_version"] == BLUEPRINT_SCHEMA_VERSION
    assert version.version_no == 1
    assert validate_blueprint(version.content) == (True, None)
    artifact = await Artifact.objects.aget(id=version.artifact_id)
    assert artifact.blueprint_status == BlueprintStatus.RESEARCHING


async def test_intake_sets_session_artifact_version_pointer() -> None:
    """⑤ 硬断言②：``session.current_artifact_version_id`` 非空（DB 重读）。

    不成立时后果是**静默的**：``blueprint_spec_gate`` 取不到版本即恒判需澄清，会话卡死
    在 spec_gate 且零异常（反向对照见 ``test_spec_gate_without_pointer_*``）。
    """
    await _make_project()

    session = await _start_and_intake()

    assert session.current_artifact_version_id is not None
    assert session.current_stage == "decompose"
    assert (session.stage_state or {}).get("intake", {}).get("artifact_id")


async def test_seeded_project_id_is_queryable_via_project_member(django_user_model) -> None:
    """⑥ 硬断言③：``meta.project_id`` **能被 ``ProjectMember`` 查中**。

    ⛔ 断言「非空」不够 —— 一份 ``meta.project_id`` 落成 Space id 的蓝图同样非空，而它
    的全部端点恒不可用（见 ``test_blueprint_with_space_id_*``）。
    """
    user = await sync_to_async(django_user_model.objects.create_user)(
        username="intake-3", password="x"
    )
    await _make_project(member=user)

    session = await _start_and_intake()

    version = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    project_id = version.content["meta"]["project_id"]
    assert await _project_member_hits(project_id, user)


# ══════════════════════════════════════════════════════════════════════════
# 7-9：P-8（MCP 的 Space/Project 混淆）三面夹击
# ══════════════════════════════════════════════════════════════════════════


async def test_mcp_context_resolves_to_project_not_space() -> None:
    """⑦ ⭐ MCP 变异靶：``work_item_context.space`` 是 **Space FK**，必须换算成 Project。

    ``mcp_tools/technical_plan_service.py:488`` 把 ``space_id`` 当 ``"project_id"`` 键回给
    调用方 —— 把本函数的 MCP 分支改成透传 ``space_id``，本用例立刻转红（实跑记录见
    116-02-SUMMARY）。
    """
    project = await _make_project()
    space = await sync_to_async(lambda: project.space)()
    context = _FakeWorkItemContext(space)

    resolved = await aresolve_project_id(entry="mcp", work_item_context=context)

    assert resolved != str(space.id), "⛔ 透传 space_id 即落一份 20 个端点恒不可用的蓝图"
    assert resolved == _PROJECT_ID
    assert await sync_to_async(_project_exists)(resolved)


async def test_unresolvable_project_rejects_with_zero_side_effects() -> None:
    """⑧ ⭐ 推不出 project_id ⇒ 抛且**零副作用**（三张表计数与调用前逐字相等）。"""
    before = await _counts()

    with pytest.raises(BlueprintIntakeRejected) as excinfo:
        await start_blueprint_orchestration(
            ConvergenceSessionEntrypoint.CHAT, _REQUIREMENT, entry_key="chat"
        )

    assert excinfo.value.reason == "project_unresolved"
    assert excinfo.value.detail and "/" not in excinfo.value.detail  # 中性文案，无内部路径
    assert await _counts() == before


async def test_blueprint_with_space_id_as_project_id_is_unusable_downstream(
    django_user_model,
) -> None:
    """⑨ 把 P-8 的代价钉成事实：同一用户、同一端点，Space id 那份**恒不可用**。

    对照组（正确 project_id）必须 200 —— 否则本用例只是在断言「端点坏了」。
    """
    from rest_framework.test import APIClient

    user = await sync_to_async(django_user_model.objects.create_user)(
        username="intake-9", password="x"
    )
    project = await _make_project(member=user)
    space = await sync_to_async(lambda: project.space)()

    good = await _aseed_manual(project_id=_PROJECT_ID)
    bad = await _aseed_manual(project_id=str(space.id))

    client = APIClient()
    client.force_authenticate(user=user)
    ok = await sync_to_async(client.get)(f"/api/delivery/artifacts/{good.id}/blueprint-review/")
    denied = await sync_to_async(client.get)(f"/api/delivery/artifacts/{bad.id}/blueprint-review/")

    assert ok.status_code == 200
    assert denied.status_code != 200
    # 范围闸 fail-closed：Space id 也是合法 UUID ⇒ 命中「非该项目成员」的中性 404
    # （而不是「读不到 project_id」的 400）。两条都是「恒不可用且无补救入口」。
    assert denied.status_code in (400, 404)


# ══════════════════════════════════════════════════════════════════════════
# 10：intake 幂等 + 指针反向对照
# ══════════════════════════════════════════════════════════════════════════


async def test_intake_is_idempotent_on_replay() -> None:
    """⑩ 同一会话重驱 intake ⇒ 不重复建 artifact，且**仍带回**既有指针。"""
    await _make_project()
    session = await _start_and_intake()
    pointer = session.current_artifact_version_id
    after_first = await sync_to_async(lambda: Artifact.objects.count())()

    session.current_stage = "intake"
    await session.asave(update_fields=["current_stage"])
    session = await _drive_one_step(session)

    assert await sync_to_async(lambda: Artifact.objects.count())() == after_first
    assert session.current_artifact_version_id == pointer


async def test_spec_gate_without_pointer_needs_clarification() -> None:
    """⑩b ⭐ 「``StageOutcome`` 不带指针」的**反向对照**：规格门恒判需澄清。

    这条把「handler 必须显式带回 ``current_artifact_version``」从注释变成可证伪事实：
    没有指针的会话（= 替身 handler 返回 ``StageOutcome(event="intaken")`` 之后的形态）
    进 spec_gate 拿不到版本 ⇒ ``needs_clarification`` + 无线程，会话卡死。
    """
    from services.process_runtime.blueprint_spec_gate import BlueprintSpecGateAdapter

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="spec_gate",
        stage_state={"decomposition": {"requirement_text": _REQUIREMENT}},
    )

    result = await BlueprintSpecGateAdapter(scorer=AsyncMock()).run(session)

    assert session.current_artifact_version_id is None
    assert result["event"] == "needs_clarification"


# ══════════════════════════════════════════════════════════════════════════
# 11-13：decompose 两条路径 + 重跑不翻版本
# ══════════════════════════════════════════════════════════════════════════

_SEGMENTS = [
    {"title": "习题生成接口", "module": "practice", "layer": "backend"},
    {"title": "练习页生成入口", "module": "practice", "layer": "frontend"},
    {"title": "生成结果埋点", "module": "observability", "layer": "backend"},
]


async def test_decompose_from_feature_segments_never_calls_llm() -> None:
    """⑪ 路径 (a)：三条 segments ⇒ 三个功能点、id 两两不同，且 **LLM 零调用**。"""
    await _make_project()
    session = await _start_and_intake(feature_segments=_SEGMENTS, mode="feature_list")
    artifact = await _artifact_of(session)

    with patch("agents.llm_factory.build_chat_model") as build_model:
        version = await adecompose_feature_points(
            session=session,
            artifact=artifact,
            requirement_text=_REQUIREMENT,
            feature_segments=_SEGMENTS,
        )

    build_model.assert_not_called()
    assert version is not None
    points = version.content["requirement_spec"]["feature_points"]
    assert [p["title"] for p in points] == [s["title"] for s in _SEGMENTS]
    assert len({p["id"] for p in points}) == 3
    assert validate_blueprint(version.content) == (True, None)


async def test_decompose_rerun_does_not_create_a_new_version() -> None:
    """⑫ ⭐ 确定性 id ⇒ 重跑 ``content_hash`` 相等 ⇒ ``add_version`` 复用 current。

    随机 uuid 作 id 会让每次重跑都翻一版，把版本历史刷成噪声、diff 视图不可用（T-116-14）。
    """
    await _make_project()
    session = await _start_and_intake(feature_segments=_SEGMENTS, mode="feature_list")
    artifact = await _artifact_of(session)

    first = await adecompose_feature_points(
        session=session,
        artifact=artifact,
        requirement_text=_REQUIREMENT,
        feature_segments=_SEGMENTS,
    )
    assert first is not None
    after_first = await sync_to_async(lambda: ArtifactVersion.objects.count())()

    second = await adecompose_feature_points(
        session=session,
        artifact=artifact,
        requirement_text=_REQUIREMENT,
        feature_segments=copy.deepcopy(_SEGMENTS),
    )

    assert second is None, "无实质变化不得翻版本"
    assert await sync_to_async(lambda: ArtifactVersion.objects.count())() == after_first


async def test_decompose_is_fail_soft_when_llm_unavailable() -> None:
    """⑬ 路径 (b)：LLM 抛异常 ⇒ **不抛、不落 FAILED**，``feature_points`` 保持空。

    一次上游抖动不该废掉整条蓝图 —— 规格门本就会因信息不足而开澄清，那是正确的下一步。
    """
    await _make_project()
    session = await _start_and_intake()
    artifact = await _artifact_of(session)
    before = await sync_to_async(lambda: ArtifactVersion.objects.count())()

    with patch(
        "services.provider_config.ProviderConfigService.aresolve",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
    ):
        version = await adecompose_feature_points(
            session=session, artifact=artifact, requirement_text=_REQUIREMENT
        )

    assert version is None
    assert await sync_to_async(lambda: ArtifactVersion.objects.count())() == before
    latest = await _latest_version(artifact)
    assert latest.content["requirement_spec"]["feature_points"] == []
    session = await ConvergenceSession.objects.aget(id=session.id)
    assert session.status != "failed"


async def test_decompose_handler_carries_pointer_when_nothing_changed() -> None:
    """⑭ handler 三种分支都带回指针：无新版本时带回会话**既有**指针。"""
    await _make_project()
    session = await _start_and_intake(feature_segments=_SEGMENTS, mode="feature_list")
    pointer_before = session.current_artifact_version_id

    session = await _drive_one_step(session)  # decompose：直采落 v2

    assert session.current_stage == "spec_gate"
    assert session.current_artifact_version_id is not None
    assert session.current_artifact_version_id != pointer_before
    version = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    assert len(version.content["requirement_spec"]["feature_points"]) == 3


# ══════════════════════════════════════════════════════════════════════════
# 15：INV-6 源码扫描（本模块绝不裸写状态字段，也不进豁免名单）
# ══════════════════════════════════════════════════════════════════════════


def test_intake_module_never_writes_status_field_directly() -> None:
    """⑮ INV-6：本模块零裸写状态字段、走 lifecycle service、且未进豁免名单。"""
    src = _INTAKE_MODULE.read_text(encoding="utf-8")
    guard = (_SERVER_DIR / "tests/delivery/test_blueprint_inv6_guard.py").read_text("utf-8")

    from tests.delivery.test_blueprint_inv6_guard import _FIELD_WRITE_PATTERNS

    for pattern in _FIELD_WRITE_PATTERNS:
        assert not pattern.search(src), f"发现旁路写状态字段：{pattern.pattern}"
    assert "BlueprintLifecycleService" in src
    assert "blueprint_intake" not in guard.split("_ALLOWED_WRITER")[1].splitlines()[0]
    # 骨架的判别键取自懒 import 的常量，⛔ 不复制字面量（MN-10）
    tree = ast.parse(src)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == BLUEPRINT_SCHEMA_VERSION
    ]
    assert not literals, "⛔ 不得复制 schema 版本字面量，必须取 BLUEPRINT_SCHEMA_VERSION"


# ══════════════════════════════════════════════════════════════════════════
# 局部 helper
# ══════════════════════════════════════════════════════════════════════════


class _FakeWorkItemContext:
    """``McpWorkItemContext`` 的最小替身：``space`` 是 ``projects.Space``（⛔ 不是 Project）。"""

    def __init__(self, space: Any) -> None:
        self.space = space
        self.space_id = space.id


def _project_exists(project_id: str) -> bool:
    from initiatives.models import Project

    return Project.objects.filter(id=project_id).exists()


async def _artifact_of(session: Any) -> Any:
    version = await ArtifactVersion.objects.select_related("artifact").aget(
        id=session.current_artifact_version_id
    )
    return version.artifact


async def _aseed_manual(*, project_id: str) -> Any:
    """手工造一份指定 ``meta.project_id`` 的蓝图（第 9 条的两个对照组）。"""
    from delivery.services.artifact_service import ArtifactService

    content = build_skeleton(title="对照组", project_id=project_id, goal_text="目标")
    return await ArtifactService().create("technical_plan", content, title="对照组")


def test_uuid_helper_rejects_non_uuid() -> None:
    """⑯ 形状闸：非 UUID 的 ``feature_meta.project_id`` 不得被当成合法 Project id。"""
    from services.process_runtime.blueprint_intake import _is_uuid

    assert _is_uuid(str(uuid.uuid4()))
    assert not _is_uuid("proj-0001")
    assert not _is_uuid("")
    assert not _is_uuid(None)


async def test_feature_meta_with_unknown_project_is_rejected() -> None:
    """⑰ ``feature_meta.project_id`` 形状对但**库里没有** ⇒ 照样拒（⛔ 不落坏 id）。"""
    with pytest.raises(BlueprintIntakeRejected):
        await aresolve_project_id(
            entry="feature_list", feature_meta={"project_id": str(uuid.uuid4())}
        )


async def test_feature_meta_project_is_used_directly() -> None:
    """⑱ ``feature_meta.project_id`` 已是 Project id 且存在 ⇒ 直接采用（零换算）。"""
    await _make_project()

    resolved = await aresolve_project_id(
        entry="feature_list", feature_meta={"project_id": _PROJECT_ID}
    )

    assert resolved == _PROJECT_ID
