"""coding_tools 单元测试 — create_coding_plan / update_coding_plan @tool。"""
import uuid
import pytest
from asgiref.sync import sync_to_async
from chat.models import CodingSession, Conversation
from repositories.models import Repository
@pytest.fixture
def conversation(project):
 """创建绑定到 project 的测试 Conversation。"""
 return Conversation.objects.create(project=project, title="测试编码对话")
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
# create_coding_plan 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCreateCodingPlan:
 """create_coding_plan @tool 测试。"""
 @pytest.mark.asyncio
 async def test_create_coding_plan_success(self, project, repository, conversation):
 """传入有效参数，返回 success=True 且 output 包含 session_id。"""
 from agents.tools.coding_tools import create_coding_plan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 技术方案\n- 修改 main.py",
 affected_files=[{"path": "src/main.py", "change_type": "modify"}],
 )
 assert result.success is True
 assert "session_id" in result.output
 assert result.output["status"] == "draft"
 assert "branch_name" in result.output
 @pytest.mark.asyncio
 async def test_create_coding_plan_creates_session(
 self, project, repository, conversation
 ):
 """验证数据库中创建了 CodingSession，字段正确。"""
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
 session_id = result.output["session_id"]
 session = await CodingSession.objects.aget(id=session_id)
 assert session.status == CodingSession.Status.DRAFT
 assert session.revision_count == 0
 assert session.tech_plan == "## 方案内容"
 assert len(session.affected_files) == 2
 # Phase：path 自动归一化为 file_path
 assert session.affected_files[0]["file_path"] == "src/a.py"
 @pytest.mark.asyncio
 async def test_create_coding_plan_project_not_found(
 self, repository, conversation
 ):
 """传入不存在的 project_id，返回 success=False。"""
 from agents.tools.coding_tools import create_coding_plan
 fake_id = str(uuid.uuid4)
 result = await create_coding_plan(
 space_id=fake_id,
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 方案",
 affected_files=,
 )
 assert result.success is False
 assert "not found" in result.error.lower
 @pytest.mark.asyncio
 async def test_create_coding_plan_repo_not_in_project(
 self, project, other_repository, conversation
 ):
 """传入不属于该 project 的 repository_id，返回 success=False。"""
 from agents.tools.coding_tools import create_coding_plan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(other_repository.id),
 tech_plan="## 方案",
 affected_files=,
 )
 assert result.success is False
 assert "error" != None
# ============================================================================
# update_coding_plan 测试
# ============================================================================
@pytest.fixture
def draft_coding_session(conversation, repository):
 """创建 draft 状态的 CodingSession 供 update 测试使用。
 Phase：affected_files 字段名 `file_path`；保留旧 `path` 字段名的迁移
 路径在 `_normalize_affected_files` 工具内自动转换，单元测试用例直接构造
 新 schema。
 """
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 初始方案",
 affected_files=[{"file_path": "src/old.py", "change_type": "modify"}],
 branch_name="coding-test1234",
 )
@pytest.mark.django_db(transaction=True)
class TestUpdateCodingPlan:
 """update_coding_plan @tool 测试（Phase：兼容 session_id 旧路径）。"""
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
 # Phase：新返回包含 coding_plan_id
 assert "coding_plan_id" in result.output
 # 验证数据库（兼容字段同步刷新）
 await draft_coding_session.arefresh_from_db
 assert draft_coding_session.tech_plan == "## 更新后方案\n- 新步骤"
 assert draft_coding_session.coding_plan_id is not None
 @pytest.mark.asyncio
 async def test_update_coding_plan_session_not_found(self):
 """传入不存在的 session_id 返回 error。"""
 from agents.tools.coding_tools import update_coding_plan
 fake_id = str(uuid.uuid4)
 result = await update_coding_plan(
 session_id=fake_id,
 tech_plan="## 方案",
 affected_files=,
 )
 assert result.success is False
 assert "not found" in result.error.lower
 @pytest.mark.asyncio
 async def test_branch_name_format(self, project, repository, conversation):
 """分支名应为 {type}{YYYYMMDD}.{desc} 格式，不再是 coding-{hex8}。"""
 import re
 from agents.tools.coding_tools import create_coding_plan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 技术方案\n- 实现 user authentication 模块",
 affected_files=[{"path": "src/auth.py", "change_type": "add"}],
 )
 assert result.success is True
 branch_name = result.output["branch_name"]
 # 格式校验：{feat|fix|chore}{YYYYMMDD}.{短描述}
 assert re.match(r"^(feat|fix|chore)\d{8}\.[a-z0-9\-]+$", branch_name), \
 f"分支名格式不正确: {branch_name}"
 assert not branch_name.startswith("coding-"), "不应使用旧的 coding- 前缀"
 @pytest.mark.asyncio
 async def test_branch_type_fix_from_tech_plan(self, project, repository, conversation):
 """tech_plan 包含 fix 关键词时分支类型应为 fix。"""
 from agents.tools.coding_tools import create_coding_plan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 修复方案\n- 修复 null pointer bug in user module",
 affected_files=[{"path": "src/user.py", "change_type": "modify"}],
 )
 assert result.success is True
 branch_name = result.output["branch_name"]
 assert branch_name.startswith("fix"), f"应以 fix 开头: {branch_name}"
 @pytest.mark.asyncio
 async def test_branch_type_chore_from_tech_plan(self, project, repository, conversation):
 """tech_plan 包含 refactor 关键词时分支类型应为 chore。"""
 from agents.tools.coding_tools import create_coding_plan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 重构方案\n- refactor database connection module",
 affected_files=[{"path": "src/db.py", "change_type": "modify"}],
 )
 assert result.success is True
 branch_name = result.output["branch_name"]
 assert branch_name.startswith("chore"), f"应以 chore 开头: {branch_name}"
