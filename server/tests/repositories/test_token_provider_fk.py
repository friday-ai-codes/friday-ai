"""TOKEN-01/02：密钥提供方 FK 重构守护。

覆盖：
- 解析优先级 per-repo → FK → host → none（老仓库零回归）
- 建仓 access_token 可选：FK / host fallback / 无（fail-loud）
- has_credential 反映 per-repo 或实例池可解析
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from common.encryption import encrypt_value
from projects.models import Space
from repositories.models import (
    AuthType,
    GitCredential,
    GitInstanceCredential,
    Repository,
)
from services.git_credentials import resolve_git_token_sync

# transaction=True：异步 create 测试经 AsyncClient 在独立线程连接命中 DB，
# 普通 django_db 的单事务会与之死锁（database table is locked）。
pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# 解析优先级（同步核心）
# ---------------------------------------------------------------------------


def _repo(**kwargs) -> Repository:
    base = dict(name="r", git_url="https://gitlab.example.com/g/p.git", git_platform="gitlab")
    base.update(kwargs)
    return Repository.objects.create(**base)


def test_resolver_per_repo_token_wins() -> None:
    repo = _repo()
    GitCredential.objects.create(
        repository=repo, auth_type=AuthType.ACCESS_TOKEN, encrypted_token=encrypt_value("per-repo-tok")
    )
    inst = GitInstanceCredential.objects.create(
        host="gitlab.example.com", encrypted_token=encrypt_value("host-tok")
    )
    repo.git_instance_credential = inst
    repo.save()
    assert resolve_git_token_sync(repo) == "per-repo-tok"


def test_resolver_fk_over_host() -> None:
    """无 per-repo token：显式 FK 优先于 host 自动匹配。"""
    fk = GitInstanceCredential.objects.create(
        host="other.example.com", encrypted_token=encrypt_value("fk-tok")
    )
    GitInstanceCredential.objects.create(
        host="gitlab.example.com", encrypted_token=encrypt_value("host-tok")
    )
    repo = _repo(git_instance_credential=fk)
    assert resolve_git_token_sync(repo) == "fk-tok"


def test_resolver_host_match_when_no_fk() -> None:
    GitInstanceCredential.objects.create(
        host="gitlab.example.com", encrypted_token=encrypt_value("host-tok")
    )
    repo = _repo()
    assert resolve_git_token_sync(repo) == "host-tok"


def test_resolver_none_for_legacy_repo_without_any() -> None:
    """老仓库无 per-repo token、无 FK、host 无匹配 → None（零回归）。"""
    repo = _repo(git_url="https://no-match.example.com/g/p.git")
    assert resolve_git_token_sync(repo) is None


# ---------------------------------------------------------------------------
# 建仓 access_token 可选
# ---------------------------------------------------------------------------


async def _auth_headers(user: User) -> dict[str, str]:
    refresh = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {refresh.access_token}"}


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(username="u", email="u@e.com", password="x")


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="s")


async def _post_create(client, user, payload):
    from unittest.mock import patch

    with patch("repositories.summary_service.enqueue_repo_summary"):
        return await client.post(
            "/api/repositories/",
            data=payload,
            content_type="application/json",
            headers=await _auth_headers(user),
        )


@pytest.mark.asyncio
async def test_create_with_fk_no_token(user: User, space: Space) -> None:
    """无自有 token + 显式密钥提供方 FK → 建仓成功，不建 per-repo 凭证，FK 落库。"""
    inst = await GitInstanceCredential.objects.acreate(
        host="gitlab.example.com", encrypted_token=encrypt_value("fk-tok")
    )
    resp = await _post_create(AsyncClient(), user, {
        "name": "fk-repo",
        "git_url": "https://gitlab.example.com/g/fk.git",
        "git_platform": "gitlab",
        "access_token": "",
        "git_instance_credential_id": str(inst.id),
        "space_ids": [str(space.id)],
    })
    assert resp.status_code == 201, resp.content
    repo = await Repository.objects.aget(name="fk-repo")
    assert str(repo.git_instance_credential_id) == str(inst.id)
    assert not await GitCredential.objects.filter(repository=repo).aexists()


@pytest.mark.asyncio
async def test_create_with_host_match_no_token(user: User, space: Space) -> None:
    """无自有 token + host 自动匹配实例池 → 建仓成功。"""
    await GitInstanceCredential.objects.acreate(
        host="gitlab.example.com", encrypted_token=encrypt_value("host-tok")
    )
    resp = await _post_create(AsyncClient(), user, {
        "name": "host-repo",
        "git_url": "https://gitlab.example.com/g/host.git",
        "git_platform": "gitlab",
        "space_ids": [str(space.id)],
    })
    assert resp.status_code == 201, resp.content


@pytest.mark.asyncio
async def test_create_no_token_no_provider_fails(user: User, space: Space) -> None:
    """无自有 token + 无 FK + host 无匹配 → 400 fail-loud。"""
    resp = await _post_create(AsyncClient(), user, {
        "name": "bad-repo",
        "git_url": "https://no-match.example.com/g/p.git",
        "git_platform": "gitlab",
        "space_ids": [str(space.id)],
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# has_credential
# ---------------------------------------------------------------------------


def test_has_credential_true_for_host_match() -> None:
    from repositories.serializers import RepositorySerializer

    GitInstanceCredential.objects.create(
        host="gitlab.example.com", encrypted_token=encrypt_value("host-tok")
    )
    repo = _repo()
    assert RepositorySerializer().get_has_credential(repo) is True


def test_has_credential_false_when_unresolvable() -> None:
    from repositories.serializers import RepositorySerializer

    repo = _repo(git_url="https://no-match.example.com/g/p.git")
    assert RepositorySerializer().get_has_credential(repo) is False
