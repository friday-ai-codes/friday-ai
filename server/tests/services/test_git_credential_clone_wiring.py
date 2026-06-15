"""克隆 / bare 镜像 fetch / 图谱克隆三条取 token 路径的接线守护测试（Phase 26 REPO-02）。

与 26-01 解析器单测不同，本套测试驱动**真实接线入口**而非解析器本身：
- ``repo_mirror._fetch_repo_params`` —— bare 镜像 fetch 的取 token 路径；
- ``graph_builder.prepare_repo_workdir_async`` —— 图谱克隆的取 token 路径（mock
  子进程，仅捕获 ``git clone`` argv 中的鉴权 URL，不真正联网）。

覆盖 must_haves：
- 同 host 多仓在无 per-repo token 时共享同一实例凭证；
- per-repo token 存在时三条路径仍优先用 per-repo token（向后兼容不回退）；
- 取 token 路径日志不含 token 明文。
"""

from __future__ import annotations

import asyncio
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
from repositories.views import build_authenticated_git_url

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


class _FakeProc:
    """模拟 git clone 子进程：恒成功、空输出，避免真实联网。"""

    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def kill(self) -> None:  # pragma: no cover - 成功路径不会触发
        pass

    async def wait(self) -> int:  # pragma: no cover
        return 0


def _patch_clone_capture(monkeypatch) -> list[list[str]]:
    """patch ``asyncio.create_subprocess_exec``，捕获每次 git clone 的 argv。"""
    captured: list[list[str]] = []

    async def _fake_exec(*args, **kwargs):
        captured.append(list(args))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return captured


# ---------------------------------------------------------------------------
# Test 1：同 host 多仓共享一份实例凭证
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_mirror_two_same_host_repos_share_instance_credential() -> None:
    """bare 镜像 fetch：同 host 两仓均无 per-repo token → 共享实例凭证。"""
    from services.repo_mirror import _fetch_repo_params

    repo_a = await _make_repo(f"https://{_HOST}/ns/a.git", name="a")
    repo_b = await _make_repo(f"git@{_HOST}:ns/b.git", name="b")
    await _make_instance_cred("instance-token")

    params_a = await _fetch_repo_params(str(repo_a.id))
    params_b = await _fetch_repo_params(str(repo_b.id))

    assert params_a["token"] == "instance-token"
    assert params_b["token"] == "instance-token"
    # 实例 token 经 build_authenticated_git_url 嵌入 https 鉴权 URL
    auth_url = build_authenticated_git_url(params_a["git_url"], params_a["token"])
    assert "oauth2:instance-token@" in auth_url


@pytest.mark.django_db(transaction=True)
async def test_graph_clone_same_host_uses_instance_credential(monkeypatch) -> None:
    """图谱克隆：无 per-repo token 时按 host 命中实例凭证并嵌入 clone argv。"""
    from services.graph_builder import prepare_repo_workdir_async

    captured = _patch_clone_capture(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/g.git", name="g")
    await _make_instance_cred("instance-token")

    async with prepare_repo_workdir_async(str(repo.id)):
        pass

    assert captured, "git clone 未被调用"
    argv_text = " ".join(captured[0])
    assert "oauth2:instance-token@" in argv_text


# ---------------------------------------------------------------------------
# Test 2：per-repo token 优先（向后兼容不回退）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_mirror_per_repo_token_wins() -> None:
    """bare 镜像 fetch：repo 同时有 per-repo + 同 host 实例凭证 → 用 per-repo。"""
    from services.repo_mirror import _fetch_repo_params

    repo = await _make_repo(f"https://{_HOST}/ns/p.git")
    await _make_per_repo_cred(repo, "per-repo-token")
    await _make_instance_cred("instance-token")

    params = await _fetch_repo_params(str(repo.id))
    assert params["token"] == "per-repo-token"


@pytest.mark.django_db(transaction=True)
async def test_graph_clone_per_repo_token_wins(monkeypatch) -> None:
    """图谱克隆：per-repo token 存在时优先用 per-repo token。"""
    from services.graph_builder import prepare_repo_workdir_async

    captured = _patch_clone_capture(monkeypatch)
    repo = await _make_repo(f"https://{_HOST}/ns/p.git")
    await _make_per_repo_cred(repo, "per-repo-token")
    await _make_instance_cred("instance-token")

    async with prepare_repo_workdir_async(str(repo.id)):
        pass

    argv_text = " ".join(captured[0])
    assert "oauth2:per-repo-token@" in argv_text
    assert "instance-token" not in argv_text


# ---------------------------------------------------------------------------
# Test 3：取 token 路径不泄漏 token 明文
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_token_not_in_logs(monkeypatch, caplog) -> None:
    """三条接线入口取 token 时，结构化日志不含 token 明文。"""
    from services.graph_builder import prepare_repo_workdir_async
    from services.repo_mirror import _fetch_repo_params

    secret = "super-secret-instance-token"
    repo = await _make_repo(f"https://{_HOST}/ns/s.git")
    await _make_instance_cred(secret)

    captured = _patch_clone_capture(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        params = await _fetch_repo_params(str(repo.id))
        async with prepare_repo_workdir_async(str(repo.id)):
            pass

    assert params["token"] == secret
    assert secret in " ".join(captured[0])  # token 确实进了 clone argv
    assert secret not in caplog.text  # 但绝不进日志
