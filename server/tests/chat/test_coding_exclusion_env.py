"""Phase 22-04 Task 1 守卫：编码容器面 exclude 规则下传（两条派发路径 env 注入）。

覆盖（T-22-13 / T-22-14）：
- ``serialize_rules_for_repo`` 返回合并后有效规则（含 builtin），可 json 序列化，**绝不空**。
- chat ``build_dispatch_metadata`` 注入 ``env_FRIDAY_TASK_EXCLUDE_PATTERNS``（json 可解析为规则列表）。
- workflow ``AICodingNode._run_repo_coding`` 的 ``DispatchTask.metadata`` 含同键。
- 无 per-repo 规则时仍注入内置默认（断言非空）—— 容器面默认 fail-closed。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

EXCLUDE_KEY = "env_FRIDAY_TASK_EXCLUDE_PATTERNS"

_RUNTIME_CONFIG = {
    "api_key": "sk-test",
    "base_url": "",
    "default_model": "claude-sonnet-test",
    "sonnet_model": "claude-sonnet-test",
    "opus_model": "claude-opus-test",
    "haiku_model": "claude-haiku-test",
}


@pytest.mark.django_db(transaction=True)
class TestSerializeRulesForRepo:
    """serialize_rules_for_repo 单一真相导出。"""

    @pytest.mark.asyncio
    async def test_returns_builtin_defaults_when_no_per_repo_rules(self, repository) -> None:
        from services.exclusion import serialize_rules_for_repo

        rules = await serialize_rules_for_repo(str(repository.id))

        assert isinstance(rules, list)
        assert rules, "无 per-repo 规则时仍须返回内置默认（绝不空 → 容器面默认安全）"
        # 每项可 json 序列化且字段齐全
        for item in rules:
            assert set(item.keys()) >= {"pattern", "rule_type"}
        json.dumps(rules, ensure_ascii=False)  # 不抛即可序列化
        pairs = {(r["rule_type"], r["pattern"]) for r in rules}
        assert ("glob", ".env") in pairs  # builtin 安全默认在导出集合中

    @pytest.mark.asyncio
    async def test_includes_per_repo_rule(self, repository) -> None:
        from repositories.models import RepoExclusionRule
        from services.exclusion import invalidate_matcher_cache, serialize_rules_for_repo

        await sync_to_async(RepoExclusionRule.objects.create)(
            repository=repository, pattern="vault/", rule_type="dir", source="user"
        )
        invalidate_matcher_cache(str(repository.id))

        rules = await serialize_rules_for_repo(str(repository.id))
        pairs = {(r["rule_type"], r["pattern"]) for r in rules}
        assert ("dir", "vault/") in pairs
        assert ("glob", ".env") in pairs  # builtin 仍在


@pytest.mark.django_db(transaction=True)
class TestBuildDispatchMetadataExclude:
    """chat 派发路径注入 env_FRIDAY_TASK_EXCLUDE_PATTERNS。"""

    @pytest.fixture
    def coding_session_with_repo(self, project, repository):
        from chat.models import CodingSession, Conversation

        conversation = Conversation.objects.create(space=project, title="exclude env 测试")
        return CodingSession.objects.create(
            conversation=conversation,
            repository=repository,
            tech_plan="## 方案",
            branch_name="feat20260614.excl",
        )

    @pytest.mark.asyncio
    async def test_metadata_contains_exclude_patterns(self, coding_session_with_repo) -> None:
        from chat.coding_session_service import build_dispatch_metadata
        from repositories.models import GitCredential

        session = coding_session_with_repo
        repo = session.repository

        with (
            patch(
                "services.provider_config.aget_claude_code_runtime_config",
                new_callable=AsyncMock,
                return_value=dict(_RUNTIME_CONFIG),
            ),
            patch("repositories.models.GitCredential") as mock_git_cred_cls,
        ):
            mock_git_cred_cls.objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
            mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist

            env_metadata, _repo_url = await build_dispatch_metadata(repo, session)

        assert EXCLUDE_KEY in env_metadata, "chat 派发路径必须下传 exclude 规则"
        parsed = json.loads(env_metadata[EXCLUDE_KEY])
        assert isinstance(parsed, list) and parsed, "下传规则须为非空列表"
        pairs = {(r["rule_type"], r["pattern"]) for r in parsed}
        assert ("glob", ".env") in pairs


@pytest.mark.django_db(transaction=True)
class TestWorkflowRunRepoCodingExclude:
    """workflow 派发路径注入 env_FRIDAY_TASK_EXCLUDE_PATTERNS。"""

    @pytest.mark.asyncio
    async def test_dispatch_metadata_contains_exclude_patterns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from common.encryption import encrypt_value
        from repositories.models import AuthType, GitCredential, Repository
        from workflows.nodes.ai.coding import AICodingNode

        # 生产 coding.py 访问 credential.ssl_verify，但模型未定义该字段 → 测试侧兜底。
        monkeypatch.setattr(GitCredential, "ssl_verify", True, raising=False)

        repo = await sync_to_async(Repository.objects.create)(
            name="excl-wf-repo",
            git_url="https://git.example.com/excl-wf.git",
            default_branch="main",
        )
        await sync_to_async(GitCredential.objects.create)(
            repository=repo,
            auth_type=AuthType.ACCESS_TOKEN,
            encrypted_token=encrypt_value("tok"),
        )
        # 以 select_related 重载，避免 async 上下文反向 OneToOne 触发 SynchronousOnlyOperation。
        repo = await Repository.objects.select_related("credential").aget(id=repo.id)

        dispatched: list[Any] = []

        class _FakeDispatcher:
            async def dispatch(self, task: Any) -> None:
                dispatched.append(task)

        monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: _FakeDispatcher())

        node = AICodingNode()
        await node._run_repo_coding(
            repository=repo,
            tasks=[{"task_description": "do x"}],
            branch_name="feat/excl",
            base_branch="main",
            global_context="ctx",
            config={},
        )

        assert len(dispatched) == 1
        meta = dispatched[0].metadata
        assert EXCLUDE_KEY in meta, "workflow 派发路径必须下传 exclude 规则"
        parsed = json.loads(meta[EXCLUDE_KEY])
        assert isinstance(parsed, list) and parsed
        pairs = {(r["rule_type"], r["pattern"]) for r in parsed}
        assert ("glob", ".env") in pairs
