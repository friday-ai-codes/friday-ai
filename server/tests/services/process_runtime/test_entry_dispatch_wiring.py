"""四个入口的接线守卫（Phase 116-03）：六个续驱点 + 开关两态 + project_id 推导。

守四件事：

1. ⭐ **六个续驱点一个不漏**（Task 1）：六个文件里 ``build_orchestration_engine(`` 与
   ``adrive_convergence_session_to_pause_or_terminal(`` 的**直接调用零命中**（判据用
   ``ast``，``import`` 行不误伤），并用 ``plan_deepen_service.py`` 的**反向命中**证明扫描器
   非平凡。漏改一处的症状是「蓝图会话作答后无人续驱、卡在 waiting_clarification 永不推进
   且零异常」—— 源码扫描是唯一能把它变成机器可逮的形态。
2. ⭐ **四个入口 × 开关两态**（Task 2；同步点 2 收尾**翻默认后重写**）：
   - **默认（零配置）** ⇒ 建出 ``process_type == "technical_blueprint"`` 的会话且
     ``decomposition.project_id`` 非空 —— 这一档就是「翻了默认之后，一条真实需求确实
     驱动蓝图链」的端到端证明，⛔ 不靠显式设置蒙混过去；
   - **显式 override 回 ``technical_plan``** ⇒ 仍逐字走既有 ``start_orchestration``。
   两向对每个入口都并列存在（参数化「零配置 / 显式蓝图」两态共用同一份断言体）。
3. ⭐ **``meta.project_id`` 推不出即拒绝发起**：四个入口各自如实回错，且
   ``ConvergenceSession`` / ``Artifact`` 计数与调用前逐字相等（零副作用）。
4. ⭐ **MCP 的 Space/Project 混淆双防线**（P-8）：``McpWorkItemContext.space`` 必须过
   ``_aresolve_project`` —— 建出的蓝图 ``project_id`` 等于 ``Project.id`` 且**不等于**
   ``Space.id``；且 ``skip_clarification`` / ``force_confirm`` 绝不进蓝图链。
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[3]

# ⭐ 六个必改的续驱点（RESEARCH §A.4 表逐行）。⛔ 不含 subagent/api/callbacks.py:447
# （对蓝图三重不可达）与 plan_deepen_service.py:99（自己建 session，非蓝图入口）。
_REWIRED_FILES = (
    "workflows/nodes/ai/plan_research.py",
    "agents/tools/plan_research_tools.py",
    "mcp_tools/orchestration_delegate.py",
    "services/process_runtime/answer_resume.py",
    "feishu/callbacks/plan_clarify_callback.py",
    "initiatives/services/feature_solution_service.py",
)

# 四个真实入口文件（开关调用点所在）
_ENTRY_FILES = (
    "workflows/nodes/ai/plan_research.py",
    "agents/tools/plan_research_tools.py",
    "mcp_tools/orchestration_delegate.py",
    "initiatives/services/feature_solution_service.py",
)

_LEGACY_DIRECT_CALLS = (
    "build_orchestration_engine",
    "adrive_convergence_session_to_pause_or_terminal",
)


def _tail_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _call_hits(rel: str, names: tuple[str, ...]) -> list[str]:
    """该文件里对 ``names`` 的**直接调用**位置（``ast.Call``，``import`` 行不算）。"""
    path = _SERVER_DIR / rel
    assert path.exists(), f"扫描目标不存在：{rel}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _tail_name(node.func) in names:
            hits.append(f"{rel}:{node.lineno}: {_tail_name(node.func)}(")
    return hits


# ═══════════════════════════════════════════════════════════════════════════
# 1-4. 六个续驱点的源码扫描（Task 1）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rel", list(_REWIRED_FILES))
def test_no_direct_legacy_engine_or_driver_call(rel: str) -> None:
    """⭐ 六个续驱点里旧工厂 / 旧 driver 的**直接调用**零命中（``import`` 行不误伤）。

    漏改任一处 ⇒ 蓝图会话作答后无人续驱、卡在 ``waiting_clarification`` **永不推进且零
    异常**（T-116-21）。这是「漏改一处」唯一能被机器逮住的形态。
    """
    hits = _call_hits(rel, _LEGACY_DIRECT_CALLS)
    assert not hits, "仍有旧工厂 / 旧 driver 的直接调用：\n  " + "\n  ".join(hits)


def test_the_scanner_actually_catches_an_unrewired_file() -> None:
    """反向对照：``plan_deepen_service.py`` 是**有意不改**的一处，扫描器必须命中它。

    没有这一条，上面那组断言可能只是「扫描器根本逮不到任何东西」的假绿。同时把
    「这一处是有意不改的」显式登记在案（它自己建 session、``process_type`` 恒
    ``technical_plan``，不是蓝图入口）。
    """
    hits = _call_hits("initiatives/services/plan_deepen_service.py", _LEGACY_DIRECT_CALLS)
    assert hits, "扫描器对未改造文件零命中 ⇒ 判据是平凡的"


@pytest.mark.parametrize("rel", list(_REWIRED_FILES))
def test_dispatcher_is_actually_used(rel: str) -> None:
    """分派器真的被用上：六个文件里 ``build_engine_for_session`` 各至少一次调用。"""
    hits = _call_hits(rel, ("build_engine_for_session",))
    assert hits, f"{rel} 没有经 build_engine_for_session 取 engine/driver"


def test_answer_resume_swaps_the_driver_too() -> None:
    """⭐ ``answer_resume`` 的 **driver 也换了**（``:102-103`` 两行一起换）。

    只换 engine 不换 driver 仍然坏：旧 driver 的 ``waiting_clarification`` 短路判据
    （``ClarificationService.ahas_pending``）对蓝图恒 False ⇒ 健康会话被推到 ``max_steps``
    落 ``advance_step_limit`` FAILED。
    """
    rel = "services/process_runtime/answer_resume.py"
    assert not _call_hits(rel, ("adrive_convergence_session_to_pause_or_terminal",))
    assert _call_hits(rel, ("build_engine_for_session",))


def test_chat_container_callback_chain_is_untouched_by_design() -> None:
    """⛔ ``_schedule_chat_plan_resume`` 那条链**有意不改**（对蓝图三重不可达）。

    分支条件 ``last_output["source"] == "plan_research"``（蓝图容器写
    ``blueprint_research`` / ``blueprint_repo_plan``）、函数体读 ``plan_session_id``
    （蓝图写 ``blueprint_session_id``）、外加 ``entrypoint == CHAT`` 守门 —— 三条任一都拦
    得住。改它等于给一条永不执行的分支加维护面。
    """
    src = (_SERVER_DIR / "subagent/api/callbacks.py").read_text(encoding="utf-8")
    start = src.index("def _schedule_chat_plan_resume")
    end = src.index("\nasync def ", start + 1)
    assert "build_orchestration_engine" in src[start:end]


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. 四个入口的字面量开关调用点（Task 2）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rel", list(_ENTRY_FILES))
def test_entry_resolves_the_switch_with_a_literal_constant(rel: str) -> None:
    """⭐ 四个入口各有一处 ``aresolve_entry_process_type`` 且实参是**字面量常量**。

    ⛔ 写成 ``session.entrypoint`` 会让「只打开 workflow 键」把 MCP 一起切走 —— MCP 入口
    给 ``start_orchestration`` 传的 ``entrypoint`` 实测就是 ``"workflow"``（既有约定）。
    116-01 的 ``ast`` 守卫覆盖同一批文件；这里再按「每个文件至少一处」正面点名。
    """
    path = _SERVER_DIR / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _tail_name(node.func) != "aresolve_entry_process_type":
            continue
        arg: ast.expr | None = node.args[0] if node.args else None
        if arg is None:
            arg = next((kw.value for kw in node.keywords if kw.arg == "entry"), None)
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), (
            f"{rel}:{node.lineno} 开关实参必须是字面量常量"
        )
        literals.append(arg.value)
    assert literals, f"{rel} 没有查 per-entry 开关"


def test_force_confirm_never_leaks_into_the_blueprint_chain() -> None:
    """⛔ ``force_confirm`` 绝不进 ``start_blueprint_orchestration`` 的实参。

    它注入的是旧链 ``ClarifyAdapter`` 的题目组装器，蓝图链无对应面；「强制确认关联仓」在
    蓝图链由 ``repo_confirmation`` 硬门天然承担（T-116-26）。
    """
    rel = "initiatives/services/feature_solution_service.py"
    tree = ast.parse((_SERVER_DIR / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _tail_name(node.func) == "start_blueprint_orchestration":
            assert not any(kw.arg == "force_confirm" for kw in node.keywords)
            assert not any(kw.arg == "skip_clarification" for kw in node.keywords)


def test_mcp_never_passes_space_id_as_project_id() -> None:
    """⭐ P-8 源码防线：MCP 分支绝不把 ``context.space_id`` 当 ``project_id`` 透传。

    ``McpWorkItemContext.space`` 是 ``projects.Space`` FK，而
    ``technical_plan_service.py:488`` 把它当 ``"project_id"`` 键回给调用方 —— 透传即落一份
    「20 个端点恒不可用、图谱恒不入、导出恒不可用」且没有补救入口的蓝图。
    """
    src = (_SERVER_DIR / "mcp_tools/orchestration_delegate.py").read_text(encoding="utf-8")
    assert "aresolve_project_id" in src
    assert "project_id=context.space_id" not in src
    assert "project_id=str(context.space_id)" not in src
    assert "space_id" not in src.split("start_blueprint_orchestration")[1][:800]


def test_workflow_terminal_mapping_no_longer_hands_unreviewed_blueprints_downstream() -> None:
    """⭐ 同步点 2 已闭合：蓝图终态**不再**走旧链 ``_map_terminal``（源码级防线）。

    本测试此前断言的是**相反**的东西 —— 「``_map_terminal`` 本 plan 一行未改、改法归同步点
    2 之后」。同步点 2 到了，断言随之翻面：现在要锁死的是「蓝图 ``DONE`` 绝不被当成
    ``completed`` 交给下游 ``ai_coding``」（T-116-18 / RELY-01）。

    三条源码级不变量：
    1. 存在独立的蓝图终态分档 ``_amap_terminal_blueprint``（⛔ 不是往旧链函数里插分支）；
    2. 旧链 ``_map_terminal`` 仍是**两参签名**（既有测试按它做替身，改签名会打断它们）；
    3. ⭐ ``pending_review`` **不在**「可放行给下游」的状态集合里 —— 那正是等人审那一档。

    行为面的断言见 ``tests/services/process_runtime/test_blueprint_consumer_seams.py``。
    """
    from workflows.nodes.ai.plan_research import _BLUEPRINT_REVIEWED_STATUSES

    src = (_SERVER_DIR / "workflows/nodes/ai/plan_research.py").read_text(encoding="utf-8")
    assert "async def _amap_terminal_blueprint" in src
    assert "async def _map_terminal(self, session: Any) -> NodeResult:" in src
    assert "pending_review" not in _BLUEPRINT_REVIEWED_STATUSES


# ═══════════════════════════════════════════════════════════════════════════
# 7+. 行为面：四入口 × 开关两态 / 推不出 project_id ⇒ 零副作用
# ═══════════════════════════════════════════════════════════════════════════

pytestmark_db = pytest.mark.django_db(transaction=True)

_BLUEPRINT = "technical_blueprint"
_LEGACY = "technical_plan"


def _save_switch(value: dict[str, str]) -> None:
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.update_or_create(
        key=SettingKeys.BLUEPRINT_ENTRY_SWITCH, defaults={"value": json.dumps(value)}
    )


def _clear_switch() -> None:
    from django.core.cache import cache

    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    SystemSetting.objects.filter(key__startswith="blueprint.").delete()
    cache.delete(_cache_key(SettingKeys.BLUEPRINT_ENTRY_SWITCH))


@pytest.fixture(autouse=True)
def _isolate_switch(request: pytest.FixtureRequest):
    if request.node.get_closest_marker("django_db") is None:
        yield
        return
    request.getfixturevalue("db")
    _clear_switch()
    yield
    _clear_switch()


async def _aset_switch(**entries: str) -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(_save_switch)(dict(entries))


async def _aapply_switch(entry: str, value: str | None) -> None:
    """⭐ 参数化「零配置 / 显式蓝图」两态的统一入口。

    ``value is None`` = **什么都不写**（走翻过之后的默认），这一态才是本次收尾要证明的
    「不配置也确实驱动蓝图链」；写显式值那一态并列存在，用来证明开关本身没被绕过。
    """
    if value is not None:
        await _aset_switch(**{entry: value})


# 两态：``None`` = 零配置（新默认）；显式蓝图。两者都必须落到蓝图链。
_BLUEPRINT_SWITCH_STATES = [None, _BLUEPRINT]


async def _amake_project() -> tuple[object, object]:
    """建一条 ``Space`` + 其下的 ``Project``（``_aresolve_project`` 取该 space 首个）。"""
    from initiatives.models import Project
    from projects.models import Space

    space = await Space.objects.acreate(name=f"space-{uuid.uuid4().hex[:6]}")
    project = await Project.objects.acreate(space=space, name=f"proj-{uuid.uuid4().hex[:6]}")
    return space, project


def _stub_runtime():
    """把 engine 构造 + 两个 driver 换成不推进的替身（本文件只验接线，不驱真链路）。"""
    engine = MagicMock(name="engine")
    return patch(
        "services.process_runtime.entrypoint.build_engine_for_session",
        new=lambda session, **kw: (engine, AsyncMock(return_value=session)),
    )


# ---------------------------------------------------------------- workflow 入口


async def _aworkflow_context(space):
    """真实 ``Workflow`` / ``WorkflowExecution`` 上的最小 ``ExecutionContext``。

    传一个**其下没有任何 Project 的** Space 即模拟「推不出 project_id」（``_aresolve_project``
    返 None ⇒ 拒绝发起用例）。
    """
    from types import SimpleNamespace

    from workflows.models import Workflow, WorkflowExecution

    workflow = await Workflow.objects.acreate(name="编排工作流", space=space)
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=space, trigger_type="manual"
    )
    return SimpleNamespace(
        node_config={"requirement_text": "让登录支持双因子"},
        input_data={},
        execution_id=str(execution.id),
        node_id="n1",
        node_execution=None,
        workflow_execution=execution,
        workflow_context={},
        render_template=lambda s: s,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_workflow_entry_explicit_rollback_is_byte_identical() -> None:
    """⭐ 显式回滚到 ``technical_plan`` ⇒ workflow 入口逐字走 ``start_orchestration``。

    翻默认之后这一档要靠**显式 override** 才到达；它证明运维那条「改一个设置值即回退」
    的路仍然通。
    """
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    space, _project = await _amake_project()
    await _aset_switch(workflow=_LEGACY)
    node = AIPlanResearchNode()
    ctx = await _aworkflow_context(space)

    session = await node._create_session(ctx, MagicMock())

    assert session is not None
    assert session.process_type == _LEGACY
    assert session.entrypoint == "workflow"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("switch", _BLUEPRINT_SWITCH_STATES)
async def test_workflow_entry_drives_the_blueprint_chain(switch: str | None) -> None:
    """⭐ 零配置（新默认）与显式蓝图**两态并列** ⇒ 都建蓝图会话且带 ``project_id``。"""
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    space, project = await _amake_project()
    await _aapply_switch("workflow", switch)

    node = AIPlanResearchNode()
    session = await node._create_session(await _aworkflow_context(space), MagicMock())

    assert session.process_type == _BLUEPRINT
    assert session.entrypoint == "workflow"
    assert (session.decomposition or {}).get("project_id") == str(project.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_workflow_entry_rejects_when_project_unresolved() -> None:
    """⭐ 推不出 project_id ⇒ ``NodeResult(next_handle="error")`` 且 **DB 零副作用**。

    ⚠️ 翻默认之后这一档**不需要设开关**就会到达 —— 也正因如此它更重要了：默认走蓝图链
    意味着「推不出项目」从边缘态变成了任何一个未关联项目的工作流都会撞上的正常路径。
    """
    from delivery.models import Artifact, ConvergenceSession
    from projects.models import Space
    from workflows.nodes.ai.plan_research import AIPlanResearchNode

    # 该 space 下**没有任何 Project** ⇒ Space→Project 换算落空。
    empty_space = await Space.objects.acreate(name=f"space-{uuid.uuid4().hex[:6]}")
    before_sessions = await ConvergenceSession.objects.acount()
    before_artifacts = await Artifact.objects.acount()

    node = AIPlanResearchNode()
    result = await node._create_session(await _aworkflow_context(empty_space), MagicMock())

    assert result.status == "failed"
    assert result.next_handle == "error"
    assert result.error and "/" not in result.error
    assert await ConvergenceSession.objects.acount() == before_sessions
    assert await Artifact.objects.acount() == before_artifacts


# ---------------------------------------------------------------- chat 入口


async def _amake_conversation(space):
    from chat.models import Conversation

    return await Conversation.objects.acreate(space=space)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_chat_entry_explicit_rollback_is_byte_identical() -> None:
    """显式回滚 ⇒ chat 入口建的仍是 ``technical_plan`` / ``entrypoint=chat`` 会话。"""
    from agents.tools.plan_research_tools import start_plan_research
    from delivery.models import ConvergenceSession

    space, _project = await _amake_project()
    conv = await _amake_conversation(space)
    await _aset_switch(chat=_LEGACY)

    with _stub_runtime():
        result = await start_plan_research(
            requirement_text="让登录支持双因子",
            space_id=str(space.id),
            conversation_id=str(conv.id),
        )

    session = await ConvergenceSession.objects.filter(conversation_id=conv.id).afirst()
    assert session is not None
    assert session.process_type == _LEGACY
    assert session.entrypoint == "chat"
    assert result is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("switch", _BLUEPRINT_SWITCH_STATES)
async def test_chat_entry_drives_the_blueprint_chain(switch: str | None) -> None:
    """⭐ 零配置（新默认）与显式蓝图两态并列 ⇒ chat 入口都建蓝图会话且带所属项目。"""
    from agents.tools.plan_research_tools import start_plan_research
    from delivery.models import ConvergenceSession

    space, project = await _amake_project()
    conv = await _amake_conversation(space)
    await _aapply_switch("chat", switch)

    with _stub_runtime():
        await start_plan_research(
            requirement_text="让登录支持双因子",
            space_id=str(space.id),
            conversation_id=str(conv.id),
        )

    session = await ConvergenceSession.objects.filter(conversation_id=conv.id).afirst()
    assert session is not None
    assert session.process_type == _BLUEPRINT
    assert session.entrypoint == "chat"
    assert (session.decomposition or {}).get("project_id") == str(project.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_chat_entry_rejects_when_project_unresolved() -> None:
    """⭐ chat 推不出 project_id ⇒ ``ToolResult(success=False)`` 且 DB 零副作用。"""
    from agents.tools.plan_research_tools import start_plan_research
    from chat.models import Conversation
    from delivery.models import Artifact, ConvergenceSession

    conv = await Conversation.objects.acreate()
    before_sessions = await ConvergenceSession.objects.acount()
    before_artifacts = await Artifact.objects.acount()

    with _stub_runtime():
        result = await start_plan_research(
            requirement_text="让登录支持双因子",
            space_id="",
            conversation_id=str(conv.id),
        )

    assert result.success is False
    assert result.error and "/" not in result.error
    assert await ConvergenceSession.objects.acount() == before_sessions
    assert await Artifact.objects.acount() == before_artifacts


# ---------------------------------------------------------------- MCP 入口


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mcp_entry_explicit_rollback_is_byte_identical() -> None:
    """显式回滚 ⇒ MCP delegate 仍建 ``technical_plan`` 且 ``entrypoint="workflow"``（既有约定）。

    ⭐ 这一条同时守住 per-entry 纪律最尖锐的那一面：MCP 记的 ``entrypoint`` 就是
    ``"workflow"``，只回滚 ``mcp`` 键必须**只**影响 MCP，不能靠 entrypoint 反推。
    """
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    await _aset_switch(mcp=_LEGACY)

    with _stub_runtime():
        result = await delegate_process_runtime(requirement_text="让登录支持双因子")

    assert result.session.process_type == _LEGACY
    assert result.session.entrypoint == "workflow"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("switch", _BLUEPRINT_SWITCH_STATES)
async def test_mcp_context_resolves_to_project_not_space(switch: str | None) -> None:
    """⭐ P-8 行为防线：``meta.project_id`` 等于 ``Project.id`` 且**不等于** ``Space.id``。

    零配置（新默认）与显式蓝图两态并列 —— 翻默认之后前者才是生产实际走的那条。
    """
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    space, project = await _amake_project()
    context = _McpContextStub(space=space)
    await _aapply_switch("mcp", switch)

    with _stub_runtime():
        result = await delegate_process_runtime(
            requirement_text="让登录支持双因子", work_item_context=context
        )

    session = result.session
    resolved = (session.decomposition or {}).get("project_id")
    assert session.process_type == _BLUEPRINT
    assert resolved == str(project.id)
    assert resolved != str(space.id), "⛔ 透传 space_id 即落一份 20 个端点恒不可用的蓝图"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mcp_entry_rejects_when_project_unresolved() -> None:
    """⭐ MCP 推不出 project_id ⇒ ``status="failed"`` + 中性 detail，且 DB 零副作用。"""
    from delivery.models import Artifact, ConvergenceSession
    from mcp_tools.orchestration_delegate import delegate_process_runtime

    before_sessions = await ConvergenceSession.objects.acount()
    before_artifacts = await Artifact.objects.acount()

    with _stub_runtime():
        result = await delegate_process_runtime(requirement_text="让登录支持双因子")

    assert result.status == "failed"
    assert result.error_detail and "/" not in result.error_detail
    assert await ConvergenceSession.objects.acount() == before_sessions
    assert await Artifact.objects.acount() == before_artifacts


class _McpContextStub:
    """``McpWorkItemContext`` 的最小替身（只有 ``space`` / ``space_id`` 两个位被读）。"""

    def __init__(self, *, space) -> None:
        self.space = space
        self.space_id = getattr(space, "id", None)


# ---------------------------------------------------------------- feature list 入口


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("switch", _BLUEPRINT_SWITCH_STATES)
async def test_feature_list_entry_drives_the_blueprint_chain(switch: str | None) -> None:
    """⭐ 零配置（新默认）与显式蓝图两态并列 ⇒ 建蓝图会话且 ``feature_segments`` 原样进
    ``decomposition``（供直采，⛔ 不再走 LLM 拆分）。"""
    from delivery.models import ConvergenceSession
    from initiatives.services.feature_solution_service import FeatureSolutionService

    _space, project = await _amake_project()
    await _aapply_switch("feature_list", switch)

    segments = [
        {"title": "登录页加双因子开关", "module": "账号", "layer": "frontend"},
        {"title": "签发 TOTP 密钥", "module": "账号", "layer": "backend"},
        {"title": "补校验中间件", "module": "账号", "layer": "backend"},
    ]
    resolved = _ResolvedStub(project_id=str(project.id), segments=segments)

    session = await FeatureSolutionService()._acreate_session(
        resolved=resolved,
        repository_ids=[],
        entrypoint="mcp",
        actor=None,
        initiated_by_user_id="",
        conversation_id=None,
    )
    session = await ConvergenceSession.objects.aget(id=session.id)

    assert session.process_type == _BLUEPRINT
    decomposition = session.decomposition or {}
    assert decomposition.get("project_id") == str(project.id)
    assert len(decomposition.get("feature_segments") or []) == 3
    assert decomposition.get("mode") == "feature_list"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_feature_list_entry_explicit_rollback_is_byte_identical() -> None:
    """显式回滚 ⇒ feature list 入口仍建 ``technical_plan`` 且三个既有键形态不变。"""
    from initiatives.services.feature_solution_service import FeatureSolutionService

    _space, project = await _amake_project()
    await _aset_switch(feature_list=_LEGACY)
    resolved = _ResolvedStub(project_id=str(project.id), segments=[{"title": "A"}])

    session = await FeatureSolutionService()._acreate_session(
        resolved=resolved,
        repository_ids=[],
        entrypoint="mcp",
        actor=None,
        initiated_by_user_id="",
        conversation_id=None,
    )

    assert session.process_type == _LEGACY
    assert (session.decomposition or {}).get("mode") == "feature_list"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_feature_list_entry_rejects_when_project_unresolved() -> None:
    """⭐ feature list 推不出 project_id ⇒ ``FeatureSolutionError`` 且 DB 零副作用。"""
    from delivery.models import Artifact, ConvergenceSession
    from initiatives.services.feature_solution_service import (
        FeatureSolutionError,
        FeatureSolutionService,
    )

    before_sessions = await ConvergenceSession.objects.acount()
    before_artifacts = await Artifact.objects.acount()
    resolved = _ResolvedStub(project_id="", segments=[{"title": "A"}])

    with pytest.raises(FeatureSolutionError) as exc_info:
        await FeatureSolutionService()._acreate_session(
            resolved=resolved,
            repository_ids=[],
            entrypoint="mcp",
            actor=None,
            initiated_by_user_id="",
            conversation_id=None,
        )

    assert "/" not in exc_info.value.detail
    assert await ConvergenceSession.objects.acount() == before_sessions
    assert await Artifact.objects.acount() == before_artifacts


class _ResolvedStub:
    """``aresolve_feature_source`` 结果的最小替身（``_acreate_session`` 只读这几个位）。"""

    def __init__(self, *, project_id: str, segments: list[dict]) -> None:
        self.project_id = project_id
        self.segments = segments
        self.source = "feature_tree"
        self.module_count = 1
        self.truncated = False
        self.project = None
