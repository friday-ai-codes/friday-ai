"""任务级短 TTL token 生命周期测试（Phase 103 AGENT-01）。

覆盖：
- mint_task_token：明文前缀 / DB 只存 sha256 / kind=task / session_id / expires_at 余量
- 认证零改动复用：minted 明文经 AccessTokenAuthentication 认证通过，request.auth.kind=="task"
- 过期 / 吊销：is_valid 语义 + arevoke_task_tokens 幂等
- 存量兼容：不带 kind 的创建路径（views.py / make_access_token）恒 personal + session_id None

（Task 3 追加：三链派发集成 / 泄漏防线扫描 / MCP 链覆盖 / 终态吊销双路径。）
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from runners.models import hash_token

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_user(username: str) -> Any:
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username=username, password="x")


# =========================================================================
# mint：新签发语义（明文仅内存返回一次，DB 只存 sha256）
# =========================================================================


@pytest.mark.asyncio
async def test_mint_returns_plaintext_and_persists_hash_only() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-user")
    before = timezone.now()
    plaintext = await mint_task_token(user, "sess-mint-001", 1800)

    assert plaintext.startswith("friday_pat_")

    token = await AccessToken.objects.aget(kind="task", session_id="sess-mint-001")
    assert token.token_hash == hash_token(plaintext)
    assert token.kind == "task"
    assert token.session_id == "sess-mint-001"
    assert token.created_by_id == user.id
    # expires_at ≈ now + timeout + 600s 余量（±60s 容差）
    expected = before + timedelta(seconds=1800 + 600)
    assert abs((token.expires_at - expected).total_seconds()) < 60

    # 明文绝不出现在该行任何具体字段（PAT-02）；用 attname（FK 取 *_id）避免
    # async 上下文触发关系对象同步查询。
    for field in token._meta.concrete_fields:
        assert plaintext not in str(getattr(token, field.attname))


@pytest.mark.asyncio
async def test_mint_is_new_issue_each_call() -> None:
    """PAT-02 语义：mint 是新签发——同一用户两次 mint 得到不同明文/不同 DB 行。"""
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-twice-user")
    p1 = await mint_task_token(user, "sess-twice-a", 600)
    p2 = await mint_task_token(user, "sess-twice-b", 600)

    assert p1 != p2
    assert await AccessToken.objects.filter(kind="task", created_by=user).acount() == 2


# =========================================================================
# 认证零改动复用：minted 明文可直接过 AccessTokenAuthentication
# =========================================================================


@pytest.mark.asyncio
async def test_minted_token_authenticates_with_kind_task() -> None:
    from access_tokens.authentication import AccessTokenAuthentication
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-auth-user")
    plaintext = await mint_task_token(user, "sess-auth-001", 1800)

    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    result = await sync_to_async(AccessTokenAuthentication().authenticate)(request)
    assert result is not None
    auth_user, auth_token = result
    assert auth_user == user
    assert auth_token.kind == "task"
    assert auth_token.session_id == "sess-auth-001"


# =========================================================================
# 过期 / 吊销 / 幂等
# =========================================================================


@pytest.mark.asyncio
async def test_expired_task_token_is_invalid() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token

    user = await _make_user("mint-expire-user")
    await mint_task_token(user, "sess-expire-001", 60)

    token = await AccessToken.objects.aget(kind="task", session_id="sess-expire-001")
    assert token.is_valid is True
    # 回拨 expires_at 模拟过期
    token.expires_at = timezone.now() - timedelta(seconds=1)
    await token.asave(update_fields=["expires_at"])
    assert token.is_valid is False


@pytest.mark.asyncio
async def test_revoke_task_tokens_idempotent() -> None:
    from access_tokens.models import AccessToken
    from access_tokens.services import arevoke_task_tokens, mint_task_token

    user = await _make_user("mint-revoke-user")
    await mint_task_token(user, "sess-revoke-001", 600)

    count = await arevoke_task_tokens("sess-revoke-001")
    assert count == 1
    token = await AccessToken.objects.aget(kind="task", session_id="sess-revoke-001")
    assert token.is_valid is False
    assert token.revoked_at is not None
    first_revoked_at = token.revoked_at

    # 二次调用幂等：count=0，revoked_at 保留首次时间戳
    count2 = await arevoke_task_tokens("sess-revoke-001")
    assert count2 == 0
    await token.arefresh_from_db()
    assert token.revoked_at == first_revoked_at


@pytest.mark.asyncio
async def test_revoke_unknown_session_returns_zero() -> None:
    from access_tokens.services import arevoke_task_tokens

    assert await arevoke_task_tokens("sess-nonexistent") == 0


# =========================================================================
# 存量兼容：不带 kind 的创建路径恒 personal
# =========================================================================


def test_legacy_creation_defaults_to_personal(
    make_access_token: Callable[..., tuple[Any, str]],
) -> None:
    token, _plaintext = make_access_token(name="legacy-token")
    assert token.kind == "personal"
    assert token.session_id is None


# =========================================================================
# 派发集成 fixtures（mock runner 在线 + dispatcher 捕获 + metadata 简化）
# =========================================================================


@pytest.fixture
def dispatched_tasks(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Mock get_dispatcher().dispatch() —— 捕获 DispatchTask；并 mock runner 在线检查
    与 build_dispatch_metadata / git token 解析（隔离外部 IO，聚焦 token 注入面）。"""
    from unittest.mock import AsyncMock

    dispatched: list[Any] = []

    class _FakeDispatcher:
        async def dispatch(self, task: Any) -> None:
            dispatched.append(task)

    _instance = _FakeDispatcher()
    monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: _instance)

    import chat.coding_session_service as css

    monkeypatch.setattr(css, "check_runner_online", AsyncMock(return_value=True))

    async def _fake_metadata(repository: Any, coding_session: Any) -> tuple[dict, str]:
        return {"repository_id": str(repository.id)}, repository.git_url

    monkeypatch.setattr(css, "build_dispatch_metadata", _fake_metadata)
    monkeypatch.setattr(
        "services.git_credentials.aresolve_git_token", AsyncMock(return_value="")
    )
    return dispatched


