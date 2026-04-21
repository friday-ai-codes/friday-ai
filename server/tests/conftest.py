"""pytest-django 测试配置和 fixtures。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
# adrf 0.1.12 兼容性补丁（需在 Django 加载前执行）
from core.patches import patch_asyncio_iscoroutinefunction
patch_asyncio_iscoroutinefunction
import pytest # noqa: E402
from django.contrib.auth import get_user_model # noqa: E402
from django.core.cache import cache as django_cache # noqa: E402
from rest_framework.test import APIClient # noqa: E402
from permissions.models import ProjectMembership, ProjectRole # noqa: E402
from projects.models import Project # noqa: E402
from repositories.models import Repository # noqa: E402
# Register E2E mock fixtures for auto-discovery
pytest_plugins = [
 "tests.e2e.fixtures.mock_services",
]
User = get_user_model
# ============================================================================
# Cache Cleanup — 防止 throttle 等缓存在测试间泄漏
# ============================================================================
@pytest.fixture(autouse=True)
def _disable_scheduler_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
 """Phase：pytest 下关闭 APScheduler，避免 BackgroundScheduler
 起后台线程污染测试（T- Availability mitigation）。
 生产路径 `python manage.py runapscheduler` 不受影响；此 fixture 仅保护 pytest。
 沿用现有 FF_ENABLE_SCHEDULER 标志（PATTERNS 关键分歧 B：禁止新增 SCHEDULER_ENABLED）。
 """
 from django.conf import settings
 monkeypatch.setattr(settings, "FF_ENABLE_SCHEDULER", False, raising=False)
@pytest.fixture(autouse=True)
def _clear_throttle_cache:
 """每个测试前后清理 Django 缓存，并放宽 throttle 限速，避免非 throttle 测试被误拦截。
 SimpleRateThrottle.THROTTLE_RATES 是类变量（模块加载时评估），
 修改 settings.REST_FRAMEWORK 不会生效，需要直接 patch 类变量。
 """
 from accounts.throttles import LoginRateThrottle, RefreshRateThrottle
 # 保存原始 rate（如果有的话）
 orig_login_rate = getattr(LoginRateThrottle, "rate", None)
 orig_refresh_rate = getattr(RefreshRateThrottle, "rate", None)
 orig_login_throttle_rates = LoginRateThrottle.THROTTLE_RATES.copy
 orig_refresh_throttle_rates = RefreshRateThrottle.THROTTLE_RATES.copy
 # 放宽限速——非 throttle 专项测试不受影响
 relaxed = {"auth_login": "1000/min", "auth_refresh": "1000/min"}
 LoginRateThrottle.THROTTLE_RATES = relaxed
 RefreshRateThrottle.THROTTLE_RATES = relaxed
 django_cache.clear
 yield
 django_cache.clear
 # 恢复原始值
 LoginRateThrottle.THROTTLE_RATES = orig_login_throttle_rates
 RefreshRateThrottle.THROTTLE_RATES = orig_refresh_throttle_rates
 if orig_login_rate is not None:
 LoginRateThrottle.rate = orig_login_rate
 if orig_refresh_rate is not None:
 RefreshRateThrottle.rate = orig_refresh_rate
# ============================================================================
# API Client Fixtures
# ============================================================================
@pytest.fixture
def api_client:
 """创建未认证的 API 客户端。"""
 return APIClient
@pytest.fixture
def authenticated_client(api_client, user):
 """创建已认证的 API 客户端。"""
 api_client.force_authenticate(user=user)
 return api_client
# ============================================================================
# User Fixtures
# ============================================================================
@pytest.fixture
def user(db):
 """创建测试用户。"""
 return User.objects.create_user(
 username="testuser",
 email="test@example.com",
 password="testpassword123",
 )
@pytest.fixture
def admin_user(db):
 """创建管理员用户。"""
 return User.objects.create_superuser(
 username="admin",
 email="admin@example.com",
 password="adminpassword123",
 )
# ============================================================================
# Repository Fixtures
# ============================================================================
@pytest.fixture
def repository(db):
 """创建测试仓库。"""
 return Repository.objects.create(
 name="Test Repo",
 git_url="https://github.com/test/repo.git",
 git_platform="github",
 default_branch="main",
 )
@pytest.fixture
def repository_with_credential(db, repository):
 """创建带凭据的测试仓库。"""
 from common.encryption import encrypt_value
 from repositories.models import AuthType, GitCredential
 GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value("GITHUB_TOKEN_PLACEHOLDER"),
 )
 return repository
# ============================================================================
# Project Fixtures
# ============================================================================
@pytest.fixture
def project(db, repository):
 """创建测试项目（关联仓库）。"""
 proj = Project.objects.create(
 name="Test Project",
 description="A test project",
 feishu_project_key="test-project-key",
 feishu_webhook_token="test-webhook-token",
 )
 proj.repositories.add(repository)
 return proj
@pytest.fixture
def project_without_repo(db):
 """创建无仓库的测试项目。"""
 return Project.objects.create(
 name="Project Without Repo",
 feishu_project_key="no-repo-project-key",
 )
# ============================================================================
# URL Helper Fixtures
# ============================================================================
@pytest.fixture
def urls:
 """提供常用 URL 的辅助 fixture。"""
 from django.urls import reverse
 class URLs:
 # Auth URLs
 login = reverse("login")
 logout = reverse("logout")
 refresh = reverse("refresh")
 me = reverse("me")
 change_password = reverse("change-password")
 # Health
 health = reverse("health")
 # Settings
 settings_list = reverse("settings-list")
 @staticmethod
 def settings_detail(key):
 return reverse("settings-detail", args=[key])
 # Projects
 project_list = reverse("project-list")
 @staticmethod
 def project_detail(project_id):
 return reverse("project-detail", args=[project_id])
 @staticmethod
 def project_repositories(project_id):
 return f"/api/projects/{project_id}/repositories/"
 @staticmethod
 def project_link_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}/"
 @staticmethod
 def project_unlink_repository(project_id, repo_id):
 return f"/api/projects/{project_id}/repositories/{repo_id}/"
 @staticmethod
 def project_claude_config(project_id):
 return f"/api/projects/{project_id}/claude-config/"
 # Repositories
 repository_list = reverse("repository-list")
 @staticmethod
 def repository_detail(repo_id):
 return reverse("repository-detail", args=[repo_id])
 @staticmethod
 def repository_credential(repo_id):
 return reverse("repository-credential", args=[repo_id])
 # Feishu webhooks
 feishu_webhook = "/api/feishu/webhook/"
 return URLs
# ============================================================================
# Multi-Role User Fixtures (Phase: 权限引擎)
# ============================================================================
@pytest.fixture
def member_user(db):
 """创建 member 角色测试用户。"""
 return User.objects.create_user(
 username="member_user",
 email="member@example.com",
 password="memberpassword123",
 )
@pytest.fixture
def viewer_user(db):
 """创建 viewer 角色测试用户。"""
 return User.objects.create_user(
 username="viewer_user",
 email="viewer@example.com",
 password="viewerpassword123",
 )
@pytest.fixture
def other_user(db):
 """创建非任何项目成员的用户。"""
 return User.objects.create_user(
 username="other_user",
 email="other@example.com",
 password="otherpassword123",
 )
@pytest.fixture
def second_project(db):
 """创建第二个测试项目。"""
 return Project.objects.create(
 name="Second Project",
 description="A second test project",
 feishu_project_key="second-project-key",
 )
@pytest.fixture
def project_memberships(db, project, user, member_user, viewer_user):
 """创建项目成员关系。
 - user → project admin
 - member_user → project member
 - viewer_user → project viewer
 - admin_user 是 superuser，不需要 membership
 """
 admin_membership = ProjectMembership.objects.create(
 user=user, project=project, role=ProjectRole.ADMIN
 )
 member_membership = ProjectMembership.objects.create(
 user=member_user, project=project, role=ProjectRole.MEMBER
 )
 viewer_membership = ProjectMembership.objects.create(
 user=viewer_user, project=project, role=ProjectRole.VIEWER
 )
 return {
 "admin": admin_membership,
 "member": member_membership,
 "viewer": viewer_membership,
 }
@pytest.fixture
def authenticated_member_client(api_client, member_user):
 """创建 member 角色已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=member_user)
 return client