# ============================================================================
# Phase — CodingPlan dual-id + schema 归一化 + 多 session 同步
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestPhaseCodingPlanIntegration:
 """Phase：create / update 切换到 CodingPlan 域。"""
 @pytest.mark.asyncio
 async def test_create_coding_plan_returns_dual_ids(
 self, project, repository, conversation
 ):
 """返回 payload 同时含 coding_plan_id / coding_session_id / session_id（兼容 alias）。"""
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
 assert "session_id" in result.output # 兼容 alias
 assert result.output["coding_session_id"] == result.output["session_id"]
 @pytest.mark.asyncio
 async def test_create_coding_plan_normalizes_legacy_path_key(
 self, project, repository, conversation
 ):
 """旧 path 入参自动归一化为 file_path，落库到 plan 与 session 都是 file_path。"""
 from agents.tools.coding_tools import create_coding_plan
 from chat.models import CodingPlan, CodingSession
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 归一化用例",
 affected_files=[{"path": "legacy.py", "change_type": "modify"}],
 )
 assert result.success is True
 session = await CodingSession.objects.aget(id=result.output["coding_session_id"])
 assert session.affected_files[0]["file_path"] == "legacy.py"
 assert "path" not in session.affected_files[0]
 plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
 assert plan.affected_files[0]["file_path"] == "legacy.py"
 @pytest.mark.asyncio
 async def test_create_coding_plan_dedupes_same_tech_plan_in_same_conversation(
 self, project, repository, conversation
 ):
 """同一 conversation 内连续两次相同 (plan, repo)：plan_id 相同，session_id 也相同。
 Phase：(coding_plan, repository) 部分唯一约束限制同时只能
 1 个 active session。create_coding_plan 检测到既有 active session
 时返回同一 session（真正幂等），不再创建新的 draft。
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
 # Phase：同 (plan, repo) → 幂等返回同 session_id
 assert first.output["coding_session_id"] == second.output["coding_session_id"]
 @pytest.mark.asyncio
 async def test_update_coding_plan_by_plan_id(
 self, project, repository, conversation
 ):
 """coding_plan_id 直接路由路径：plan 字段更新 + draft session 同步。"""
 from agents.tools.coding_tools import create_coding_plan, update_coding_plan
 from chat.models import CodingPlan, CodingSession
 created = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## 原方案",
 affected_files=[{"file_path": "old.py", "change_type": "modify"}],
 )
 plan_id = created.output["coding_plan_id"]
 session_id = created.output["coding_session_id"]
 result = await update_coding_plan(
 coding_plan_id=plan_id,
 tech_plan="## 新方案",
 affected_files=[{"file_path": "new.py", "change_type": "add"}],
 )
 assert result.success is True
 assert result.output["coding_plan_id"] == plan_id
 assert result.output["synced_sessions_count"] >= 1
 plan = await CodingPlan.objects.aget(id=plan_id)
 assert plan.tech_plan == "## 新方案"
 assert plan.affected_files[0]["file_path"] == "new.py"
 session = await CodingSession.objects.aget(id=session_id)
 assert session.tech_plan == "## 新方案"
 assert session.affected_files[0]["file_path"] == "new.py"
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
 session_id = created.output["coding_session_id"]
 result = await update_coding_plan(
 session_id=session_id,
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
 affected_files=,
 )
 assert result.success is False
 assert "coding_plan_id" in result.error
 assert "session_id" in result.error
 @pytest.mark.asyncio
 async def test_update_coding_plan_does_not_touch_running_sessions(
 self, project, repository, conversation
 ):
 """plan 关联 1 draft + 1 running 时，update 只同步 draft，不污染 running。
 Phase：(coding_plan, repository) 部分唯一约束限制同时只能
 1 个 active session；本用例通过创建第二个 Repository 模拟多仓 fan-out
 让 draft 与 running 落在不同 repo 上，规避 unique_active_plan_repo。
 """
 from agents.tools.coding_tools import create_coding_plan, update_coding_plan
 from chat.models import CodingPlan, CodingSession
 from repositories.models import Repository
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
 draft_session_id = created.output["coding_session_id"]
 plan = await CodingPlan.objects.aget(id=plan_id)
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
 draft_session = await CodingSession.objects.aget(id=draft_session_id)
 assert draft_session.tech_plan == "## 更新内容"
 running_session_refreshed = await CodingSession.objects.aget(id=running_session.id)
 # running 的 deprecated 字段保留旧值不动
 assert running_session_refreshed.tech_plan == "## 同方案 fan-out"
# ============================================================================
# 工具注册测试
# ============================================================================
def test_coding_tools_registered_in_registry:
 """验证 coding_tools 模块的 @tool 已注册到全局 _tool_registry。"""
 import agents.tools.coding_tools # noqa: F401
 from agents.tools.base import _tool_registry
 assert "create_coding_plan" in _tool_registry
 assert "update_coding_plan" in _tool_registry
@pytest.mark.asyncio
async def test_chat_runner_get_tool_names_gates_deep_analysis:
 """`chat_runner._get_tool_names(force_deep_analysis=False)` 必不返回 deep_analysis。
 防止后续代码改动重新把 deep_analysis 加回默认列表（这正是历史 bug：
 LLM 在普通模式被 prompt 诱导自主调 deep_analysis）。
 """
 from unittest.mock import AsyncMock, MagicMock, patch
 from agents.chat_runner import _get_tool_names
 fake_qs = MagicMock
 fake_qs.aexists = AsyncMock(return_value=True) # has_indexed=True
 with patch("agents.chat_runner.Repository.objects.filter", return_value=fake_qs):
 normal = await _get_tool_names("space-1", force_deep_analysis=False)
 forced = await _get_tool_names("space-1", force_deep_analysis=True)
 assert "deep_analysis" not in normal, (
 "默认模式必须闸住 deep_analysis；当前列表："
 f"{sorted(normal)}"
 )
 assert "deep_analysis" in forced
 assert "search_repository_code" in normal # 普通检索工具仍需暴露
def test_coding_tools_in_indexed_tool_names:
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
 Phase Task 7: async 化 + 强制 fallback 路径（避免依赖 DB seed）。
 """
 from chat.conversation_service import _build_system_prompt
 monkeypatch.setenv(
 "PROMPT_CENTER_DISABLED_KEYS",
 "chat.system.developer,chat.strategy.default,chat.coding_guidance",
 )
 prompt = await _build_system_prompt("Test Project", "test-uuid", "developer")
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
# Phase：create_coding_plan recommended_repository_ids 测试
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
 @pytest.mark.asyncio
 async def test_explicit_ids_are_persisted_to_plan(
 self, project, repository, conversation
 ):
 from agents.tools.coding_tools import create_coding_plan
 from chat.models import CodingPlan
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
 from chat.models import CodingPlan, RepositoryRoutingTrace
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
 from chat.models import CodingPlan, RepositoryRoutingTrace
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
 "selected_by_user_final": True, # user 改选
 },
 ],
 threshold=0.5,
 triggered_by=RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE,
 )
 # other_repository 不属于 space 校验：先加进 project（让 inferred 可校验）
 # 我们这里只验证 trace_inferred 取到了两条；不验证它们都属于 space
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
 async def test_no_trace_no_explicit_returns_empty_recommended(
 self, project, repository, conversation
 ):
 from agents.tools.coding_tools import create_coding_plan
 from chat.models import CodingPlan
 result = await create_coding_plan(
 space_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(repository.id),
 tech_plan="## empty rec",
 affected_files=[{"path": "x.py", "change_type": "modify"}],
 )
 assert result.success is True
 assert result.output["recommended_source"] == "empty"
 assert result.output["recommended_repository_ids"] ==
 plan = await CodingPlan.objects.aget(id=result.output["coding_plan_id"])
 assert plan.recommended_repository_ids ==
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
