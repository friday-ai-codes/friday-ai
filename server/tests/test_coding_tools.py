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
