"""coding_tools 单元测试 — create_coding_plan / update_coding_plan @tool。

coding-plan workflow：``create_coding_plan`` 不再创建 ``CodingSession``，
session 由前端通过 fan-out endpoint
``POST /api/chat/coding-plans/{plan_id}/sessions/`` 创建。本测试文件断言
工具新行为（仅产 plan + recommended_repositories）以及 update 工具仍
能在 session 已存在时同步刷新它们。
"""

import uuid

import pytest
from asgiref.sync import sync_to_async

from chat.models import CodingPlan, CodingSession, Conversation
from repositories.models import Repository


@pytest.fixture
def conversation(project):
    """创建绑定到 project 的测试 Conversation。"""
    return Conversation.objects.create(space=project, title="测试编码对话")


@pytest.fixture
def other_repository(db):
    """创建不属于 project 的独立 Repository。"""
    return Repository.objects.create(
        name="Other Repo",
        git_url="https://github.com/other/repo.git",
        git_platform="github",
        default_branch="main",
    )


# ============================================================================
# create_coding_plan 测试（coding-plan workflow 后行为）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlan:
    """create_coding_plan @tool 测试 — 工具只产 CodingPlan，不再 acreate session。"""

    @pytest.mark.asyncio
    async def test_create_coding_plan_success_returns_plan_only(
        self, project, repository, conversation
    ):
        """传入有效参数 → success=True，返回 plan_id 非空、session_id 为 None。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 技术方案\n- 修改 main.py",
            affected_files=[{"path": "src/main.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["coding_plan_id"]
        assert result.output["coding_session_id"] is None
        assert result.output["session_id"] is None
        assert result.output["status"] == "plan_only"
        # branch_name 不再由工具产；fan-out endpoint 自己生成
        assert result.output["branch_name"] == ""

    @pytest.mark.asyncio
    async def test_create_coding_plan_does_not_create_session(
        self, project, repository, conversation
    ):
        """工具不再 acreate CodingSession：调用前后 DB 计数不变。"""
        from agents.tools.coding_tools import create_coding_plan

        before = await CodingSession.objects.acount()
        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 方案",
            affected_files=[{"file_path": "x.py", "change_type": "modify"}],
        )
        after = await CodingSession.objects.acount()
        assert result.success is True
        assert before == after  # 工具不再产 session

    @pytest.mark.asyncio
    async def test_create_coding_plan_persists_plan_with_affected_files(
        self, project, repository, conversation
    ):
        """工具会写 CodingPlan，且 affected_files 经过归一化。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 方案内容",
            affected_files=[
                {"path": "src/a.py", "change_type": "add"},
                {"path": "src/b.py", "change_type": "modify"},
            ],
        )
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.tech_plan == "## 方案内容"
        assert len(plan.affected_files) == 2
        # path → file_path 归一化
        assert plan.affected_files[0]["file_path"] == "src/a.py"

    @pytest.mark.asyncio
    async def test_create_coding_plan_project_not_found(
        self, repository, conversation
    ):
        """传入不存在的 project_id，返回 success=False。"""
        from agents.tools.coding_tools import create_coding_plan

        fake_id = str(uuid.uuid4())
        result = await create_coding_plan(
            space_id=fake_id,
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 方案",
            affected_files=[],
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_coding_plan_repo_not_in_project(
        self, project, other_repository, conversation
    ):
        """传入不属于该 project 的 repository_id，返回 success=False。

        repository_id 现在 optional，但传入后仍校验 space 归属。
        """
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(other_repository.id),
            tech_plan="## 方案",
            affected_files=[],
        )
        assert result.success is False
        assert "does not belong" in (result.error or "")

    @pytest.mark.asyncio
    async def test_create_coding_plan_without_repository_id(
        self, project, conversation
    ):
        """coding-plan workflow：repository_id 可省略，工具仍能产生 plan。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            tech_plan="## 不传仓库的方案",
            affected_files=[{"file_path": "any.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["coding_plan_id"]
        assert result.output["repository_id"] == ""
        assert result.output["repository_name"] == ""

    @pytest.mark.asyncio
    async def test_create_coding_plan_repository_id_topped_in_recommended(
        self, project, repository, conversation, other_repository
    ):
        """coding-plan workflow：传入 repository_id 时合并进 recommended（置顶）。

        ``recommended_repository_ids=[other]`` + ``repository_id=primary``：
        最终列表为 [primary, other]，primary 在前。
        """
        from agents.tools.coding_tools import create_coding_plan

        # 把 other_repository 也加入 project，让校验通过
        await sync_to_async(project.repositories.add)(other_repository)

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## merge",
            affected_files=[{"file_path": "x.py", "change_type": "modify"}],
            recommended_repository_ids=[str(other_repository.id)],
        )
        assert result.success is True
        ids = result.output["recommended_repository_ids"]
        assert ids[0] == str(repository.id)  # primary 置顶
        assert str(other_repository.id) in ids


# ============================================================================
# update_coding_plan 测试 — session 由 fixture 显式手建
# ============================================================================


@pytest.fixture
def draft_coding_session(conversation, repository):
    """创建 draft 状态的 CodingSession 供 update 测试使用。

    workflow update 起，session 不再由 create_coding_plan 工具创建，
    所以测 update 路径时直接在 fixture 里 acreate 一条。
    """
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan="## 初始方案",
        affected_files=[{"file_path": "src/old.py", "change_type": "modify"}],
        branch_name="coding-test1234",
    )


def _mk_session_for_plan(
    *, conversation, repository, plan, status=None, branch_name="manual-test"
):
    """同步辅助：在 plan 上手建一条 CodingSession（替代旧路径里 create_coding_plan
    顺便产 session 的副作用）。"""
    return CodingSession.objects.create(
        conversation=conversation,
        coding_plan=plan,
        repository=repository,
        tech_plan=plan.tech_plan,
        affected_files=plan.affected_files,
        branch_name=branch_name,
        status=status or CodingSession.Status.DRAFT,
    )


@pytest.mark.django_db(transaction=True)
class TestUpdateCodingPlan:
    """update_coding_plan @tool 测试（兼容 session_id 旧路径）。"""

    @pytest.mark.asyncio
    async def test_update_coding_plan_success(self, draft_coding_session):
        """通过旧 session_id 路径更新 draft session，触发 plan 创建并同步字段。"""
        from agents.tools.coding_tools import update_coding_plan

        result = await update_coding_plan(
            session_id=str(draft_coding_session.id),
            tech_plan="## 更新后方案\n- 新步骤",
            affected_files=[{"path": "src/new.py", "change_type": "add"}],
        )
        assert result.success is True
        assert "coding_plan_id" in result.output

        # 验证数据库（兼容字段同步刷新）
        await draft_coding_session.arefresh_from_db()
        assert draft_coding_session.tech_plan == "## 更新后方案\n- 新步骤"
        assert draft_coding_session.coding_plan_id is not None

    @pytest.mark.asyncio
    async def test_update_coding_plan_session_not_found(self):
        """传入不存在的 session_id 返回 error。"""
        from agents.tools.coding_tools import update_coding_plan

        fake_id = str(uuid.uuid4())
        result = await update_coding_plan(
            session_id=fake_id,
            tech_plan="## 方案",
            affected_files=[],
        )
        assert result.success is False
        assert "not found" in result.error.lower()


# ============================================================================
# implementation — CodingPlan dual-id + schema 归一化 + 多 session 同步
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestPhaseCodingPlanIntegration:
    """create / update 切换到 CodingPlan 域。

    coding-plan workflow：create 工具不再产 session；update 仍能同步既有
    session（由 fixture 或本类内 _mk_session_for_plan 手建）。
    """

    @pytest.mark.asyncio
    async def test_create_coding_plan_returns_dual_ids(
        self, project, repository, conversation
    ):
        """返回 payload 同时含 coding_plan_id 与 session_id alias（coding-plan workflow 后两者都为 None）。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## dual id 用例",
            affected_files=[{"file_path": "a.py", "change_type": "add"}],
        )
        assert result.success is True
        assert "coding_plan_id" in result.output
        assert "coding_session_id" in result.output
        assert "session_id" in result.output
        # coding-plan workflow：工具不产 session，两个 alias 都是 None
        assert result.output["coding_session_id"] is None
        assert result.output["session_id"] is None
        assert result.output["coding_session_id"] == result.output["session_id"]

    @pytest.mark.asyncio
    async def test_create_coding_plan_normalizes_legacy_path_key(
        self, project, repository, conversation
    ):
        """旧 path 入参自动归一化为 file_path，落库到 plan 是 file_path。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 归一化用例",
            affected_files=[{"path": "legacy.py", "change_type": "modify"}],
        )
        assert result.success is True
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.affected_files[0]["file_path"] == "legacy.py"
        assert "path" not in plan.affected_files[0]

    @pytest.mark.asyncio
    async def test_create_coding_plan_dedupes_same_tech_plan_in_same_conversation(
        self, project, repository, conversation
    ):
        """同一 conversation 内连续两次相同 tech_plan：plan_id 相同（aget_or_create 幂等）。

        coding-plan workflow：session 不再由工具创建，两次返回的 session_id
        都是 None；plan 维度的幂等行为保持。
        """
        from agents.tools.coding_tools import create_coding_plan

        kwargs = dict(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 完全相同的方案",
            affected_files=[{"file_path": "a.py", "change_type": "modify"}],
        )
        first = await create_coding_plan(**kwargs)
        second = await create_coding_plan(**kwargs)
        assert first.success and second.success
        assert first.output["coding_plan_id"] == second.output["coding_plan_id"]
        assert first.output["coding_session_id"] is None
        assert second.output["coding_session_id"] is None

    @pytest.mark.asyncio
    async def test_update_coding_plan_by_plan_id(
        self, project, repository, conversation
    ):
        """coding_plan_id 直接路由路径：plan 字段更新 + draft session 同步。

        coding-plan workflow：先 create_coding_plan 拿 plan_id，再手建一条
        draft session 关联 plan，最后用 update_coding_plan 同步两边。
        """
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 原方案",
            affected_files=[{"file_path": "old.py", "change_type": "modify"}],
        )
        plan_id = created.output["coding_plan_id"]
        plan = await CodingPlan.objects.aget(id=plan_id)
        # session 不再由工具自动产，测 update 同步前先手建一条 draft
        session = await sync_to_async(_mk_session_for_plan)(
            conversation=conversation,
            repository=repository,
            plan=plan,
        )

        result = await update_coding_plan(
            coding_plan_id=plan_id,
            tech_plan="## 新方案",
            affected_files=[{"file_path": "new.py", "change_type": "add"}],
        )
        assert result.success is True
        assert result.output["coding_plan_id"] == plan_id
        assert result.output["synced_sessions_count"] >= 1

        plan_refreshed = await CodingPlan.objects.aget(id=plan_id)
        assert plan_refreshed.tech_plan == "## 新方案"
        assert plan_refreshed.affected_files[0]["file_path"] == "new.py"

        session_refreshed = await CodingSession.objects.aget(id=session.id)
        assert session_refreshed.tech_plan == "## 新方案"
        assert session_refreshed.affected_files[0]["file_path"] == "new.py"

    @pytest.mark.asyncio
    async def test_update_coding_plan_by_legacy_session_id(
        self, project, repository, conversation
    ):
        """旧 session_id 路径：自动找到/回填 plan，返回 coding_plan_id。"""
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 旧路径",
            affected_files=[{"file_path": "x.py", "change_type": "modify"}],
        )
        plan_id = created.output["coding_plan_id"]
        plan = await CodingPlan.objects.aget(id=plan_id)
        session = await sync_to_async(_mk_session_for_plan)(
            conversation=conversation,
            repository=repository,
            plan=plan,
        )

        result = await update_coding_plan(
            session_id=str(session.id),
            tech_plan="## 更新后",
            affected_files=[{"file_path": "y.py", "change_type": "add"}],
        )
        assert result.success is True
        assert "coding_plan_id" in result.output

    @pytest.mark.asyncio
    async def test_update_coding_plan_missing_id_returns_error(self):
        """两个 id 都不传 → success=False + error 提示。"""
        from agents.tools.coding_tools import update_coding_plan

        result = await update_coding_plan(
            tech_plan="## abc",
            affected_files=[],
        )
        assert result.success is False
        assert "coding_plan_id" in result.error
        assert "session_id" in result.error

    @pytest.mark.asyncio
    async def test_update_coding_plan_does_not_touch_running_sessions(
        self, project, repository, conversation
    ):
        """plan 关联 1 draft + 1 running 时，update 只同步 draft，不污染 running。

        (coding_plan, repository) 部分唯一约束限制同时只能
        1 个 active session；本用例通过创建第二个 Repository 模拟多仓 fan-out
        让 draft 与 running 落在不同 repo 上，规避 unique_active_plan_repo。
        """
        from agents.tools.coding_tools import create_coding_plan, update_coding_plan

        # 第二个仓库（fan-out 模拟）
        repository_b = await sync_to_async(Repository.objects.create)(
            name="Test Repo B",
            git_url="https://gitlab.com/test/repo-b.git",
            git_platform="gitlab",
            default_branch="main",
        )
        await sync_to_async(project.repositories.add)(repository_b)

        created = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## 同方案 fan-out",
            affected_files=[{"file_path": "a.py", "change_type": "modify"}],
        )
        plan_id = created.output["coding_plan_id"]
        plan = await CodingPlan.objects.aget(id=plan_id)
        # repo A 上手建一条 draft session（替代旧路径里工具自动产的）
        draft_session = await sync_to_async(_mk_session_for_plan)(
            conversation=conversation,
            repository=repository,
            plan=plan,
            branch_name="draft-branch",
        )
        # 在第二个仓库上手工造一个 running session（模拟多仓 fan-out）
        running_session = await CodingSession.objects.acreate(
            conversation=conversation,
            repository=repository_b,
            coding_plan=plan,
            tech_plan="## 同方案 fan-out",
            affected_files=[{"file_path": "a.py", "change_type": "modify"}],
            status=CodingSession.Status.RUNNING,
            branch_name="running-branch",
        )

        result = await update_coding_plan(
            coding_plan_id=plan_id,
            tech_plan="## 更新内容",
            affected_files=[{"file_path": "b.py", "change_type": "modify"}],
        )
        assert result.success is True
        # 只同步了 1 个 draft
        assert result.output["synced_sessions_count"] == 1

        draft_refreshed = await CodingSession.objects.aget(id=draft_session.id)
        assert draft_refreshed.tech_plan == "## 更新内容"

        running_refreshed = await CodingSession.objects.aget(id=running_session.id)
        # running 的 deprecated 字段保留旧值不动
        assert running_refreshed.tech_plan == "## 同方案 fan-out"


# ============================================================================
# 工具注册测试
# ============================================================================


def test_coding_tools_registered_in_registry():
    """验证 coding_tools 模块的 @tool 已注册到全局 _tool_registry。"""
    import agents.tools.coding_tools  # noqa: F401
    from agents.tools.base import _tool_registry

    assert "create_coding_plan" in _tool_registry
    assert "update_coding_plan" in _tool_registry


@pytest.mark.asyncio
async def test_chat_runner_get_tool_names_gates_deep_analysis():
    """`chat_runner._get_tool_names(force_deep_analysis=False)` 必不返回 deep_analysis。

    防止后续代码改动重新把 deep_analysis 加回默认列表（这正是历史 bug：
    LLM 在普通模式被 prompt 诱导自主调 deep_analysis）。
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from agents.chat_runner import _get_tool_names

    fake_qs = MagicMock()
    fake_qs.aexists = AsyncMock(return_value=True)  # has_indexed=True

    with patch("agents.chat_runner.Repository.objects.filter", return_value=fake_qs):
        normal = await _get_tool_names("space-1", force_deep_analysis=False)
        forced = await _get_tool_names("space-1", force_deep_analysis=True)

    assert "deep_analysis" not in normal, (
        "默认模式必须闸住 deep_analysis；当前列表："
        f"{sorted(normal)}"
    )
    assert "deep_analysis" in forced
    assert "search_repository_code" in normal  # 普通检索工具仍需暴露


