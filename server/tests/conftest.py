"""pytest-django 测试配置和 fixtures。

使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""

# adrf 0.1.12 兼容性补丁（需在 Django 加载前执行）
from core.patches import patch_asyncio_iscoroutinefunction

patch_asyncio_iscoroutinefunction()

from pathlib import Path  # noqa: E402
from typing import Any, Callable  # noqa: E402

import pytest  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.cache import cache as django_cache  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from permissions.models import ProjectMembership, ProjectRole  # noqa: E402
from projects.models import Project  # noqa: E402
from repositories.models import Repository  # noqa: E402

# Register E2E mock fixtures for auto-discovery
pytest_plugins = [
    "tests.e2e.fixtures.mock_services",
]

User = get_user_model()


def pytest_sessionfinish(session, exitstatus):
    """session 收尾关闭 orchestration checkpointer 的 aiosqlite 连接。

    ``orchestration.checkpointer.get_checkpointer()`` 以进程级单例持有一个 aiosqlite
    连接，其 worker 线程是 **非 daemon**：pytest 全部用例跑完后，Python 解释器会在
    join 该线程处永久阻塞（本地卡死 / CI server-ci 跑满 6h 超时）。session 结束时
    显式关闭即可让解释器干净退出。失败仅记日志，绝不影响测试结论。
    """
    import asyncio

    try:
        from orchestration.checkpointer import close_checkpointer

        asyncio.run(close_checkpointer())
    except Exception:
        import logging

        logging.getLogger(__name__).exception("checkpointer session teardown failed")


# ============================================================================
# Cache Cleanup — 防止 throttle 等缓存在测试间泄漏
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_background_runner():
    """每个测试结束后等 background_runner in-flight 任务落地并拆掉 worker 线程。

    背景：services.background_runner 用独立 daemon 线程跑后台索引任务（修复
    `CurrentThreadExecutor already quit or is broken`）。worker 线程持有自己的
    数据库连接，写入不在 pytest-django 的 transaction 里 → 不会被 rollback
    清掉，会污染后续测试（典型表现：`test_list_repositories_empty` 莫名拿到
    上一个测试 worker 线程留下的 Repository 行）。

    autouse 保证每个测试结束都把 in-flight 任务等完 + 重启 worker，下个测试
    起步就是干净的。
    """
    yield
    try:
        from services import background_runner

        background_runner.wait_for_pending(timeout=5.0)
        background_runner._reset_for_tests()
    except Exception:
        # 测试 teardown 不应吞主测试结果——失败原因记日志即可
        import logging

        logging.getLogger(__name__).exception("background_runner teardown failed")


@pytest.fixture(autouse=True)
def _disable_scheduler_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """implementation contract：pytest 下关闭 APScheduler，避免 BackgroundScheduler
    起后台线程污染测试（security mitigation-03 Availability mitigation）。

    生产路径 `python manage.py runapscheduler` 不受影响；此 fixture 仅保护 pytest。
    沿用现有 FF_ENABLE_SCHEDULER 标志（PATTERNS 关键分歧 B：禁止新增 SCHEDULER_ENABLED）。
    """
    from django.conf import settings

    monkeypatch.setattr(settings, "FF_ENABLE_SCHEDULER", False, raising=False)


@pytest.fixture(autouse=True)
def _isolate_galaxy_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Galaxy 文件缓存目录指向每测试独立 tmp，避免测试间互相污染 / 写入 data/。"""
    from django.conf import settings

    monkeypatch.setattr(
        settings, "GALAXY_CACHE_DIR", tmp_path / "galaxy_cache", raising=False
    )


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """每个测试前后清理 Django 缓存，并放宽 throttle 限速，避免非 throttle 测试被误拦截。

    SimpleRateThrottle.THROTTLE_RATES 是类变量（模块加载时评估），
    修改 settings.REST_FRAMEWORK 不会生效，需要直接 patch 类变量。
    """
    from accounts.throttles import (
        LoginIPRateThrottle,
        LoginRateThrottle,
        RefreshRateThrottle,
    )

    throttle_classes = [LoginRateThrottle, LoginIPRateThrottle, RefreshRateThrottle]

    # 保存原始 rate / THROTTLE_RATES（如果有的话）
    originals = [
        (cls, getattr(cls, "rate", None), cls.THROTTLE_RATES.copy())
        for cls in throttle_classes
    ]

    # 放宽限速——非 throttle 专项测试不受影响
    relaxed = {
        "auth_login": "1000/min",
        "auth_login_ip": "1000/min",
        "auth_refresh": "1000/min",
    }
    for cls in throttle_classes:
        cls.THROTTLE_RATES = relaxed

    django_cache.clear()
    yield
    django_cache.clear()

    # 恢复原始值
    for cls, orig_rate, orig_throttle_rates in originals:
        cls.THROTTLE_RATES = orig_throttle_rates
        if orig_rate is not None:
            cls.rate = orig_rate