@sync_to_async
def _make_chat_fixture(*, username: str, branch: str, created_by_none: bool = False):
    """构造 Space + Repository + Conversation(+created_by) + CodingSession。"""
    import uuid as uuid_mod

    from django.contrib.auth import get_user_model

    from chat.models import CodingSession, Conversation
    from projects.models import Space
    from repositories.models import Repository

    user = get_user_model().objects.create_user(username=username, password="x")
    space = Space.objects.create(name=f"space-{uuid_mod.uuid4().hex[:6]}")
    repo = Repository.objects.create(
        name=f"repo-{uuid_mod.uuid4().hex[:6]}",
        git_url=f"https://git.example.com/t/{uuid_mod.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
    )
    space.repositories.add(repo)
    conversation = Conversation.objects.create(
        space=space,
        title="token 集成测试",
        created_by=None if created_by_none else user,
    )
    cs = CodingSession.objects.create(
        conversation=conversation,
        repository=repo,
        tech_plan="## 方案",
        branch_name=branch,
    )
    cs = CodingSession.objects.select_related(
        "repository", "conversation", "conversation__space", "conversation__created_by"
    ).get(id=cs.id)
    return user, space, repo, cs


# =========================================================================
# chat 链集成：dispatch 注入新签发 token + 知识端点 + 落库泄漏扫描
# =========================================================================


