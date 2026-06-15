"""git_credentials 解析器单测（Phase 26 REPO-01）。

覆盖凭证解析优先级与安全契约：
- Test A（向后兼容）：per-repo token 存在时优先返回，即便同 host 也有实例凭证。
- Test B（实例池 fallback）：无 per-repo token，按 host 命中实例凭证。
- Test C（多仓共享）：同 host 的两个仓库共享同一实例凭证。
- Test D（无凭证）：无 per-repo token 且 host 无实例凭证 → None（不抛、不伪造）。
- Test E（host 归一）：HTTPS 与 SSH 解析出同一归一化 host。
- Test F（不泄漏）：解析过程不向日志写入 token 明文。
"""

from __future__ import annotations

import logging

import pytest

from common.encryption import encrypt_value
from repositories.models import (
    AuthType,
    GitCredential,
    GitInstanceCredential,
    GitPlatform,
    Repository,
)
from services.git_credentials import (
    _extract_git_host,
    resolve_git_token_sync,
)


class TestExtractGitHost:
    def test_https_host(self) -> None:
        assert _extract_git_host("https://gitlab.example.com/ns/p.git") == "gitlab.example.com"

    def test_ssh_host(self) -> None:
        assert _extract_git_host("git@gitlab.example.com:ns/p.git") == "gitlab.example.com"

    def test_https_and_ssh_same_normalized_host(self) -> None:
        """Test E：HTTPS 与 SSH 同实例解析出同一归一化 host。"""
        https = _extract_git_host("https://Gitlab.Example.com/ns/p.git")
        ssh = _extract_git_host("git@gitlab.example.com:ns/p.git")
        assert https == ssh == "gitlab.example.com"

    def test_https_with_port_preserved(self) -> None:
        assert _extract_git_host("https://gitlab.example.com:8443/ns/p.git") == (
            "gitlab.example.com:8443"
        )

    def test_https_userinfo_with_port_preserved(self) -> None:
        """HI-01：含 userinfo 的 HTTPS URL 不得被 SSH 正则误吞而丢端口（威胁 T-26-03）。"""
        assert _extract_git_host(
            "https://oauth2:tok@gitlab.example.com:8443/g/r.git"
        ) == "gitlab.example.com:8443"
        assert _extract_git_host(
            "https://gitlab-ci-token@git.corp:8443/ns/repo.git"
        ) == "git.corp:8443"

    def test_https_userinfo_without_port_unchanged(self) -> None:
        """无端口的 userinfo URL 仍解析出纯 host。"""
        assert _extract_git_host(
            "https://oauth2:tok@gitlab.example.com/g/r.git"
        ) == "gitlab.example.com"

    def test_http_scheme_with_userinfo(self) -> None:
        assert _extract_git_host(
            "http://user@git.internal:8080/ns/p.git"
        ) == "git.internal:8080"

    def test_ssh_scheme_strips_userinfo(self) -> None:
        assert _extract_git_host(
            "ssh://git@gitlab.example.com:22/ns/p.git"
        ) == "gitlab.example.com:22"

    def test_same_domain_different_port_distinct_hosts(self) -> None:
        """同域不同端口必须解析为不同 host key，确保命中各自实例凭证（威胁 T-26-03）。"""
        portless = _extract_git_host("https://oauth2:tok@gitlab.internal/ns/p.git")
        ported = _extract_git_host("https://oauth2:tok@gitlab.internal:8443/ns/p.git")
        assert portless == "gitlab.internal"
        assert ported == "gitlab.internal:8443"
        assert portless != ported

    def test_unparseable_returns_none(self) -> None:
        assert _extract_git_host("") is None
        assert _extract_git_host("not-a-url") is None


@pytest.fixture
def _repo_factory(db):
    def _make(git_url: str, name: str = "r") -> Repository:
        return Repository.objects.create(
            name=name,
            git_url=git_url,
            git_platform="gitlab",
            default_branch="main",
        )

    return _make