@pytest.fixture(autouse=True)
def _reset_procrastinate_tables(request):
    """postgres_queue 测试运行前清空 procrastinate 队列表，避免跨测试污染。

    procrastinate 经自有连接（PsycopgConnector / DjangoConnector）写
    ``procrastinate_jobs`` / ``procrastinate_workers`` 等表，这些写入不在
    pytest-django 的测试事务内，``transaction=True`` 的 flush 也未必把残留 job 与
    自增序列清干净 → 上个用例遗留的 ``todo`` job 会被下个用例的 worker 误领
    （典型表现：``test_forged_heartbeat_job_rescued_to_todo`` 期望领到自己 defer 的
    新 job，却拿到上个测试遗留的 ``fetched.id == 1`` 而失败）。

    仅对带 ``postgres_queue`` 标记的真实 Postgres 用例生效：运行前
    ``TRUNCATE ... RESTART IDENTITY CASCADE`` 现存的所有 ``procrastinate_*`` 表，
    保证每个用例从干净队列起步；非 postgres_queue / 非 Postgres 路径完全 no-op。
    """
    if request.node.get_closest_marker("postgres_queue") is None:
        yield
        return

    from django.db import connection

    try:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() "
                    "AND tablename LIKE 'procrastinate_%'"
                )
                tables = [row[0] for row in cursor.fetchall()]
                if tables:
                    quoted = ", ".join(f'"{name}"' for name in tables)
                    cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
    except Exception:
        # 清理失败不应吞主测试结果——记日志即可
        import logging

        logging.getLogger(__name__).exception("procrastinate pre-clean failed")

    yield


# ============================================================================
# API Client Fixtures
# ============================================================================


@pytest.fixture
def api_client():
    """创建未认证的 API 客户端。"""
    return APIClient()


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
# Phase 08（对话/会话用户隔离）测试 fixtures
#
# 供 tests/test_conversation_isolation.py 复现 IDOR（用户 B 直取用户 A 会话）。
# 形态与 test_conversation_integration.py 的 user_and_token / auth_headers
# 一致：async 创建用户 + sync_to_async(RefreshToken.for_user) 铸 JWT。
# 仅新增，不改动既有 fixture 语义（per 08-01 Task 1 acceptance）。
# ============================================================================


@pytest.fixture
def second_user(db):
    """隔离测试用：二号普通用户（非 superuser），跨用户越权样本。"""
    return User.objects.create_user(
        username="iso_second_user",
        email="iso_second@example.com",
        password="iso-second-pass-123",
    )


