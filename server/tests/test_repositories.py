"""仓库端点测试。

使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""

import pytest
from django.urls import reverse
from rest_framework import status

from permissions.services import PermissionService

# ============================================================================
# 仓库列表和创建测试
# ============================================================================


@pytest.mark.django_db
class TestRepositoryListCreate:
    """仓库列表和创建接口测试。"""

    def test_list_repositories_empty(self, authenticated_client, urls):
        """测试空仓库列表。"""
        response = authenticated_client.get(urls.repository_list)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_list_repositories_with_data(self, authenticated_client, repository, urls):
        """测试有数据的仓库列表。"""
        response = authenticated_client.get(urls.repository_list)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Test Repo"

    def test_create_repository_with_token(
        self, authenticated_client, project_without_repo, urls
    ):
        """测试使用 token 创建仓库（必须关联至少一个空间）。"""
        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "New Repo",
                "git_url": "https://github.com/test/new-repo.git",
                "git_platform": "github",
                "default_branch": "main",
                "access_token": "ghp_test_token_12345",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Repo"
        assert response.data["has_credential"] is True
        # 创建即建立空间关联
        assert project_without_repo.repositories.filter(
            id=response.data["id"]
        ).exists()

    def test_create_repository_without_space_creates_orphan(
        self, authenticated_client, user, urls
    ):
        """不带 space_ids 建仓成功，产出「孤儿仓库」（#9：space_ids 可选，允许后补绑定）。

        放宽 space_ids 必填的补偿控制是仓库级管理权限收口（#11）：孤儿仓库未关联
        任何空间，`can_admin_repository` 对非超管恒 False —— 建仓者本人也无法对其
        执行索引/建立知识/敏感信息等管理操作。此处一并断言，确保放宽不等于失守。
        """
        from repositories.models import Repository

        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "No Space Repo",
                "git_url": "https://github.com/test/repo.git",
                "access_token": "ghp_test_token_12345",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        repo = Repository.objects.get(id=response.data["id"])
        # 孤儿仓库：未关联任何空间
        assert repo.spaces.count() == 0
        # 补偿控制：孤儿仓库仅超管可管理，建仓者（普通用户）无管理权
        assert PermissionService.can_admin_repository(user, str(repo.id)) is False

    def test_create_repository_head_branch_as_default(
        self, authenticated_client, project_without_repo, urls
    ):
        """未显式选默认分支时自动采用 HEAD 分支。"""
        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "Head Branch Repo",
                "git_url": "https://github.com/test/head-repo.git",
                "git_platform": "github",
                "access_token": "ghp_test_token_12345",
                "remote_head_branch": "develop",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["default_branch"] == "develop"
        assert response.data["remote_head_branch"] == "develop"

    def test_create_repository_empty_token(
        self, authenticated_client, project_without_repo, urls
    ):
        """测试使用空 token 创建仓库失败。"""
        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "No Token Repo",
                "git_url": "https://github.com/test/repo.git",
                "access_token": "   ",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_repository_converts_ssh_git_url(
        self, authenticated_client, project_without_repo, urls
    ):
        """创建仓库时 SSH URL 自动转换为 HTTPS（任务容器无 ssh，token 认证仅支持 HTTPS）。"""
        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "SSH Repo",
                "git_url": "git@github.com:test/repo.git",
                "access_token": "ghp_test_token_12345",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["git_url"] == "https://github.com/test/repo.git"

    def test_create_repository_rejects_non_git_protocol(
        self, authenticated_client, project_without_repo, urls
    ):
        """无法转换的非 http(s) 协议仍然拒绝。"""
        response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "FTP Repo",
                "git_url": "ftp://example.com/test/repo.git",
                "access_token": "ghp_test_token_12345",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "仅支持 HTTPS" in str(response.data)

    def test_create_repository_unauthenticated(self, api_client, urls):
        """测试未认证用户无法创建仓库。"""
        response = api_client.post(
            urls.repository_list,
            {"name": "New Repo", "git_url": "https://github.com/test/repo.git"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# 仓库详情测试
# ============================================================================


@pytest.mark.django_db
class TestRepositoryDetail:
    """仓库详情接口测试。"""

    def test_get_repository(self, authenticated_client, repository, urls):
        """测试获取单个仓库。"""
        response = authenticated_client.get(urls.repository_detail(repository.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Repo"
        assert "spaces" in response.data

    def test_update_repository(self, authenticated_client, repository, urls):
        """测试更新仓库。"""
        response = authenticated_client.patch(
            urls.repository_detail(repository.id),
            {"name": "Updated Repo"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Repo"

    def test_update_repository_converts_ssh_git_url(
        self, authenticated_client, repository, urls
    ):
        """更新仓库时 SSH URL 自动转换为 HTTPS。"""
        response = authenticated_client.patch(
            urls.repository_detail(repository.id),
            {"git_url": "git@gitlab.example.com:frontend/example-app.git"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["git_url"] == "https://gitlab.example.com/frontend/example-app.git"

    def test_delete_repository(self, authenticated_client, repository, urls):
        """测试删除仓库。"""
        response = authenticated_client.delete(urls.repository_detail(repository.id))

        assert response.status_code == status.HTTP_204_NO_CONTENT


# ============================================================================
# 仓库凭据测试
# ============================================================================


@pytest.mark.django_db
class TestRepositoryCredential:
    """仓库凭据接口测试。"""

    def test_get_credential(self, authenticated_client, project_without_repo, urls):
        """测试获取仓库凭据。"""
        # 创建带凭据的仓库
        create_response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "Repo With Cred",
                "git_url": "https://github.com/test/repo.git",
                "access_token": "test_token",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )
        repo_id = create_response.data["id"]

        response = authenticated_client.get(urls.repository_credential(repo_id))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["has_access_token"] is True
        assert response.data["auth_type"] == "access_token"

    def test_get_credential_not_found(self, authenticated_client, repository, urls):
        """测试获取不存在的凭据。"""
        response = authenticated_client.get(urls.repository_credential(repository.id))

        # API returns 200 with null when credential doesn't exist
        assert response.status_code == status.HTTP_200_OK
        assert response.data is None

    def test_delete_credential(self, authenticated_client, project_without_repo, urls):
        """测试删除仓库凭据。"""
        # 创建带凭据的仓库
        create_response = authenticated_client.post(
            urls.repository_list,
            {
                "name": "Repo To Delete Cred",
                "git_url": "https://github.com/test/repo.git",
                "access_token": "test_token",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )
        repo_id = create_response.data["id"]

        response = authenticated_client.delete(urls.repository_credential(repo_id))

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证已删除 - API returns 200 with null when credential doesn't exist
        response = authenticated_client.get(urls.repository_credential(repo_id))
        assert response.status_code == status.HTTP_200_OK
        assert response.data is None


@pytest.mark.django_db
class TestRepositoryConnection:
    """仓库连接测试接口。"""

    def test_test_connection_converts_ssh_git_url(self, authenticated_client, monkeypatch):
        """测试连接接口把 SSH URL 转成 HTTPS 后再探测（不再 400 拒绝）。"""
        import subprocess
        from types import SimpleNamespace

        captured_cmds: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return SimpleNamespace(
                returncode=0,
                stdout="ref: refs/heads/main\tHEAD\nabc123\trefs/heads/main\n",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        response = authenticated_client.post(
            reverse("test-connection"),
            {
                "git_url": "git@github.com:test/repo.git",
                "access_token": "ghp_test_token_12345",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        # ls-remote 用的是转换 + 注入 token 后的 HTTPS 地址
        auth_url = captured_cmds[0][captured_cmds[0].index("--symref") + 1]
        assert auth_url == "https://oauth2:ghp_test_token_12345@github.com/test/repo.git"

    def test_test_connection_rejects_non_git_protocol(self, authenticated_client):
        """无法转换的非 http(s) 协议仍然 400 拒绝。"""
        response = authenticated_client.post(
            reverse("test-connection"),
            {
                "git_url": "ftp://example.com/test/repo.git",
                "access_token": "ghp_test_token_12345",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False
        assert "仅支持 HTTPS" in response.data["error"]


# ============================================================================
# SSH URL → HTTPS 转换（纯函数单测）
# ============================================================================


class TestSshGitUrlToHttps:
    """ssh_git_url_to_https：SSH 两种形态转 HTTPS，非 SSH 原样返回。"""

    def test_scp_style(self):
        from repositories.serializers import ssh_git_url_to_https

        assert (
            ssh_git_url_to_https("git@gitlab.example.com:frontend/example-app.git")
            == "https://gitlab.example.com/frontend/example-app.git"
        )

    def test_ssh_protocol_with_port(self):
        from repositories.serializers import ssh_git_url_to_https

        # ssh 端口必须丢弃（https 走 443）
        assert (
            ssh_git_url_to_https("ssh://git@gitlab.example.com:2222/group/repo.git")
            == "https://gitlab.example.com/group/repo.git"
        )

    def test_ssh_protocol_without_user(self):
        from repositories.serializers import ssh_git_url_to_https

        assert (
            ssh_git_url_to_https("ssh://gitlab.example.com/group/repo.git")
            == "https://gitlab.example.com/group/repo.git"
        )

    def test_https_passthrough(self):
        from repositories.serializers import ssh_git_url_to_https

        assert (
            ssh_git_url_to_https("https://github.com/test/repo.git")
            == "https://github.com/test/repo.git"
        )

    def test_strips_whitespace(self):
        from repositories.serializers import ssh_git_url_to_https

        assert (
            ssh_git_url_to_https("  git@github.com:a/b.git\n")
            == "https://github.com/a/b.git"
        )


# ============================================================================
# 分支解析与排序（纯函数单测）
# ============================================================================


class TestBranchParsingAndSorting:
    """ls-remote --symref 输出解析 + 分支排序规则。"""

    def test_parse_symref_head(self):
        from repositories.views import _parse_ls_remote_refs

        stdout = (
            "ref: refs/heads/develop\tHEAD\n"
            "aaa111\tHEAD\n"
            "aaa111\trefs/heads/develop\n"
            "bbb222\trefs/heads/main\n"
            "ccc333\trefs/heads/feature/x\n"
        )
        branches, head = _parse_ls_remote_refs(stdout)
        assert head == "develop"
        assert set(branches) == {"develop", "main", "feature/x"}

    def test_parse_without_symref_falls_back_to_sha_match(self):
        from repositories.views import _parse_ls_remote_refs

        stdout = (
            "aaa111\tHEAD\n"
            "aaa111\trefs/heads/master\n"
            "aaa111\trefs/heads/release\n"
            "bbb222\trefs/heads/dev\n"
        )
        branches, head = _parse_ls_remote_refs(stdout)
        # 多个分支命中 HEAD sha 时偏向 main/master
        assert head == "master"
        assert set(branches) == {"master", "release", "dev"}

    def test_sort_branches_priority(self):
        from repositories.views import _sort_branches

        branches = ["zeta", "alpha", "master", "main", "develop"]
        activity = {"zeta": 200, "alpha": 100}
        result = _sort_branches(branches, head_branch="develop", activity=activity)
        # HEAD > main/master > 活跃度降序 > 字典序
        assert result == ["develop", "main", "master", "zeta", "alpha"]

    def test_sort_branches_without_activity_lexicographic(self):
        from repositories.views import _sort_branches

        result = _sort_branches(["c", "b", "main", "a"], head_branch=None)
        assert result == ["main", "a", "b", "c"]


# ============================================================================
# 仓库侧关联空间管理
# ============================================================================


@pytest.mark.django_db
class TestRepositorySpaces:
    """GET/PUT /repositories/{id}/spaces/。"""

    def _url(self, repo_id):
        return f"/api/repositories/{repo_id}/spaces/"

    def test_get_linked_spaces(self, authenticated_client, project, repository):
        response = authenticated_client.get(self._url(repository.id))

        assert response.status_code == status.HTTP_200_OK
        assert [s["name"] for s in response.data] == ["Test Space"]

    def test_put_replaces_links(
        self, authenticated_client, project, second_project, repository
    ):
        response = authenticated_client.put(
            self._url(repository.id),
            {"space_ids": [str(second_project.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert [s["id"] for s in response.data] == [str(second_project.id)]
        assert not project.repositories.filter(id=repository.id).exists()
        assert second_project.repositories.filter(id=repository.id).exists()

    def test_put_empty_unbinds_all(self, authenticated_client, user, project, repository):
        """空数组＝解绑全部空间（#9：不再强制「至少一个空间」）。

        解绑后仓库退化为孤儿仓库，按 #11 仅超管可管理 —— 一并断言，确保放宽
        校验没有顺带放宽权限。
        """
        response = authenticated_client.put(
            self._url(repository.id),
            {"space_ids": []},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
        # 全部关联被解除
        assert not project.repositories.filter(id=repository.id).exists()
        # 解绑后成为孤儿仓库：非超管无管理权
        assert PermissionService.can_admin_repository(user, str(repository.id)) is False

    def test_put_non_list_rejected(self, authenticated_client, project, repository):
        """space_ids 非列表仍应 400，且原有关联保持不变（类型校验未被放宽）。"""
        response = authenticated_client.put(
            self._url(repository.id),
            {"space_ids": "not-a-list"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert project.repositories.filter(id=repository.id).exists()

    def test_put_unknown_space_rejected(self, authenticated_client, repository):
        import uuid

        response = authenticated_client.put(
            self._url(repository.id),
            {"space_ids": [str(uuid.uuid4())]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