def test_coding_tools_in_indexed_tool_names():
    """验证 chat_runner._INDEXED_TOOL_NAMES 含 coding tools 但**不含** deep_analysis。

    `_FULL_TOOL_NAMES` 已拆为 `_INDEXED_TOOL_NAMES`（默认）+ `_DEEP_ANALYSIS_TOOL_NAMES`
    （用户开「深度分析」开关时），避免 LLM 在普通模式自主调 deep_analysis。
    """
    from agents.chat_runner import _DEEP_ANALYSIS_TOOL_NAMES, _INDEXED_TOOL_NAMES

    assert "create_coding_plan" in _INDEXED_TOOL_NAMES
    assert "update_coding_plan" in _INDEXED_TOOL_NAMES
    # 默认列表绝不能含 deep_analysis（核心闸门契约）
    assert "deep_analysis" not in _INDEXED_TOOL_NAMES
    # 开启深度分析时才追加 deep_analysis
    assert "deep_analysis" in _DEEP_ANALYSIS_TOOL_NAMES
    assert set(_INDEXED_TOOL_NAMES).issubset(set(_DEEP_ANALYSIS_TOOL_NAMES))


# ============================================================================
# system prompt + _get_tool_names 测试
# ============================================================================


@pytest.mark.asyncio
async def test_system_prompt_contains_coding_guidance(monkeypatch):
    """验证 system prompt 包含编码意图识别指引。

    implementation Task 7: async 化 + 强制 fallback 路径（避免依赖 DB seed）。
    """
    from chat.conversation_service import _build_system_prompt

    monkeypatch.setenv(
        "PROMPT_CENTER_DISABLED_KEYS",
        "chat.system.developer,chat.strategy.default,chat.coding_guidance",
    )
    prompt = await _build_system_prompt("Test Space", "test-uuid", "developer")
    assert "create_coding_plan" in prompt
    assert "编码" in prompt or "代码变更" in prompt


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_tool_names_includes_coding_tools(project, repository):
    """有索引仓库时，_get_tool_names 返回列表包含 coding tools。"""
    from chat.conversation_service import _get_tool_names

    # 将 repository 设置为已索引状态
    repository.index_status = "indexed"
    await repository.asave(update_fields=["index_status"])

    tool_names = await _get_tool_names(str(project.id))
    assert "create_coding_plan" in tool_names
    assert "update_coding_plan" in tool_names


