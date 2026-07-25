"""gap-closure 接线守护测试（Phase 26 REPO-01 / 26-VERIFICATION 缺口）。

26-02/26-03 之后仍有 ≥8 处内联 ``decrypt_value(credential.encrypted_token)``
绕过统一解析器（pr.py / coding_graph.py / code_review.py / summary_service.py /
chat_tools.py / views.py TestConnection）。本套测试驱动两类**代表性真实入口**，
确认「仅靠实例凭证池（无 per-repo token）的同 host 仓库」也能解析出 token：

1. 容器 dispatch token 注入路径（``summary_service._build_env_metadata``）——
   代表 summary_service / chat_tools 两处 dispatch 注入；
2. git 平台 client 路径（``CreatePRNode._create_pr_for_repository``）——
   代表 pr.py / code_review.py / coding_graph.py 三处 ``get_git_platform_client``。

同时守护 per-repo 优先（向后兼容不回退）、缺凭证文案不回退、token 不进日志。
"""

from __future__ import annotations

import logging

import pytest
from asgiref.sync import sync_to_async

from common.encryption import encrypt_value
from repositories.models import (
    AuthType,
    GitCredential,
    GitInstanceCredential,
    GitPlatform,
    Repository,
)

_HOST = "gitlab.example.com"


@sync_to_async
def _make_repo(git_url: str, *, name: str = "r") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=git_url,
        git_platform="gitlab",
        default_branch="main",
    )


@sync_to_async
def _make_instance_cred(token: str, *, host: str = _HOST) -> None:
    GitInstanceCredential.objects.create(
        host=host,
        provider=GitPlatform.GITLAB,
        encrypted_token=encrypt_value(token),
    )


@sync_to_async
def _make_per_repo_cred(repo: Repository, token: str) -> None:
    GitCredential.objects.create(
        repository=repo,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value(token),
    )


# ---------------------------------------------------------------------------
# 类型 1：容器 dispatch token 注入（summary_service._build_env_metadata）
# ---------------------------------------------------------------------------


def _patch_runtime_config(monkeypatch) -> None:
    """patch ``aget_claude_code_runtime_config``，避免触达 provider 配置。"""

    async def _fake_cc():
        return {
            "api_key": "k",
            "base_url": "http://x",
            "default_model": "m",
            "haiku_model": "s",
        }

    monkeypatch.setattr(
        "services.provider_config.aget_claude_code_runtime_config", _fake_cc
    )


@pytest.mark.django_db(transaction=True)
async def test_dispatch_instance_pool_only_injects_token(monkeypatch) -> None:
    """dispatch 注入：实例池-only 同 host 仓库 → 注入实例 token（不再注入空 token）。"""
    from repositories.summary_service import _build_env_metadata

    _patch_runtime_config(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/a.git", name="a")
    await _make_instance_cred("instance-token")

    env = await _build_env_metadata(repo)

    assert env["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "instance-token"
    assert env["env_FRIDAY_TASK_GIT_AUTH_TYPE"] == "token"


@pytest.mark.django_db(transaction=True)
async def test_dispatch_per_repo_token_wins(monkeypatch) -> None:
    """dispatch 注入：per-repo + 实例池同在 → 用 per-repo token（向后兼容不回退）。"""
    from repositories.summary_service import _build_env_metadata

    _patch_runtime_config(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/p.git")
    await _make_per_repo_cred(repo, "per-repo-token")
    await _make_instance_cred("instance-token")

    env = await _build_env_metadata(repo)

    assert env["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "per-repo-token"


@pytest.mark.django_db(transaction=True)
async def test_dispatch_missing_credential_omits_token(monkeypatch) -> None:
    """dispatch 注入：无任何凭证 → 不注入 token key（行为不回退）。"""
    from repositories.summary_service import _build_env_metadata

    _patch_runtime_config(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/none.git")

    env = await _build_env_metadata(repo)

    assert "env_FRIDAY_TASK_GIT_ACCESS_TOKEN" not in env


# ---------------------------------------------------------------------------
# 类型 2：git 平台 client 路径（CreatePRNode._create_pr_for_repository）
# ---------------------------------------------------------------------------


def _patch_pr_client_capture(monkeypatch) -> list[dict[str, str]]:
    """patch ``pr.get_git_platform_client``，捕获传入 token，返回成功 fake client。"""
    from services.git_platform import MRCreateResult

    calls: list[dict[str, str]] = []

    class _FakeClient:
        async def find_open_merge_request(self, source_branch, target_branch):
            """无既有 open PR —— CreatePRNode 建 PR 前会先过这道 reuse-first 围栏。"""
            return None

        async def create_merge_request(self, request):
            return MRCreateResult(success=True, mr_url="http://mr/1", mr_id="1")

    def _fake_client(repository, token):
        calls.append({"repository_id": str(repository.id), "token": token})
        return _FakeClient()

    monkeypatch.setattr(
        "workflows.nodes.git.pr.get_git_platform_client", _fake_client
    )
    return calls


@pytest.mark.django_db(transaction=True)
async def test_pr_instance_pool_only_uses_instance_token(monkeypatch) -> None:
    """PR 创建：实例池-only 同 host 仓库 → 平台 client 收到实例 token。"""
    from workflows.nodes.git.pr import CreatePRNode

    calls = _patch_pr_client_capture(monkeypatch)
    repo = await _make_repo(f"git@{_HOST}:ns/b.git", name="b")
    await _make_instance_cred("instance-token")

    result = await CreatePRNode()._create_pr_for_repository(
        repo, "t", "b", "main", "feat", []
    )

    assert calls[-1]["token"] == "instance-token"
    assert result.get("pr_url") == "http://mr/1"


@pytest.mark.django_db(transaction=True)
async def test_pr_missing_credential_error_preserved(monkeypatch) -> None:
    """PR 创建：无任何凭证 → 保留既有 'No access token' 报错，不回退。"""
    from workflows.nodes.git.pr import CreatePRNode

    _patch_pr_client_capture(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/none.git")

    result = await CreatePRNode()._create_pr_for_repository(
        repo, "t", "b", "main", "feat", []
    )

    assert result["success"] is False
    assert result["error"] == "No access token configured for repository"


@pytest.mark.django_db(transaction=True)
async def test_pr_token_not_in_logs(monkeypatch, caplog) -> None:
    """PR 创建取 token 时，结构化日志不含 token 明文。"""
    from workflows.nodes.git.pr import CreatePRNode

    calls = _patch_pr_client_capture(monkeypatch)
    secret = "super-secret-instance-token"
    repo = await _make_repo(f"https://{_HOST}/ns/s.git")
    await _make_instance_cred(secret)

    with caplog.at_level(logging.DEBUG):
        await CreatePRNode()._create_pr_for_repository(
            repo, "t", "b", "main", "feat", []
        )

    assert calls[-1]["token"] == secret
    assert secret not in caplog.text