class TestResolveGitToken:
    def test_a_per_repo_token_wins(self, _repo_factory) -> None:
        """Test A：per-repo token 优先于同 host 实例凭证。"""
        repo = _repo_factory("https://gitlab.example.com/ns/p.git")
        GitCredential.objects.create(
            repository=repo,
            auth_type=AuthType.ACCESS_TOKEN,
            encrypted_token=encrypt_value("per-repo-token"),
        )
        GitInstanceCredential.objects.create(
            host="gitlab.example.com",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("instance-token"),
        )
        assert resolve_git_token_sync(repo) == "per-repo-token"

    def test_b_instance_pool_fallback(self, _repo_factory) -> None:
        """Test B：无 per-repo token → 按 host 命中实例凭证。"""
        repo = _repo_factory("https://gitlab.example.com/ns/p.git")
        GitInstanceCredential.objects.create(
            host="gitlab.example.com",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("instance-token"),
        )
        assert resolve_git_token_sync(repo) == "instance-token"

    def test_c_two_repos_share_one_instance_credential(self, _repo_factory) -> None:
        """Test C：同 host 的两仓共享同一实例凭证。"""
        repo_a = _repo_factory("https://gitlab.example.com/ns/a.git", name="a")
        repo_b = _repo_factory("git@gitlab.example.com:ns/b.git", name="b")
        GitInstanceCredential.objects.create(
            host="gitlab.example.com",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("shared-token"),
        )
        assert resolve_git_token_sync(repo_a) == "shared-token"
        assert resolve_git_token_sync(repo_b) == "shared-token"

    def test_d_no_credential_returns_none(self, _repo_factory) -> None:
        """Test D：无 per-repo token 且 host 无实例凭证 → None。"""
        repo = _repo_factory("https://gitlab.other.com/ns/p.git")
        assert resolve_git_token_sync(repo) is None

    def test_userinfo_url_with_port_hits_ported_instance(self, _repo_factory) -> None:
        """HI-01：含 userinfo + 端口的仓库 URL 命中 host:port 实例凭证（威胁 T-26-03）。"""
        repo = _repo_factory("https://oauth2:tok@gitlab.internal:8443/ns/p.git")
        GitInstanceCredential.objects.create(
            host="gitlab.internal:8443",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("ported-token"),
        )
        assert resolve_git_token_sync(repo) == "ported-token"

    def test_same_domain_different_port_route_to_distinct_credentials(
        self, _repo_factory
    ) -> None:
        """HI-01：同域不同端口路由到各自实例凭证，不串 token（威胁 T-26-03）。"""
        repo_portless = _repo_factory(
            "https://oauth2:tok@gitlab.internal/ns/a.git", name="a"
        )
        repo_ported = _repo_factory(
            "https://oauth2:tok@gitlab.internal:8443/ns/b.git", name="b"
        )
        GitInstanceCredential.objects.create(
            host="gitlab.internal",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("portless-token"),
        )
        GitInstanceCredential.objects.create(
            host="gitlab.internal:8443",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("ported-token"),
        )
        assert resolve_git_token_sync(repo_portless) == "portless-token"
        assert resolve_git_token_sync(repo_ported) == "ported-token"

    def test_per_repo_credential_without_token_falls_through(self, _repo_factory) -> None:
        """per-repo 凭证存在但无 token（如 SSH key）→ 落到实例池。"""
        repo = _repo_factory("https://gitlab.example.com/ns/p.git")
        GitCredential.objects.create(
            repository=repo,
            auth_type=AuthType.SSH_KEY,
            encrypted_token="",
        )
        GitInstanceCredential.objects.create(
            host="gitlab.example.com",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value("instance-token"),
        )
        assert resolve_git_token_sync(repo) == "instance-token"

    def test_f_token_not_in_logs(self, _repo_factory, caplog) -> None:
        """Test F：解析过程不向日志写入 token 明文。"""
        secret = "super-secret-token-value"
        repo = _repo_factory("https://gitlab.example.com/ns/p.git")
        GitInstanceCredential.objects.create(
            host="gitlab.example.com",
            provider=GitPlatform.GITLAB,
            encrypted_token=encrypt_value(secret),
        )
        with caplog.at_level(logging.DEBUG):
            assert resolve_git_token_sync(repo) == secret
        assert secret not in caplog.text