# ============================================================================
# create_coding_plan recommended_repository_ids 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlanRecommendedRepos:
    """create_coding_plan 自动预填 recommended_repository_ids 行为。"""

    @pytest.mark.asyncio
    async def test_input_schema_has_optional_recommended_repository_ids(self):
        from agents.tools.registry import ToolRegistry

        tool = ToolRegistry.get_tool("create_coding_plan")
        assert tool is not None
        props = tool.parameters["properties"]
        assert "recommended_repository_ids" in props
        assert props["recommended_repository_ids"]["type"] == "array"
        # 不在 required
        assert "recommended_repository_ids" not in tool.parameters["required"]
        # coding-plan workflow：repository_id 也改为 optional
        assert "repository_id" not in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_explicit_ids_are_persisted_to_plan(
        self, project, repository, conversation
    ):
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## explicit recs",
            affected_files=[{"path": "a.py", "change_type": "modify"}],
            recommended_repository_ids=[str(repository.id)],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "explicit"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_no_explicit_inferred_from_latest_chat_tool_trace(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan
        from chat.models import RepositoryRoutingTrace

        # 写一条 trace：only repository selected_by_user_final=True
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": False,
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        )

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## auto-infer",
            affected_files=[{"path": "x.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "trace_inferred"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_manual_override_trace_takes_precedence(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan
        from chat.models import RepositoryRoutingTrace

        # 第一行：chat_tool，only repository selected
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": False,
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        )
        # 第二行：manual_override，user 把 other 也选上
        await RepositoryRoutingTrace.objects.acreate(
            conversation=conversation,
            query="q",
            candidates=[
                {
                    "repository_id": str(repository.id),
                    "repository_name": "x",
                    "score": 0.9,
                    "level": "high",
                    "evidence": "ev",
                    "selected_by_ai": True,
                    "selected_by_user_final": True,
                },
                {
                    "repository_id": str(other_repository.id),
                    "repository_name": "y",
                    "score": 0.3,
                    "level": "low",
                    "evidence": "ev",
                    "selected_by_ai": False,
                    "selected_by_user_final": True,  # user 改选
                },
            ],
            threshold=0.5,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE,
        )

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## with manual override",
            affected_files=[{"path": "x.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "trace_inferred"
        # 最新 trace（manual_override 行）的两个 selected_by_user_final=True 仓库都拿到
        ids = set(result.output["recommended_repository_ids"])
        assert str(repository.id) in ids
        assert str(other_repository.id) in ids

    @pytest.mark.asyncio
    async def test_no_trace_no_explicit_with_repository_id_falls_back_to_primary(
        self, project, repository, conversation
    ):
        """coding-plan workflow：trace + explicit 都空，但传了 repository_id
        → final_recommended 仅含 primary，recommended_source='primary_repo'。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## empty rec with primary",
            affected_files=[{"path": "x.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "primary_repo"
        assert result.output["recommended_repository_ids"] == [str(repository.id)]
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == [str(repository.id)]

    @pytest.mark.asyncio
    async def test_no_trace_no_explicit_no_repository_id_returns_empty(
        self, project, conversation
    ):
        """coding-plan workflow：trace + explicit + repository_id 全空
        → empty 列表 + recommended_source='empty'。"""
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            tech_plan="## fully empty",
            affected_files=[{"path": "x.py", "change_type": "modify"}],
        )
        assert result.success is True
        assert result.output["recommended_source"] == "empty"
        assert result.output["recommended_repository_ids"] == []
        plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
        assert plan.recommended_repository_ids == []

    @pytest.mark.asyncio
    async def test_invalid_explicit_id_not_in_space_returns_error(
        self, project, repository, conversation, other_repository
    ):
        from agents.tools.coding_tools import create_coding_plan

        result = await create_coding_plan(
            space_id=str(project.id),
            conversation_id=str(conversation.id),
            repository_id=str(repository.id),
            tech_plan="## invalid",
            affected_files=[{"path": "x.py", "change_type": "modify"}],
            recommended_repository_ids=[str(other_repository.id)],
        )
        assert result.success is False
        assert "not in space" in (result.error or "")
