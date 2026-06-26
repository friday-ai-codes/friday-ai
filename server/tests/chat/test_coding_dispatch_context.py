"""dispatch 携带项目上下文守护测试（Phase 86, HOOK-04）：

- 绑定项目（bound_project）+ 成员触发用户 → 召回非空 + 写 RetrievalTrace
- ProjectBranch 显式绑定反查 → 召回非空（无 bound_project 时）
- 无绑定 → 返回 ""（fail-soft，派发与现状一致）
- members_only 非成员触发用户 → packer fail-closed 返回空（不泄漏）
- 注入上下文经脱敏（含密钥片段注入前无明文）
- build_dispatch_metadata 含固定 workspace cwd 标识（供 resume cwd 一致校验）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import ProjectVisibility
from initiatives.services import MemoryService, ProjectService
from interactions.models import RetrievalTrace
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_RUNTIME_CONFIG = {
    "api_key": "sk-test",
    "base_url": "",
    "default_model": "claude-sonnet-test",
    "sonnet_model": "claude-sonnet-test",
    "opus_model": "claude-opus-test",
    "haiku_model": "claude-haiku-test",
}


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


@sync_to_async
def _make_repository(name: str = "ctx-repo"):
    return Repository.objects.create(
        name=name,
        git_url=f"https://github.com/test/{name}.git",
        git_platform="github",
        default_branch="main",
    )


async def _make_project(*, key: str, visibility=ProjectVisibility.PUBLIC_ORG):
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user(f"owner-{key}")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    project = await type(project).objects.select_related("space").aget(pk=project.id)
    return project, space, owner


@sync_to_async
def _make_coding_session(*, space, repo, owner, branch="feat/ctx", bound_project=None):
    from chat.models import CodingSession, Conversation

    conversation = Conversation.objects.create(
        space=space,
        title="dispatch ctx 测试",
        created_by=owner,
        bound_project=bound_project,
    )
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repo,
        tech_plan="## 方案",
        branch_name=branch,
    )


class TestResolveProjectContextForDispatch:
    @pytest.mark.asyncio
    async def test_bound_project_member_recalls_and_writes_trace(self) -> None:
        from chat.coding_session_service import _resolve_project_context_for_dispatch

        project, space, owner = await _make_project(key="ctx-bound")
        await MemoryService().append(
            project_id=project.id, content="项目关键决策记忆", contributor=owner
        )
        repo = await _make_repository("ctx-bound-repo")
        cs = await _make_coding_session(
            space=space, repo=repo, owner=owner, bound_project=project
        )

        ctx = await _resolve_project_context_for_dispatch(cs)
        assert "项目关键决策记忆" in ctx

        trace_count = await RetrievalTrace.objects.filter(
            source="chat_project_context", conversation_id=str(cs.conversation_id)
        ).acount()
        assert trace_count >= 1

    @pytest.mark.asyncio
    async def test_branch_binding_fallback_recalls(self) -> None:
        from chat.coding_session_service import _resolve_project_context_for_dispatch
        from initiatives.models import ProjectBranch

        project, space, owner = await _make_project(key="ctx-branch")
        await MemoryService().append(
            project_id=project.id, content="分支绑定召回记忆", contributor=owner
        )
        repo = await _make_repository("ctx-branch-repo")
        cs = await _make_coding_session(
            space=space, repo=repo, owner=owner, branch="feat/bind", bound_project=None
        )
        # 无 bound_project，但有 ProjectBranch 显式绑定 → 反查命中。
        await sync_to_async(ProjectBranch.objects.create)(
            project=project, repository=repo, branch_name="feat/bind", created_by=owner
        )

        ctx = await _resolve_project_context_for_dispatch(cs)
        assert "分支绑定召回记忆" in ctx

    @pytest.mark.asyncio
    async def test_no_binding_returns_empty(self) -> None:
        from chat.coding_session_service import _resolve_project_context_for_dispatch

        space = await sync_to_async(Space.objects.create)(name="S-nobind")
        owner = await _make_user("owner-nobind")
        repo = await _make_repository("ctx-nobind-repo")
        cs = await _make_coding_session(
            space=space, repo=repo, owner=owner, branch="feat/none", bound_project=None
        )
        assert await _resolve_project_context_for_dispatch(cs) == ""

    @pytest.mark.asyncio
    async def test_members_only_non_member_fail_closed(self) -> None:
        from chat.coding_session_service import _resolve_project_context_for_dispatch

        project, space, owner = await _make_project(
            key="ctx-mo", visibility=ProjectVisibility.MEMBERS_ONLY
        )
        await MemoryService().append(
            project_id=project.id, content="机密不可泄漏记忆", contributor=owner
        )
        stranger = await _make_user("stranger-mo")
        repo = await _make_repository("ctx-mo-repo")
        # 触发用户为非成员 stranger → packer fail-closed 零召回。
        cs = await _make_coding_session(
            space=space, repo=repo, owner=stranger, bound_project=project
        )
        ctx = await _resolve_project_context_for_dispatch(cs)
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_recalled_context_is_redacted(self) -> None:
        from chat.coding_session_service import _resolve_project_context_for_dispatch

        project, space, owner = await _make_project(key="ctx-redact")
        # 记忆内混入密钥样式片段 → 注入前必须脱敏。
        await MemoryService().append(
            project_id=project.id,
            content="部署密钥 sk-ant-abcd1234567890efgh 请勿外泄",
            contributor=owner,
        )
        repo = await _make_repository("ctx-redact-repo")
        cs = await _make_coding_session(
            space=space, repo=repo, owner=owner, bound_project=project
        )
        ctx = await _resolve_project_context_for_dispatch(cs)
        assert "sk-ant-abcd1234567890efgh" not in ctx
        assert "REDACTED" in ctx


class TestDispatchMetadataWorkspaceCwd:
    @pytest.mark.asyncio
    async def test_metadata_contains_workspace_cwd(self) -> None:
        from chat.coding_session_service import build_dispatch_metadata
        from chat.session_store import WORKSPACE_CWD
        from repositories.models import GitCredential

        space = await sync_to_async(Space.objects.create)(name="S-cwd")
        owner = await _make_user("owner-cwd")
        repo = await _make_repository("ctx-cwd-repo")
        cs = await _make_coding_session(space=space, repo=repo, owner=owner)

        with (
            patch(
                "services.provider_config.aget_claude_code_runtime_config",
                new_callable=AsyncMock,
                return_value=dict(_RUNTIME_CONFIG),
            ),
            patch("repositories.models.GitCredential") as mock_git_cred_cls,
        ):
            mock_git_cred_cls.objects.aget = AsyncMock(
                side_effect=GitCredential.DoesNotExist
            )
            mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist

            env_metadata, _repo_url = await build_dispatch_metadata(repo, cs)

        assert env_metadata["env_FRIDAY_TASK_WORKSPACE_CWD"] == WORKSPACE_CWD
