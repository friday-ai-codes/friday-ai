"""coding_tools 单元测试 — create_coding_plan / update_coding_plan @tool。"""
import uuid
import pytest
from chat.models import CodingSession, Conversation
from projects.models import Project
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
 project_id=str(project.id),
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
 project_id=str(project.id),
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
 assert session.affected_files[0]["path"] == "src/a.py"
 @pytest.mark.asyncio
 async def test_create_coding_plan_project_not_found(
 self, repository, conversation
 ):
 """传入不存在的 project_id，返回 success=False。"""
 from agents.tools.coding_tools import create_coding_plan
 fake_id = str(uuid.uuid4)
 result = await create_coding_plan(
 project_id=fake_id,
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
 project_id=str(project.id),
 conversation_id=str(conversation.id),
 repository_id=str(other_repository.id),
 tech_plan="## 方案",
 affected_files=,
 )
 assert result.success is False
 assert "error" is not None
# ============================================================================
# update_coding_plan 测试
# ============================================================================
@pytest.fixture
def draft_coding_session(conversation, repository):
 """创建 draft 状态的 CodingSession 供 update 测试使用。"""
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 初始方案",
 affected_files=[{"path": "src/old.py", "change_type": "modify"}],
 branch_name="coding-test1234",
 )
@pytest.mark.django_db(transaction=True)
class TestUpdateCodingPlan:
 """update_coding_plan @tool 测试。"""
 @pytest.mark.asyncio
 async def test_update_coding_plan_success(self, draft_coding_session):
 """更新 draft session 的 tech_plan，revision_count 从 0 递增到 1。"""
 from agents.tools.coding_tools import update_coding_plan
 assert draft_coding_session.revision_count == 0
 result = await update_coding_plan(
 session_id=str(draft_coding_session.id),
 tech_plan="## 更新后方案\n- 新步骤",
 affected_files=[{"path": "src/new.py", "change_type": "add"}],
 )
 assert result.success is True
 assert result.output["revision_count"] == 1
 # 验证数据库
 await draft_coding_session.arefresh_from_db
 assert draft_coding_session.tech_plan == "## 更新后方案\n- 新步骤"
 assert draft_coding_session.revision_count == 1
 @pytest.mark.asyncio
 async def test_update_coding_plan_non_draft_error(self, draft_coding_session):
 """非 draft 状态 session 不可更新方案。"""
 from agents.tools.coding_tools import update_coding_plan
 # 将 session 改为 confirmed
 draft_coding_session.status = CodingSession.Status.CONFIRMED
 await draft_coding_session.asave(update_fields=["status"])
 result = await update_coding_plan(
 session_id=str(draft_coding_session.id),
 tech_plan="## 更新",
 affected_files=,
 )
 assert result.success is False
 assert "草稿" in result.error or "draft" in result.error.lower
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
# ============================================================================
# 工具注册测试
# ============================================================================
def test_coding_tools_registered_in_registry:
 """验证 coding_tools 模块的 @tool 已注册到全局 _tool_registry。"""
 import agents.tools.coding_tools # noqa: F401
 from agents.tools.base import _tool_registry
 assert "create_coding_plan" in _tool_registry
 assert "update_coding_plan" in _tool_registry
def test_coding_tools_in_full_tool_names:
 """验证 chat_runner._FULL_TOOL_NAMES 包含 coding tools。"""
 from agents.chat_runner import _FULL_TOOL_NAMES
 assert "create_coding_plan" in _FULL_TOOL_NAMES
 assert "update_coding_plan" in _FULL_TOOL_NAMES
# ============================================================================
# system prompt + _get_tool_names 测试
# ============================================================================
def test_system_prompt_contains_coding_guidance:
 """验证 system prompt 包含编码意图识别指引。"""
 from chat.conversation_service import _build_system_prompt
 prompt = _build_system_prompt("Test Project", "test-uuid", "developer")
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