@pytest.fixture
def authenticated_viewer_client(api_client, viewer_user):
 """创建 viewer 角色已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=viewer_user)
 return client
@pytest.fixture
def authenticated_admin_client(api_client, admin_user):
 """创建 superuser 已认证客户端。"""
 client = APIClient
 client.force_authenticate(user=admin_user)
 return client
# ============================================================================
# Phase Wave：AI 节点测试公共 fixture（Q6 决策落地 / 弥补）
#
# ~ 所有新建 AI 节点测试统一引用以下 4 fixture，禁止重复定义。
# 违反由 静态扫描拦截。
# ============================================================================
@pytest.fixture
def fake_chat_model_factory(monkeypatch):
 """参数化 FakeChatModel factory fixture（ 测试脚手架）。
 返回一个 callable，生产 FakeChatModel 并自动注入 build_chat_model seam 到
 所有 AI 节点模块的 build_chat_model 符号（双 patch 模式；Pitfall #5 规避）。
 Usage:
 async def test_xxx(fake_chat_model_factory):
 fake = fake_chat_model_factory(
 responses=["ok"],
 tool_calls=[[{"name": "echo", "args": {}, "id": "c1"}]],
 usage_metadata={"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
 )
 # seam 已注入；直接构造 runner / 节点即可
 Seam 注入点（按优先级）：
 - agents.llm_factory.build_chat_model（始终）
 - agents.langchain_runner.build_chat_model（始终）
 - workflows.nodes.ai.prompt.build_chat_model（若存在）
 - workflows.nodes.ai.variable_extractor.build_chat_model（若存在）
 """
 from typing import Any, Sequence
 from tests.helpers.fake_chat_model import FakeChatModel
 def _factory(
 *,
 responses: Sequence[str] = ("done",),
 tool_calls: Sequence[Sequence[dict[str, Any]]] | None = None,
 usage_metadata: dict[str, int] | None = None,
 ) -> FakeChatModel:
 fake = FakeChatModel(
 responses=responses,
 tool_calls=tool_calls or,
 usage_metadata=usage_metadata
 or {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
 )
 # 核心 seam（始终有效）
 monkeypatch.setattr(
 "agents.llm_factory.build_chat_model",
 lambda *a, **kw: fake,
 )
 monkeypatch.setattr(
 "agents.langchain_runner.build_chat_model",
 lambda *a, **kw: fake,
 raising=False,
 )
 # 节点级可选 seam（Phase Wave+ 才会存在；raising=False 兼容缺失）
 for mod_path in (
 "workflows.nodes.ai.prompt.build_chat_model",
 "workflows.nodes.ai.variable_extractor.build_chat_model",
 "workflows.nodes.ai.base_agent.build_chat_model",
 ):
 monkeypatch.setattr(
 mod_path, lambda *a, **kw: fake, raising=False
 )
 return fake
 return _factory
@pytest.fixture
def mock_aresolve_ok(monkeypatch):
 """注入 ProviderConfigService.aresolve_or_error stub 返回合法 ResolvedProviderConfig。
 Usage:
 async def test_xxx(mock_aresolve_ok):
 resolved = mock_aresolve_ok(source="system", provider_type="anthropic")
 # 之后的 aresolve_or_error 调用都会返回该 resolved 对象
 参数默认值使用 Anthropic system-scope，满足 ~08 多数测试需求；传入
 `provider_type="openai_chat"` 可切 OpenAI 链路。
 """
 def _setup(
 *,
 source: str = "system",
 provider_type: str = "anthropic",
 api_key: str = "sk-fake",
 base_url: str = "https://api.anthropic.com",
 ):
 from services.provider_config import (
 ProviderType,
 ResolvedProviderConfig,
 )
 pt = (
 provider_type
 if isinstance(provider_type, ProviderType)
 else ProviderType(provider_type)
 )
 resolved = ResolvedProviderConfig(
 provider_type=pt,
 api_key=api_key,
 base_url=base_url,
 source=source,
 )
 async def _stub(node_config=None, conversation=None, project=None):
 return resolved
 monkeypatch.setattr(
 "services.provider_config.ProviderConfigService.aresolve_or_error",
 _stub,
 )
 return resolved
 return _setup
@pytest.fixture
def mock_aresolve_missing(monkeypatch):
 """注入 ProviderConfigService.aresolve_or_error stub 返回 ProviderMissingError。
 Usage:
 async def test_xxx(mock_aresolve_missing):
 mock_aresolve_missing(missing_provider="openai_chat")
 # 之后 aresolve_or_error 调用都返回 ProviderMissingError（ Result 模式）
 上层节点（AIAgentBaseNode / AIPromptNode 等）应基于 isinstance 分支转
 NodeResult(status="failed") + 结构化 error。
 """
 def _setup(
 *,
 missing_provider: str = "openai_chat",
 recommended_action: str = "请在系统设置中配置 OpenAI 凭证",
 source_attempted: str = "system",
 ):
 from services.provider_config import ProviderMissingError
 err = ProviderMissingError(
 missing_provider=missing_provider,
 recommended_action=recommended_action,
 source_attempted=source_attempted,
 )
 async def _stub(node_config=None, conversation=None, project=None):
 return err
 monkeypatch.setattr(
 "services.provider_config.ProviderConfigService.aresolve_or_error",
 _stub,
 )
 return err
 return _setup
# ============================================================================
# Phase Plan：Provider 凭证测试公共 fixture
#
# 4 用户（system_admin + project_a_admin/member/viewer + project_b_admin）
# + 2 独立项目（project_a / project_b）+ 3 凭证（system + project_a + project_b）
# + async_client。CONTEXT 命名锁定， 与 work-item 共享消费。
#
# 与既有 `project` / `admin_user` fixture 不冲突（不同命名空间）。
# ============================================================================
@pytest.fixture
def system_admin_user(db):
 """Phase：系统级 superuser 用户。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 return User.objects.create_user(
 username=f"sysadmin_{suffix}",
 email=f"sysadmin_{suffix}@test.local",
 password="test-password",
 is_superuser=True,
 is_staff=True,
 )
@pytest.fixture
def project_a(db):
 """Phase：独立项目 A（避开既有 `project` fixture 的 repository 依赖）。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 return Project.objects.create(
 name=f"project-a-{suffix}",
 feishu_project_key=f"p229-pa-{suffix}",
 )
@pytest.fixture
def project_b(db):
 """Phase：独立项目 B（跨项目场景用）。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 return Project.objects.create(
 name=f"project-b-{suffix}",
 feishu_project_key=f"p229-pb-{suffix}",
 )
def _add_membership(project, user, role):
 """内部 helper：按 ProjectRole 枚举添加成员关系。"""
 ProjectMembership.objects.create(
 project=project,
 user=user,
 role=role,
 )
@pytest.fixture
def project_a_admin_user(db, project_a):
 """Phase：项目 A 的 ADMIN 角色用户。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 u = User.objects.create_user(
 username=f"pa_admin_{suffix}",
 email=f"pa_admin_{suffix}@test.local",
 password="test-password",
 )
 _add_membership(project_a, u, ProjectRole.ADMIN)
 return u
@pytest.fixture
def project_a_member_user(db, project_a):
 """Phase：项目 A 的 MEMBER 角色用户。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 u = User.objects.create_user(
 username=f"pa_member_{suffix}",
 email=f"pa_member_{suffix}@test.local",
 password="test-password",
 )
 _add_membership(project_a, u, ProjectRole.MEMBER)
 return u
@pytest.fixture
def project_a_viewer_user(db, project_a):
 """Phase：项目 A 的 VIEWER 角色用户。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 u = User.objects.create_user(
 username=f"pa_viewer_{suffix}",
 email=f"pa_viewer_{suffix}@test.local",
 password="test-password",
 )
 _add_membership(project_a, u, ProjectRole.VIEWER)
 return u
@pytest.fixture
def project_b_admin_user(db, project_b):
 """Phase：项目 B 的 ADMIN 角色用户（跨项目越权测试）。"""
 from uuid import uuid4
 suffix = uuid4.hex[:8]
 u = User.objects.create_user(
 username=f"pb_admin_{suffix}",
 email=f"pb_admin_{suffix}@test.local",
 password="test-password",
 )
 _add_membership(project_b, u, ProjectRole.ADMIN)
 return u
@pytest.fixture
def system_default_anthropic_credential(db):
 """Phase：系统级 Anthropic 凭证（scope='system'，scope_id=None）。"""
 import json
 from uuid import uuid4
 from common.encryption import encrypt_value
 from system.models import ProviderCredential
 suffix = uuid4.hex[:8]
 return ProviderCredential.objects.create(
 provider_type="anthropic",
 name=f"sys-default-{suffix}",
 scope="system",
 scope_id=None,
 encrypted_config=encrypt_value(
 json.dumps(
 {
 "api_key": "sk-test-placeholder",
 "base_url": "https://api.anthropic.com",
 }
 )
 ),
 is_active=True,
 )
@pytest.fixture
def project_a_anthropic_credential(db, project_a):
 """Phase：项目 A 的 Anthropic 凭证（scope='project'，scope_id=project_a.id）。"""
 import json
 from uuid import uuid4
 from common.encryption import encrypt_value
 from system.models import ProviderCredential
 suffix = uuid4.hex[:8]
 return ProviderCredential.objects.create(
 provider_type="anthropic",
 name=f"pa-anth-{suffix}",
 scope="project",
 scope_id=project_a.id,
 encrypted_config=encrypt_value(
 json.dumps(
 {
 "api_key": "sk-ant-proj-a-testing",
 "base_url": "https://api.anthropic.com",
 }
 )
 ),
 is_active=True,
 )
@pytest.fixture
def project_b_openai_credential(db, project_b):
 """Phase：项目 B 的 OpenAI 凭证（跨项目用例）。"""
 import json
 from uuid import uuid4
 from common.encryption import encrypt_value
 from system.models import ProviderCredential
 suffix = uuid4.hex[:8]
 return ProviderCredential.objects.create(
 provider_type="openai_chat",
 name=f"pb-oai-{suffix}",
 scope="project",
 scope_id=project_b.id,
 encrypted_config=encrypt_value(
 json.dumps(
 {
 "api_key": "sk-test-placeholder",
 "base_url": "https://api.openai.com/v1",
 }
 )
 ),
 is_active=True,
 )
@pytest.fixture
def async_client:
 """Phase：未认证的 APIClient（供矩阵测试 force_authenticate 按角色注入）。"""
 return APIClient
# ============================================================================
# Phase Wave：AI 节点测试公共 fixture（Q6 决策落地 / 弥补）
# ============================================================================
@pytest.fixture
def make_minimal_context:
 """构造最小 ExecutionContext 供 AI 节点 execute 调用。
 Usage:
 def test_xxx(make_minimal_context):
 ctx = make_minimal_context(
 node_config={"user_prompt": "hi"},
 execution_id="test-exec",
 node_id="n1",
 )
 result = await node.execute(ctx)
 默认值：
 - execution_id="test-exec-id-12345"（固定便于 字节级 hash 稳定）
 - node_id="n1"
 - input_data={} / workflow_context={} / previous_outputs={} / trigger_data={}
 不注入 workflow_execution / node_execution（execute 路径在大多数节点可 None）。
 ExecutionContext 真实签名来自 workflows/nodes/base.py：
 execution_id / node_id / node_config / input_data / workflow_context /
 previous_outputs / trigger_data / workflow_execution / node_execution
 """
 from typing import Any
 def _make(
 *,
 node_config: dict[str, Any] | None = None,
 execution_id: str = "test-exec-id-12345",
 node_id: str = "n1",
 input_data: dict[str, Any] | None = None,
 workflow_context: dict[str, Any] | None = None,
 previous_outputs: dict[str, dict[str, Any]] | None = None,
 trigger_data: dict[str, Any] | None = None,
 workflow_execution: Any = None,
 node_execution: Any = None,
 ):
 from workflows.nodes.base import ExecutionContext
 return ExecutionContext(
 execution_id=execution_id,
 node_id=node_id,
 node_config=node_config or {},
 input_data=input_data or {},
 workflow_context=workflow_context or {},
 previous_outputs=previous_outputs or {},
 trigger_data=trigger_data or {},
 workflow_execution=workflow_execution,
 node_execution=node_execution,
 )
 return _make
# ============= Phase Wave fixtures =============
#
# Plan 新增 5 个 factory fixture，供 Plan 的后端测试直接注入。
# 所有 fixture 遵循 developer-notes.md 规范：
# - 函数附类型注解
# - docstring 中文 + 列参数语义
# - 使用 `apps.get_model(...)` 避免 Django app registry race（T- 缓解）
#
# 注意：部分 fixture 引用的字段（Conversation.provider_credential_id /
# Conversation.status / Project.default_provider_credential_id / ResolvedProviderChain）
# 尚未落地，**当前 Plan/06 尚未执行**；fixture 实现采用 forward-compatible 写法：
# - 工厂通过 **overrides 透传字段，避免字段不存在时强设默认值
# - resolve_chain_builder 暂以 dict 代替 dataclass，Plan 完成后可升级 type hint
# =====================================================
@pytest.fixture
def frozen_conversation_factory(db, project):
 """Phase：创建 status ∈ {active, completed, stopped, error} 的 Conversation。
 Plan pin 冻结用例的主入口 fixture。
 Args:
 status: 对话状态，默认 "completed"（冻结态）。可选 active/completed/stopped/error。
 **overrides: 其余字段 override（title / model / provider_type / provider_credential_id ...）
 Usage:
 def test_frozen_cannot_repin(frozen_conversation_factory):
 conv = frozen_conversation_factory(status="completed")
 # 此后 API 修改 conv.provider_credential_id 应 400
 实现说明：
 - 使用 apps.get_model 防 app registry race
 - status 字段 Plan Wave 新增；若当前模型未含则通过 setattr 兼容写入
 （DB 列可能缺失，仅影响未 migrate 的本地环境）
 - project 字段复用既有 `project` fixture，保证 Conversation 必填 FK 满足
 """
 from typing import Any
 from django.apps import apps
 def _factory(*, status: str = "completed", **overrides: Any):
 Conversation = apps.get_model("chat", "Conversation")
 # 避免触发未迁移的 status 列（Plan W0 前）
 status_kwarg: dict[str, Any] = {}
 if "status" in {f.name for f in Conversation._meta.get_fields}:
 status_kwarg["status"] = status
 defaults: dict[str, Any] = {
 "project": overrides.pop("project", project),
 "title": overrides.pop("title", f"frozen-{status}"),
 "model": overrides.pop("model", ""),
 }
 defaults.update(status_kwarg)
 defaults.update(overrides)
 return Conversation.objects.create(**defaults)
 return _factory
@pytest.fixture
def execution_with_snapshot_factory(db, project):
 """Phase：创建 WorkflowExecution 并把 node_snapshots 写入 context JSONField。
 Args:
 node_snapshots: dict[str, dict]，形如
 {"node-1": {"provider_type": "anthropic", "model": "claude-3-5",
 "resolved_source": "project", "api_key_fingerprint": "..."}}
 **overrides: 其余字段（status / trigger_type / workflow ...）
 Usage:
 def test_replay_uses_snapshot(execution_with_snapshot_factory):
 ex = execution_with_snapshot_factory(node_snapshots={
 "n1": {"provider_type": "anthropic", "model": "claude-3-5-sonnet-20241022"},
 })
 assert ex.context["node_snapshots"]["n1"]["model"] == "claude-3-5-sonnet-20241022"
 实现说明：
 - context 是 JSONField（workflows/models/execution.py 实测）
 - workflow FK 由 caller 通过 `workflow=` override 传入；不传则创建最小 Workflow
 """
 from typing import Any
 from uuid import uuid4
 from django.apps import apps
 def _factory(
 *,
 node_snapshots: dict[str, dict] | None = None,
 **overrides: Any,
 ):
 WorkflowExecution = apps.get_model("workflows", "WorkflowExecution")
 Workflow = apps.get_model("workflows", "Workflow")
 workflow = overrides.pop("workflow", None)
 if workflow is None:
 workflow = Workflow.objects.create(
 name=f"wf-snapshot-{uuid4.hex[:8]}",
 project=project,
 )
 context = overrides.pop("context", {}) or {}
 if node_snapshots is not None:
 context["node_snapshots"] = node_snapshots
 defaults: dict[str, Any] = {
 "workflow": workflow,
 "project": project,
 "status": "completed",
 "trigger_type": "manual",
 "context": context,
 }
 defaults.update(overrides)
 return WorkflowExecution.objects.create(**defaults)
 return _factory
@pytest.fixture
def analytics_token_usage_factory(db):
 """Phase：批量创建 TokenUsage，按 provider_type 聚合统计用。
 Args:
 provider_type: "anthropic" | "openai_chat" | "openai_responses" | "gemini" | "ollama"
 count: 创建条数（默认 1）
 cost_usd: 单条成本（Decimal，默认 0.01）
 input_tokens: 单条 input token（默认 500）
 output_tokens: 单条 output token（默认 500）
 Returns:
 list[TokenUsage] — 新创建记录列表
 Usage:
 def test_group_by_provider(analytics_token_usage_factory):
 analytics_token_usage_factory(provider_type="anthropic", count=3)
 analytics_token_usage_factory(provider_type="openai_chat", count=2)
 # 之后 GET /analytics/overview/?group_by=provider_type 应返 2 组
 实现说明：
 - TokenUsage 必须挂 SubAgentSession FK；自动创建最小 SubAgentSession
 - 使用 apps.get_model 避免 direct import 导致的 circular import
 """
 from decimal import Decimal
 from typing import Any
 from uuid import uuid4
 from django.apps import apps
 def _factory(
 *,
 provider_type: str = "anthropic",
 count: int = 1,
 cost_usd: Decimal = Decimal("0.01"),
 input_tokens: int = 500,
 output_tokens: int = 500,
 model: str = "claude-3-5-sonnet-20241022",
 session: Any = None,
 ) -> list[Any]:
 TokenUsage = apps.get_model("subagent", "TokenUsage")
 SubAgentSession = apps.get_model("subagent", "SubAgentSession")
 AgentSession = apps.get_model("agents", "AgentSession")
 if session is None:
 # SubAgentSession 需要 main_session (AgentSession FK) + repo_url + task_type
 # Phase Plan Rule 1 bug fix：Plan stub 未创建 main_session 致 NOT NULL 失败
 main = AgentSession.objects.create(
 session_id=f"main-{uuid4.hex}",
 status=AgentSession.Status.COMPLETED,
 )
 session = SubAgentSession.objects.create(
 session_id=f"sess-{uuid4.hex}",
 main_session=main,
 repo_url="https://github.com/test/analytics.git",
 task_type=SubAgentSession.TaskType.CODING,
 )
 created: list[Any] =
 for _ in range(count):
 created.append(
 TokenUsage.objects.create(
 session=session,
 input_tokens=input_tokens,
 output_tokens=output_tokens,
 total_cost_usd=cost_usd,
 model=model,
 provider_type=provider_type,
 )
 )
 return created
 return _factory
@pytest.fixture
def sse_error_emitter:
 """Phase /：SSE ERROR 事件 payload 构造 helper。
 返回一个 dataclass-like 对象，暴露 3 个 method，每个返回结构化 SSE 事件 dict：
 - context_exceeded(estimated, max_tokens, model) →
 - provider_credential_missing(provider_type) →
 - generic(message) → 通用兜底
 Usage:
 def test_context_exceeded_payload(sse_error_emitter):
 evt = sse_error_emitter.context_exceeded(
 estimated=200000, max_tokens=150000, model="claude-3-5-sonnet",
 )
 assert evt["type"] == "error"
 assert evt["code"] == "context_window_exceeded"
 assert evt["data"]["exceeded_by"] == 50000
 Payload 形状锁定 work-item.md §SSE ERROR payload 契约。
 """
 from dataclasses import dataclass
 @dataclass
 class _SSEErrorEmitter:
 """SSE ERROR 事件 payload 工厂。"""
 def context_exceeded(
 self,
 *,
 estimated: int,
 max_tokens: int,
 model: str,
 ) -> dict:
 """：context_window_exceeded 结构化 payload。"""
 return {
 "type": "error",
 "code": "context_window_exceeded",
 "data": {
 "estimated_tokens": estimated,
 "max_tokens": max_tokens,
 "exceeded_by": max(0, estimated - max_tokens),
 "model": model,
 "recommended_actions": [
 "cleanup_history",
 "switch_larger_context_model",
 "trim_system_prompt",
 ],
 },
 }
 def provider_credential_missing(self, *, provider_type: str) -> dict:
 """：provider_credential_missing 结构化 payload。"""
 return {
 "type": "error",
 "code": "provider_credential_missing",
 "data": {
 "provider_type": provider_type,
 "recommended_actions": [
 "configure_credential",
 "switch_provider",
 ],
 },
 }
 def generic(self, *, message: str) -> dict:
 """通用兜底 ERROR payload。"""
 return {
 "type": "error",
 "code": "generic",
 "data": {"message": message},
 }
 return _SSEErrorEmitter
@pytest.fixture
def resolve_chain_builder:
 """Phase：构造四层 ResolvedProviderChain dict（Plan aresolve_with_chain 产出）。
 Args:
 winning_layer: "node" | "conversation" | "project" | "system"
 —— 标识哪一层解析命中（优先级：node > conversation > project > system）
 values: dict[str, str] | None — 可选 layer-specific override，形如
 {"node": "pc-node-id", "project": "pc-proj-id"}
 Returns:
 dict 形如 {
 "winning": {"source": winning_layer, "provider_type": "anthropic",
 "model": "claude-3-5", "credential_id": "..."},
 "chain": [
 {"layer": "node", "value": str | None, "active": bool},
 {"layer": "conversation", "value": str | None, "active": bool},
 {"layer": "project", "value": str | None, "active": bool},
 {"layer": "system", "value": str | None, "active": bool},
 ],
 }
 Usage:
 def test_api_returns_chain(resolve_chain_builder):
 chain = resolve_chain_builder(winning_layer="project")
 # 之后 API 响应 `resolved_provider.chain` 与 chain["chain"] 一致
 实现说明：
 - Plan 尚未落地 ResolvedProviderChain dataclass；当前以 dict 代替
 - Plan 完成后可把返回值替换为 services.provider_config.ResolvedProviderChain
 并升级 type hint
 """
 from typing import Literal
 def _factory(
 *,
 winning_layer: Literal["node", "conversation", "project", "system"] = "system",
 values: dict[str, str] | None = None,
 provider_type: str = "anthropic",
 model: str = "claude-3-5-sonnet-20241022",
 ) -> dict:
 layer_order = ["node", "conversation", "project", "system"]
 values = values or {}
 chain_entries =
 for layer in layer_order:
 chain_entries.append({
 "layer": layer,
 "value": values.get(layer),
 "active": layer == winning_layer,
 })
 return {
 "winning": {
 "source": winning_layer,
 "provider_type": provider_type,
 "model": model,
 "credential_id": values.get(winning_layer),
 },
 "chain": chain_entries,
 }
 return _factory
