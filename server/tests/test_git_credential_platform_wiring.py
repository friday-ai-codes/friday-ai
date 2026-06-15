"""git 平台客户端（MR/PR 创建）取 token 接线守护测试（Phase 26 REPO-01）。

与 26-01 解析器单测不同，本套测试驱动**真实接线入口**
``mcp_tools.merge_request_service._get_client`` 而非解析器本身：patch
``get_git_platform_client`` 捕获传入 token，不真正打 git 平台 API。

覆盖 must_haves：
- 同 host 多仓在无 per-repo token 时共享同一实例凭证；
- per-repo token 存在时平台 client 仍优先用 per-repo token（向后兼容不回退）；
- 缺凭证时报错文案不回退；
- 取 token 路径日志不含 token 明文。
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


def _patch_client_capture(monkeypatch) -> list[dict[str, str]]:
    """patch ``merge_request_service.get_git_platform_client``，捕获每次传入 token。"""
    calls: list[dict[str, str]] = []

    def _fake_client(repository, token):
        calls.append({"repository_id": str(repository.id), "token": token})
        return object()

    monkeypatch.setattr(
        "mcp_tools.merge_request_service.get_git_platform_client", _fake_client
    )
    return calls


# ---------------------------------------------------------------------------
# Test 1：同 host 多仓共享一份实例凭证
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_two_same_host_repos_share_instance_credential(monkeypatch) -> None:
    """MR 平台 client：同 host 两仓均无 per-repo token → 共享实例凭证。"""
    from mcp_tools.merge_request_service import _get_client

    calls = _patch_client_capture(monkeypatch)
    repo_a = await _make_repo(f"https://{_HOST}/ns/a.git", name="a")
    repo_b = await _make_repo(f"git@{_HOST}:ns/b.git", name="b")
    await _make_instance_cred("instance-token")

    await _get_client(repo_a)
    await _get_client(repo_b)

    assert [c["token"] for c in calls] == ["instance-token", "instance-token"]


# ---------------------------------------------------------------------------
# Test 2：per-repo token 优先（向后兼容不回退）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_per_repo_token_wins(monkeypatch) -> None:
    """MR 平台 client：repo 同时有 per-repo + 同 host 实例凭证 → 用 per-repo。"""
    from mcp_tools.merge_request_service import _get_client

    calls = _patch_client_capture(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/p.git")
    await _make_per_repo_cred(repo, "per-repo-token")
    await _make_instance_cred("instance-token")

    await _get_client(repo)

    assert calls[-1]["token"] == "per-repo-token"


# ---------------------------------------------------------------------------
# Test 3：缺凭证报错文案不回退
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_missing_credential_raises(monkeypatch) -> None:
    """无 per-repo token 且 host 无实例凭证 → 仍 raise 原报错文案。"""
    from mcp_tools.merge_request_service import MergeRequestToolError, _get_client

    _patch_client_capture(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/none.git")

    with pytest.raises(MergeRequestToolError, match="仓库缺少 Git 平台访问凭据"):
        await _get_client(repo)


# ---------------------------------------------------------------------------
# Test 4：取 token 路径不泄漏 token 明文
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_token_not_in_logs(monkeypatch, caplog) -> None:
    """平台 client 取 token 时，结构化日志不含 token 明文。"""
    from mcp_tools.merge_request_service import _get_client

    calls = _patch_client_capture(monkeypatch)
    secret = "super-secret-instance-token"
    repo = await _make_repo(f"https://{_HOST}/ns/s.git")
    await _make_instance_cred(secret)

    with caplog.at_level(logging.DEBUG):
        await _get_client(repo)

    assert calls[-1]["token"] == secret  # token 确实传入 client
    assert secret not in caplog.text  # 但绝不进日志