@pytest.fixture
async def second_user_and_token(db):
    """隔离测试用：二号用户 + JWT access token（async）。

    返回 ``(user, access_token_str)``，供二号用户以 Bearer 头发认证请求，
    复现「B 持自己 JWT 直取 A 会话 id」的越权访问。
    """
    from asgiref.sync import sync_to_async
    from rest_framework_simplejwt.tokens import RefreshToken

    user = await User.objects.acreate_user(
        username="iso_second_user_jwt",
        password="iso-second-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def second_auth_headers(second_user_and_token):
    """二号用户 Bearer Authorization 头 dict。"""
    _, access_token = second_user_and_token
    return {"authorization": f"Bearer {access_token}"}


@pytest.fixture
async def superuser_and_token(db):
    """隔离测试用：superuser + JWT（async），验证 ISO-03 管理员无特权 bypass。"""
    from asgiref.sync import sync_to_async
    from rest_framework_simplejwt.tokens import RefreshToken

    user = await User.objects.acreate_superuser(
        username="iso_superuser_jwt",
        email="iso_superuser@example.com",
        password="iso-superuser-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def superuser_auth_headers(superuser_and_token):
    """superuser Bearer Authorization 头 dict。"""
    _, access_token = superuser_and_token
    return {"authorization": f"Bearer {access_token}"}


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
        encrypted_token=encrypt_value("ghp_test_token_12345"),
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
def urls():
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

        # Spaces
        space_list = reverse("space-list")

        @staticmethod
        def space_detail(space_id):
            return reverse("space-detail", args=[space_id])

        @staticmethod
        def space_repositories(space_id):
            return f"/api/spaces/{space_id}/repositories/"

        @staticmethod
        def space_link_repository(space_id, repo_id):
            return f"/api/spaces/{space_id}/repositories/{repo_id}/"

        @staticmethod
        def space_unlink_repository(space_id, repo_id):
            return f"/api/spaces/{space_id}/repositories/{repo_id}/"

        # implementation（contract）：project_claude_config helper 已随 v8.1
        # /api/spaces/<id>/claude-config/ 端点硬删一并移除。

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

    return URLs()


# ============================================================================
# Multi-Role User Fixtures (权限引擎)
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
    client = APIClient()
    client.force_authenticate(user=member_user)
    return client


@pytest.fixture
def authenticated_viewer_client(api_client, viewer_user):
    """创建 viewer 角色已认证客户端。"""
    client = APIClient()
    client.force_authenticate(user=viewer_user)
    return client


@pytest.fixture
def authenticated_admin_client(api_client, admin_user):
    """创建 superuser 已认证客户端。"""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


# ============================================================================
# implementation Wave：AI 节点测试公共 fixture（Q6 决策落地 / work item 弥补）
#
# checkpoint ~ checkpoint 所有新建 AI 节点测试统一引用以下 4 fixture，禁止重复定义。
# 违反由 checkpoint 静态扫描拦截。
# ============================================================================


@pytest.fixture
def fake_chat_model_factory(monkeypatch):
    """参数化 FakeChatModel factory fixture（contract 测试脚手架）。

    返回一个 callable，生产 FakeChatModel 并自动注入 build_chat_model seam 到
    所有 AI 节点模块的 build_chat_model 符号（双 patch 模式；Pitfall #5 规避）。

    Usage::

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
            tool_calls=tool_calls or [],
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
        # 节点级可选 seam（implementation Wave+ 才会存在；raising=False 兼容缺失）
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

    Usage::

        async def test_xxx(mock_aresolve_ok):
            resolved = mock_aresolve_ok(source="system", provider_type="anthropic")
            # 之后的 aresolve_or_error 调用都会返回该 resolved 对象

    参数默认值使用 Anthropic system-scope，满足 checkpoint~08 多数测试需求；传入
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

    Usage::

        async def test_xxx(mock_aresolve_missing):
            mock_aresolve_missing(missing_provider="openai_chat")
            # 之后 aresolve_or_error 调用都返回 ProviderMissingError（contract Result 模式）

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
# Provider 凭证测试公共 fixture
#
# 4 用户（system_admin + project_a_admin/member/viewer + project_b_admin）
# + 2 独立项目（project_a / project_b）+ 3 凭证（system + project_a + project_b）
# + async_client。context contract 命名锁定，checkpoint 与 work-item 共享消费。
#
# 与既有 `project` / `admin_user` fixture 不冲突（不同命名空间）。
# ============================================================================


@pytest.fixture
def system_admin_user(db):
    """implementation contract：系统级 superuser 用户。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    return User.objects.create_user(
        username=f"sysadmin_{suffix}",
        email=f"sysadmin_{suffix}@test.local",
        password="test-password",
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def project_a(db):
    """独立项目 A（避开既有 `project` fixture 的 repository 依赖）。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    return Project.objects.create(
        name=f"project-a-{suffix}",
        feishu_project_key=f"p229-pa-{suffix}",
    )


@pytest.fixture
def project_b(db):
    """独立项目 B（跨项目场景用）。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
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
    """implementation contract：项目 A 的 ADMIN 角色用户。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    u = User.objects.create_user(
        username=f"pa_admin_{suffix}",
        email=f"pa_admin_{suffix}@test.local",
        password="test-password",
    )
    _add_membership(project_a, u, ProjectRole.ADMIN)
    return u


@pytest.fixture
def project_a_member_user(db, project_a):
    """implementation contract：项目 A 的 MEMBER 角色用户。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    u = User.objects.create_user(
        username=f"pa_member_{suffix}",
        email=f"pa_member_{suffix}@test.local",
        password="test-password",
    )
    _add_membership(project_a, u, ProjectRole.MEMBER)
    return u


@pytest.fixture
def project_a_viewer_user(db, project_a):
    """implementation contract：项目 A 的 VIEWER 角色用户。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    u = User.objects.create_user(
        username=f"pa_viewer_{suffix}",
        email=f"pa_viewer_{suffix}@test.local",
        password="test-password",
    )
    _add_membership(project_a, u, ProjectRole.VIEWER)
    return u


@pytest.fixture
def project_b_admin_user(db, project_b):
    """implementation contract：项目 B 的 ADMIN 角色用户（跨项目越权测试）。"""
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    u = User.objects.create_user(
        username=f"pb_admin_{suffix}",
        email=f"pb_admin_{suffix}@test.local",
        password="test-password",
    )
    _add_membership(project_b, u, ProjectRole.ADMIN)
    return u


@pytest.fixture
def system_default_anthropic_credential(db):
    """系统级 Anthropic 凭证（scope='system'，scope_id=None）。"""
    import json
    from uuid import uuid4

    from common.encryption import encrypt_value
    from system.models import ProviderCredential

    suffix = uuid4().hex[:8]
    return ProviderCredential.objects.create(
        provider_type="anthropic",
        name=f"sys-default-{suffix}",
        scope="system",
        scope_id=None,
        encrypted_config=encrypt_value(
            json.dumps(
                {
                    "api_key": "sk-ant-sys-default-testing",
                    "base_url": "https://api.anthropic.com",
                }
            )
        ),
        is_active=True,
    )


@pytest.fixture
def project_a_anthropic_credential(db, project_a):
    """项目 A 的 Anthropic 凭证（scope='project'，scope_id=project_a.id）。"""
    import json
    from uuid import uuid4

    from common.encryption import encrypt_value
    from system.models import ProviderCredential

    suffix = uuid4().hex[:8]
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
    """项目 B 的 OpenAI 凭证（跨项目用例）。"""
    import json
    from uuid import uuid4

    from common.encryption import encrypt_value
    from system.models import ProviderCredential

    suffix = uuid4().hex[:8]
    return ProviderCredential.objects.create(
        provider_type="openai_chat",
        name=f"pb-oai-{suffix}",
        scope="project",
        scope_id=project_b.id,
        encrypted_config=encrypt_value(
            json.dumps(
                {
                    "api_key": "sk-proj-b-openai-testing",
                    "base_url": "https://api.openai.com/v1",
                }
            )
        ),
        is_active=True,
    )


@pytest.fixture
def async_client():
    """未认证的 APIClient（供矩阵测试 force_authenticate 按角色注入）。"""
    return APIClient()


# ============================================================================
# implementation Wave：AI 节点测试公共 fixture（Q6 决策落地 / work item 弥补）
# ============================================================================


@pytest.fixture
def make_minimal_context():
    """构造最小 ExecutionContext 供 AI 节点 execute 调用。

    Usage::

        def test_xxx(make_minimal_context):
            ctx = make_minimal_context(
                node_config={"user_prompt": "hi"},
                execution_id="test-exec",
                node_id="n1",
            )
            result = await node.execute(ctx)

    默认值：
        - execution_id="test-exec-id-12345"（固定便于 checkpoint 字节级 hash 稳定）
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


# ============= implementation Wave fixtures =============
#
# plan 新增 5 个 factory fixture，供 plan-07 的后端测试直接注入。
# 所有 fixture 遵循 project instructions 规范：
#   - 函数附类型注解
#   - docstring 中文 + 列参数语义
#   - 使用 `apps.get_model(...)` 避免 Django app registry race（security mitigation-01 缓解）
#
# 注意：部分 fixture 引用的字段（Conversation.provider_credential_id /
# Conversation.status / Project.default_provider_credential_id / ResolvedProviderChain）
# 尚未落地，**当前 plan/06 尚未执行**；fixture 实现采用 forward-compatible 写法：
#   - 工厂通过 **overrides 透传字段，避免字段不存在时强设默认值
#   - resolve_chain_builder 暂以 dict 代替 dataclass，plan 完成后可升级 type hint
# =====================================================


@pytest.fixture
def frozen_conversation_factory(db, project):
    """implementation contract：创建 status ∈ {active, completed, stopped, error} 的 Conversation。

    plan pin 冻结用例的主入口 fixture。

    Args:
        status: 对话状态，默认 "completed"（冻结态）。可选 active/completed/stopped/error。
        **overrides: 其余字段 override（title / model / provider_type / provider_credential_id ...）

    Usage::

        def test_frozen_cannot_repin(frozen_conversation_factory):
            conv = frozen_conversation_factory(status="completed")
            # 此后 API 修改 conv.provider_credential_id 应 400

    实现说明：
        - 使用 apps.get_model 防 app registry race
        - status 字段 plan Wave 新增；若当前模型未含则通过 setattr 兼容写入
          （DB 列可能缺失，仅影响未 migrate 的本地环境）
        - project 字段复用既有 `project` fixture，保证 Conversation 必填 FK 满足
    """
    from typing import Any

    from django.apps import apps

    def _factory(*, status: str = "completed", **overrides: Any):
        Conversation = apps.get_model("chat", "Conversation")
        field_names = {f.name for f in Conversation._meta.get_fields()}
        # 避免触发未迁移的 status 列（plan W0 前）
        status_kwarg: dict[str, Any] = {}
        if "status" in field_names:
            status_kwarg["status"] = status
        # Phase 08 ISO-01：created_by 向后兼容透传——字段落地后（08-02 schema
        # migration）经 overrides 直接写入会话 owner；未迁移环境（Wave 0 之前）
        # 丢弃该 override，避免 Conversation.objects.create() 抛 unexpected kwarg。
        if "created_by" in overrides and "created_by" not in field_names:
            overrides.pop("created_by")
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
    """implementation contract：创建 WorkflowExecution 并把 node_snapshots 写入 context JSONField。

    Args:
        node_snapshots: dict[str, dict]，形如
            {"node-1": {"provider_type": "anthropic", "model": "claude-3-5",
                        "resolved_source": "project", "api_key_fingerprint": "..."}}
        **overrides: 其余字段（status / trigger_type / workflow ...）

    Usage::

        def test_replay_uses_snapshot(execution_with_snapshot_factory):
            ex = execution_with_snapshot_factory(node_snapshots={
                "n1": {"provider_type": "anthropic", "model": "claude-3-5-sonnet-20241022"},
            })
            assert ex.context["node_snapshots"]["n1"]["model"] == "claude-3-5-sonnet-20241022"

    实现说明：
        - context 是 JSONField（workflows/models/execution.py work item 实测）
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
                name=f"wf-snapshot-{uuid4().hex[:8]}",
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
    """implementation contract：批量创建 TokenUsage，按 provider_type 聚合统计用。

    Args:
        provider_type: "anthropic" | "openai_chat" | "openai_responses" | "gemini" | "ollama"
        count: 创建条数（默认 1）
        cost_usd: 单条成本（Decimal，默认 0.01）
        input_tokens: 单条 input token（默认 500）
        output_tokens: 单条 output token（默认 500）

    Returns:
        list[TokenUsage] — 新创建记录列表

    Usage::

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
            # implementation Rule 1 bug fix：plan stub 未创建 main_session 致 NOT NULL 失败
            main = AgentSession.objects.create(
                session_id=f"main-{uuid4().hex}",
                status=AgentSession.Status.COMPLETED,
            )
            session = SubAgentSession.objects.create(
                session_id=f"sess-{uuid4().hex}",
                main_session=main,
                repo_url="https://github.com/test/analytics.git",
                task_type=SubAgentSession.TaskType.CODING,
            )

        created: list[Any] = []
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
def sse_error_emitter():
    """implementation contract / contract：SSE ERROR 事件 payload 构造 helper。

    返回一个 dataclass-like 对象，暴露 3 个 method，每个返回结构化 SSE 事件 dict：
        - context_exceeded(estimated, max_tokens, model) → contract contract
        - provider_credential_missing(provider_type) → contract contract
        - generic(message) → 通用兜底

    Usage::

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
            """contract contract：context_window_exceeded 结构化 payload。"""
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
            """contract contract：provider_credential_missing 结构化 payload。"""
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

    return _SSEErrorEmitter()


@pytest.fixture
def resolve_chain_builder():
    """implementation contract：构造四层 ResolvedProviderChain dict（plan aresolve_with_chain 产出）。

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

    Usage::

        def test_api_returns_chain(resolve_chain_builder):
            chain = resolve_chain_builder(winning_layer="project")
            # 之后 API 响应 `resolved_provider.chain` 与 chain["chain"] 一致

    实现说明：
        - plan 尚未落地 ResolvedProviderChain dataclass；当前以 dict 代替
        - plan 完成后可把返回值替换为 services.provider_config.ResolvedProviderChain
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

        chain_entries = []
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


# ============================================================================
# implementation（contract / work item）：pytest matrix Provider 双 fixture
#
# 把 ``CODE_INTELLIGENCE_PROVIDER ∈ {local, null}`` 双值参数化成 pytest fixture，
# 让 chat / agent / workflow / retrieval / find_related 关键 path 测试一次 import
# 即可同时覆盖两 Provider 路径，无需各自重复 ``HybridSearchService(NullProvider())
# / HybridSearchService(LocalProvider())`` 样板。
#
# 设计要点：
# - **非 autouse**：仅显式 inject ``provider_type`` / ``hybrid_service`` 的测试
#   才会触发 parametrize 双轨——既有不消费 fixture 的测试零影响（per plan
#   "CONFTEST fixture 兼容：不破坏既有测试"）。
# - **延迟 import**：``HybridSearchService`` / Provider 实现在 fixture 体内
#   lazy import，避免 conftest 顶层引入服务模块加重 Django app loading 顺序。
# - **测试 ID 兜底**：``params=["local", "null"]`` 让 pytest 自动生成
#   ``[local]`` / ``[null]`` 后缀，配合函数名中显式 ``_null_provider`` 子串
#   双重保证 ``pytest -k null_provider --co`` 收集（success criterion 字面要求）。
# - **CI 双 job 桥接**：implementation CI 启用 ``CODE_INTELLIGENCE_PROVIDER=null``
#   env 时，可在 fixture 内读 env 限定单 provider 跑——本 phase 仅落参数化骨架，
#   env-driven filter 留 implementation 一起接（per contract / docs/work item-MATRIX.md）。
# ============================================================================


@pytest.fixture(params=["local", "null"])
def provider_type(request) -> str:
    """implementation contract / Provider 双轨参数化 fixture。

    Returns:
        ``"local"`` 或 ``"null"``——下游 fixture / 测试用此字符串实例化
        ``LocalProvider`` / ``NullProvider`` 注入 ``HybridSearchService``。

    Usage::

        async def test_xxx_for_null_provider(provider_type):
            from services.code_intel.local_provider import LocalProvider
            from services.code_intel.null_provider import NullProvider
            provider = LocalProvider() if provider_type == "local" else NullProvider()
            ...

    与 ``hybrid_service`` 工厂 fixture 等价（hybrid_service 一步到位返
    ``HybridSearchService`` 实例，本 fixture 暴露原始字符串供更细粒度控制）。
    """
    return request.param  # type: ignore[no-any-return]


@pytest.fixture
def hybrid_service(provider_type):
    """implementation contract / HybridSearchService(Provider) 工厂 fixture。

    根据 ``provider_type`` parametrize 值实例化对应 Provider 并注入
    ``HybridSearchService``，让测试 body 完全聚焦在调用与断言。

    Returns:
        ``HybridSearchService`` 实例（NullProvider 或 LocalProvider 注入）。

    Usage::

        async def test_search_xxx_for_null_provider(hybrid_service):
            result = await hybrid_service.search("query", repository_ids=["r1"])
            ...

    注意：消费方 mock ``services.retrieval.hybrid_search.search_rag`` 等外部依赖
    保持 socket-disabled + DB-free；LocalProvider 路径的 ``lookup_symbols`` ORM
    调用会被 ``asyncio.gather(return_exceptions=True)`` 捕获降级为
    ``symbol_results=[]``（与 ``test_null_provider_paths.py`` case 5 同模式）。
    """
    from services.code_intel.local_provider import LocalProvider
    from services.code_intel.null_provider import NullProvider
    from services.retrieval import HybridSearchService

    provider = LocalProvider() if provider_type == "local" else NullProvider()
    return HybridSearchService(provider)


# ============================================================================
# implementation Wave：Access Token 共享 fixture（contract..04 测试桩消费）
#
# 设计要点（project instructions + contract）：
#   - 全函数严格类型注解（mypy 硬性要求）。
#   - access_tokens app 在 Wave 阶段尚未实现：fixture 体内通过
#     pytest.importorskip("access_tokens.models") 延迟导入，使本 conftest 顶层
#     不硬 import 未实现 app —— 套件可被收集、不报 ImportError；模块缺失时
#     依赖该 fixture 的用例优雅 skip。
#   - 明文仅来自 generate_pat()，入库只存 fingerprint（runners.models.hash_token），
#     明文绝不写任何字段（contract / contract）。
# ============================================================================


@pytest.fixture
def access_user(user: Any) -> Any:
    """Access Token 归属用户。

    复用既有 `user` fixture（accounts.User），不重复造轮子（shared user fixture）。
    """
    return user


@pytest.fixture
def make_access_token(
    db: Any, access_user: Any
) -> Callable[..., tuple[Any, str]]:
    """工厂 fixture：创建 AccessToken 并返回 (模型实例, 明文)。

    返回的可调用对象签名：``(name="t", expires_at=None, revoked=False, note="") -> tuple[AccessToken, str]``。

    Wave 阶段 `access_tokens.models` 未落地 → importorskip 跳过依赖此 fixture 的用例；
    实现（checkpoint）落地后生效。明文经 ``generate_pat()`` 生成，仅 ``hash_token`` 结果入
    ``token_hash``，明文绝不写任何字段（contract / contract）。

    指纹由 ``token_prefix=plaintext[:12]`` 与 ``token_suffix=plaintext[-4:]`` 对称构成；
    后 4 字符非敏感、不可反推明文（PAT-02/03）。``note`` 为可选备注（PAT-01）。

    Args:
        name: token 显示名（默认 "t"）。
        expires_at: 过期时间，None = 永不过期。
        revoked: 是否软吊销（设置 revoked_at = 当前时间）。
        note: 可选备注（默认空串）。
    """
    access_models = pytest.importorskip("access_tokens.models")
    from runners.models import hash_token

    def _make(
        name: str = "t",
        expires_at: Any = None,
        revoked: bool = False,
        note: str = "",
    ) -> tuple[Any, str]:
        from django.utils import timezone

        plaintext: str = access_models.generate_pat()
        token = access_models.AccessToken.objects.create(
            name=name,
            token_hash=hash_token(plaintext),
            token_prefix=plaintext[:12],
            token_suffix=plaintext[-4:],
            note=note,
            expires_at=expires_at,
            revoked_at=timezone.now() if revoked else None,
            created_by=access_user,
        )
        return token, plaintext

    return _make


# ============================================================================
# Phase 10（RemoteTool 执行端点）测试 fixtures
#
#   - make_remote_tool：source/is_active 参数化的 RemoteTool 工厂
#     （test_remote_tool_execute.py / test_remote_tool_dispatch.py 消费）。
#
# 注：工具令牌绑定（ToolTokenBinding）功能已整体移除，相应 fixture 与用例同删。
# ============================================================================


@pytest.fixture
def make_remote_tool(db: Any) -> Callable[..., Any]:
    """工厂 fixture：创建 ``RemoteTool``（source / is_active 可参数化）。

    返回的可调用对象签名::

        (name=None, source="mcp", is_active=True, description="t",
         input_schema=None, timeout=30, config=None) -> RemoteTool

    ``RemoteTool.name`` 唯一：``name=None`` 时自动拼随机后缀保证每次唯一，
    亦允许显式传 ``name`` 覆盖（同名复用/冲突由调用方自负）。``input_schema``
    缺省填最小合法 schema ``{"type": "object", "properties": {}}``，``config``
    缺省 ``{}``。该模型已存在（无需 importorskip）。

    Args:
        name: 工具名；None=自动生成唯一名。
        source: 工具源，``builtin`` / ``mcp`` / ``skill``（绑定范围仅 mcp/skill）。
        is_active: 是否启用（执行过滤依据）。
        description: 描述文本。
        input_schema: JSON Schema；None=最小合法 object schema。
        timeout: 执行超时秒数。
        config: 源特定配置 dict；None=空 dict。
    """
    from uuid import uuid4

    from tools.models import RemoteTool

    def _make(
        name: str | None = None,
        source: str = "mcp",
        is_active: bool = True,
        description: str = "t",
        input_schema: dict[str, Any] | None = None,
        timeout: int = 30,
        config: dict[str, Any] | None = None,
    ) -> Any:
        if name is None:
            name = f"tool_{source}_{uuid4().hex[:8]}"
        return RemoteTool.objects.create(
            name=name,
            description=description,
            source=source,
            input_schema=input_schema or {"type": "object", "properties": {}},
            timeout=timeout,
            is_active=is_active,
            config=config or {},
        )

    return _make