@pytest.mark.asyncio
async def test_chat_dispatch_mints_token_and_no_plaintext_persisted(
    settings: Any, dispatched_tasks: list[Any]
) -> None:
    import json
    import uuid as uuid_mod

    from access_tokens.models import AccessToken
    from chat.coding_session_service import dispatch_coding_task
    from subagent.models import SubAgentSession

    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    user, _space, _repo, cs = await _make_chat_fixture(
        username=f"chat-mint-{uuid_mod.uuid4().hex[:8]}",
        branch=f"feat/103-chat-{uuid_mod.uuid4().hex[:6]}",
    )
    session_id = await dispatch_coding_task(cs, task_type="coding", prompt="实现功能")

    # (a) DispatchTask.metadata 含新签发 token + 知识端点（base 不带路径）
    assert len(dispatched_tasks) == 1
    meta = dispatched_tasks[0].metadata
    plaintext = meta["env_FRIDAY_TASK_USER_TOKEN"]
    assert plaintext.startswith("friday_pat_")
    assert meta["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] == "https://friday.example.com"

    # (b) AccessToken 行：kind=task、session_id 关联、token_hash==hash(env 明文)——新签发
    token = await AccessToken.objects.aget(kind="task", session_id=session_id)
    assert token.token_hash == hash_token(plaintext)
    assert token.created_by_id == user.id

    # (c) 落库泄漏扫描：SubAgentSession.last_output 与 CodingSession 持久化字段无明文
    sub_session = await SubAgentSession.objects.aget(session_id=session_id)
    assert "friday_pat_" not in json.dumps(sub_session.last_output, ensure_ascii=False)
    await cs.arefresh_from_db()
    for field in cs._meta.concrete_fields:
        assert "friday_pat_" not in str(getattr(cs, field.attname))


@pytest.mark.asyncio
async def test_persisted_dispatch_strips_all_credential_env_keys(
    settings: Any, dispatched_tasks: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """落库副本剔除全部凭证键（103 审查 WR-03 泄漏守护）：

    - 内存 DispatchTask.metadata 保留 Git token / API key / 任务 token（首派容器行为不变）
    - SubAgentSession.last_output.dispatch.metadata 三键全无 + 明文不落库
    - ``_redacted_env_keys`` 标记记录剔除清单（断连重派重解析依据）
    """
    import json
    import uuid as uuid_mod

    import chat.coding_session_service as css
    from chat.coding_session_service import CREDENTIAL_ENV_KEYS, dispatch_coding_task
    from subagent.models import SubAgentSession

    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    async def _metadata_with_credentials(repository: Any, coding_session: Any):
        return {
            "repository_id": str(repository.id),
            "env_FRIDAY_TASK_GIT_ACCESS_TOKEN": "glpat-GITSECRET456",
            "env_FRIDAY_TASK_GIT_AUTH_TYPE": "token",
            "env_FRIDAY_TASK_CLAUDE_API_KEY": "sk-ant-APISECRET789",
        }, repository.git_url

    monkeypatch.setattr(css, "build_dispatch_metadata", _metadata_with_credentials)

    _user, _space, _repo, cs = await _make_chat_fixture(
        username=f"chat-redact-{uuid_mod.uuid4().hex[:8]}",
        branch=f"feat/103-redact-{uuid_mod.uuid4().hex[:6]}",
    )
    session_id = await dispatch_coding_task(cs, task_type="coding", prompt="实现功能")

    # (a) 内存 dispatch metadata 完整（首派容器 clone/SDK 行为不变）
    meta = dispatched_tasks[0].metadata
    assert meta["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "glpat-GITSECRET456"
    assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "sk-ant-APISECRET789"
    assert meta["env_FRIDAY_TASK_USER_TOKEN"].startswith("friday_pat_")

    # (b) 落库副本三键全无，明文不出现在整个 last_output
    sub_session = await SubAgentSession.objects.aget(session_id=session_id)
    persisted_meta = sub_session.last_output["dispatch"]["metadata"]
    for key in CREDENTIAL_ENV_KEYS:
        assert key not in persisted_meta, f"凭证键 {key} 不得落库"
    dumped = json.dumps(sub_session.last_output, ensure_ascii=False)
    assert "glpat-GITSECRET456" not in dumped
    assert "sk-ant-APISECRET789" not in dumped
    assert "friday_pat_" not in dumped

    # (c) 剔除标记（重派重解析依据）：三键均被剔除
    assert set(persisted_meta["_redacted_env_keys"]) == set(CREDENTIAL_ENV_KEYS)
    # 非凭证键原样保留
    assert persisted_meta["env_FRIDAY_TASK_GIT_AUTH_TYPE"] == "token"


@pytest.mark.asyncio
async def test_chat_dispatch_degrades_without_user(
    settings: Any, dispatched_tasks: list[Any]
) -> None:
    """user 不可解析（conversation.created_by=None）→ dispatch 成功且不注入 token env。"""
    import uuid as uuid_mod

    from access_tokens.models import AccessToken
    from chat.coding_session_service import dispatch_coding_task

    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    _user, _space, _repo, cs = await _make_chat_fixture(
        username=f"chat-nouser-{uuid_mod.uuid4().hex[:8]}",
        branch=f"feat/103-nouser-{uuid_mod.uuid4().hex[:6]}",
        created_by_none=True,
    )
    session_id = await dispatch_coding_task(cs, task_type="coding", prompt="实现功能")

    assert len(dispatched_tasks) == 1
    meta = dispatched_tasks[0].metadata
    assert "env_FRIDAY_TASK_USER_TOKEN" not in meta
    # 知识端点仍注入（与 token 独立；task 侧三要素守门缺 token 自然降级）
    assert meta["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] == "https://friday.example.com"
    assert await AccessToken.objects.filter(kind="task", session_id=session_id).acount() == 0


# =========================================================================
# MCP 链覆盖（checker BLOCKER 1 验收钉）：桥接会话 created_by + kind=task token
# =========================================================================


@pytest.mark.asyncio
async def test_mcp_dispatch_execution_carries_created_by_and_mints(
    settings: Any, dispatched_tasks: list[Any]
) -> None:
    import uuid as uuid_mod

    from django.contrib.auth import get_user_model

    from access_tokens.models import AccessToken
    from chat.models import CodingSession
    from mcp_tools.execution_service import dispatch_execution
    from mcp_tools.models import (
        McpCodingExecutionTrace,
        McpCodingPlan,
        McpCodingPlanVersion,
    )
    from projects.models import Space
    from repositories.models import Repository

    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    @sync_to_async
    def _make_mcp_fixture():
        from interactions.ledger import create_interaction_run

        user = get_user_model().objects.create_user(
            username=f"mcp-mint-{uuid_mod.uuid4().hex[:8]}", password="x"
        )
        space = Space.objects.create(name=f"mcp-space-{uuid_mod.uuid4().hex[:6]}")
        repo = Repository.objects.create(
            name=f"mcp-repo-{uuid_mod.uuid4().hex[:6]}",
            git_url=f"https://git.example.com/m/{uuid_mod.uuid4().hex[:6]}.git",
            git_platform="github",
            default_branch="main",
        )
        space.repositories.add(repo)
        run = create_interaction_run(
            token_fingerprint=hash_token(f"mcp-mint-{uuid_mod.uuid4().hex[:6]}"),
            source="mcp",
        )
        plan = McpCodingPlan.objects.create(
            run=run,
            repository=repo,
            requirement="103 任务 token 覆盖",
            title="MCP token 覆盖",
        )
        version = McpCodingPlanVersion.objects.create(
            plan=plan,
            run=run,
            version=1,
            plan_body={"title": "MCP token 覆盖", "requirement": "103"},
        )
        trace = McpCodingExecutionTrace.objects.create(
            run=run,
            plan=plan,
            plan_version=version,
            repository=repo,
            branch_name="",
            target_branch="main",
            timeout_seconds=600,
        )
        return user, plan, version, trace

    user, plan, version, trace = await _make_mcp_fixture()

    branch = f"feat/103-mcp-{uuid_mod.uuid4().hex[:6]}"
    response = await dispatch_execution(
        trace=trace,
        plan=plan,
        version=version,
        branch_name=branch,
        target_branch="main",
        timeout_seconds=600,
        initiating_user=user,
    )

    coding_session = response.coding_session
    assert coding_session is not None
    cs = await CodingSession.objects.select_related(
        "conversation", "subagent_session"
    ).aget(id=coding_session.id)
    # 桥接 Conversation 携带发起用户（可归因，T-103-04）
    assert cs.conversation.created_by_id == user.id
    # MCP 链派发后存在 kind=task 的 AccessToken（三链覆盖不静默失效）
    assert cs.subagent_session is not None
    token = await AccessToken.objects.aget(
        kind="task", session_id=cs.subagent_session.session_id
    )
    assert token.created_by_id == user.id
    assert len(dispatched_tasks) == 1
    assert dispatched_tasks[0].metadata["env_FRIDAY_TASK_USER_TOKEN"].startswith(
        "friday_pat_"
    )


# =========================================================================
# 终态吊销双路径：callbacks HTTP 版 + consumers WS 版（幂等）
# =========================================================================


@sync_to_async
def _make_sub_session(username: str):
    import uuid as uuid_mod

    from django.contrib.auth import get_user_model

    from agents.models import AgentSession
    from subagent.models import SubAgentSession

    user = get_user_model().objects.create_user(username=username, password="x")
    main = AgentSession.objects.create(
        session_id=f"main-{uuid_mod.uuid4().hex[:8]}", metadata={}
    )
    session = SubAgentSession.objects.create(
        session_id=f"coding-{uuid_mod.uuid4().hex[:12]}",
        main_session=main,
        task_type=SubAgentSession.TaskType.CODING,
        status=SubAgentSession.Status.RUNNING,
        last_output={"task_type": "coding"},
    )
    return user, session


def _patch_resume_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """屏蔽回调 handler 的续驱/通知副作用（与吊销断言无关的后台调度）。"""
    from unittest.mock import AsyncMock, MagicMock

    import subagent.api.callbacks as cbs

    monkeypatch.setattr(cbs, "_schedule_workflow_resume", MagicMock())
    monkeypatch.setattr(cbs, "_schedule_agent_session_resume", MagicMock())
    monkeypatch.setattr(cbs, "_update_coding_session_on_complete", AsyncMock())
    monkeypatch.setattr(cbs, "_update_coding_session_on_fail", AsyncMock())
    monkeypatch.setattr(cbs, "_send_failure_notification", AsyncMock())


@pytest.mark.asyncio
async def test_http_callback_completed_revokes_task_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid as uuid_mod

    import structlog

    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token
    from subagent.api.callbacks import _handle_completed

    _patch_resume_hooks(monkeypatch)
    user, session = await _make_sub_session(f"cb-done-{uuid_mod.uuid4().hex[:8]}")
    await mint_task_token(user, session.session_id, 600)

    log = structlog.get_logger("test-callbacks")
    payload = {"result_type": "text", "output": {"text": "done"}}
    resp = await _handle_completed(session, payload, log)
    assert resp.status_code == 200

    token = await AccessToken.objects.aget(kind="task", session_id=session.session_id)
    assert token.revoked_at is not None
    # 重复触发（幂等）：TaskResult 已存在 → 早退，不报错
    resp2 = await _handle_completed(session, payload, log)
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_http_callback_failed_revokes_task_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid as uuid_mod

    import structlog

    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token
    from subagent.api.callbacks import _handle_failed

    _patch_resume_hooks(monkeypatch)
    user, session = await _make_sub_session(f"cb-fail-{uuid_mod.uuid4().hex[:8]}")
    await mint_task_token(user, session.session_id, 600)

    log = structlog.get_logger("test-callbacks")
    resp = await _handle_failed(session, {"error": "boom"}, log)
    assert resp.status_code == 200

    token = await AccessToken.objects.aget(kind="task", session_id=session.session_id)
    assert token.revoked_at is not None


@pytest.mark.asyncio
async def test_ws_handler_completed_revokes_task_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS 直连路径独立写终态（不经 callbacks handler）→ 同点吊销。"""
    import uuid as uuid_mod

    import structlog

    from access_tokens.models import AccessToken
    from access_tokens.services import arevoke_task_tokens, mint_task_token
    from runners.consumers import RunnerConsumer

    _patch_resume_hooks(monkeypatch)
    user, session = await _make_sub_session(f"ws-done-{uuid_mod.uuid4().hex[:8]}")
    await mint_task_token(user, session.session_id, 600)

    consumer = RunnerConsumer.__new__(RunnerConsumer)  # handler 不依赖连接态
    log = structlog.get_logger("test-ws")
    await RunnerConsumer._handle_completed(
        consumer,
        {"task_id": session.session_id, "result_type": "text", "output": {}},
        log,
    )

    token = await AccessToken.objects.aget(kind="task", session_id=session.session_id)
    assert token.revoked_at is not None
    # 幂等：再次吊销 count=0 不报错
    assert await arevoke_task_tokens(session.session_id) == 0


@pytest.mark.asyncio
async def test_ws_handler_failed_revokes_task_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid as uuid_mod

    import structlog

    from access_tokens.models import AccessToken
    from access_tokens.services import mint_task_token
    from runners.consumers import RunnerConsumer

    _patch_resume_hooks(monkeypatch)
    user, session = await _make_sub_session(f"ws-fail-{uuid_mod.uuid4().hex[:8]}")
    await mint_task_token(user, session.session_id, 600)

    consumer = RunnerConsumer.__new__(RunnerConsumer)
    log = structlog.get_logger("test-ws")
    await RunnerConsumer._handle_failed(
        consumer, {"task_id": session.session_id, "error": "boom"}, log
    )

    token = await AccessToken.objects.aget(kind="task", session_id=session.session_id)
    assert token.revoked_at is not None
