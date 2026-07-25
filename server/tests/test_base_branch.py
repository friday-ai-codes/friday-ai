"""base_branch 字段及分支列表 API 测试。

覆盖 work item（模型/序列化器）、work item（分支列表/推荐）、work item（校验）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.urls import reverse

from repositories.models import Repository
from repositories.serializers import RepositorySerializer


# ============================================================================
# TestBaseBranchModel — 模型和序列化器
# ============================================================================


@pytest.mark.django_db
class TestBaseBranchModel:
    def test_base_branch_field_exists(self) -> None:
        field = Repository._meta.get_field("base_branch")
        assert field.max_length == 100
        assert field.null is True
        assert field.blank is True

    def test_base_branch_default_is_none(self, repository: Repository) -> None:
        assert repository.base_branch is None

    def test_base_branch_in_serializer(self, repository: Repository) -> None:
        data = RepositorySerializer(repository).data
        assert "base_branch" in data
        assert data["base_branch"] is None


# ============================================================================
# TestBaseBranchCreate — 创建/兼容性
# ============================================================================


@pytest.mark.django_db
class TestBaseBranchCreate:
    def test_create_repository_with_base_branch(self) -> None:
        repo = Repository.objects.create(
            name="Branch Repo",
            git_url="https://github.com/test/branch-repo.git",
            git_platform="github",
            default_branch="main",
            base_branch="develop",
        )
        repo.refresh_from_db()
        assert repo.base_branch == "develop"

    def test_create_repository_without_base_branch(self) -> None:
        repo = Repository.objects.create(
            name="No Branch Repo",
            git_url="https://github.com/test/no-branch.git",
            git_platform="github",
            default_branch="main",
        )
        repo.refresh_from_db()
        assert repo.base_branch is None


# ============================================================================
# TestBaseBranchUpdate — PATCH 更新
# ============================================================================


@pytest.mark.django_db
class TestBaseBranchUpdate:
    @patch("repositories.views._validate_base_branch", new_callable=AsyncMock, return_value=True)
    def test_update_repository_base_branch(
        self, mock_validate, authenticated_client, repository_in_user_space
    ) -> None:
        # repository_in_user_space：仓库可见性按空间成员过滤（#9/#11），孤儿仓库普通用户 404
        repository = repository_in_user_space
        url = reverse("repository-detail", args=[repository.id])
        response = authenticated_client.patch(
            url,
            {"base_branch": "feature-x"},
            format="json",
        )
        assert response.status_code == 200
        repository.refresh_from_db()
        assert repository.base_branch == "feature-x"


# ============================================================================
# TestBranchListAPI — 完整分支列表 + 推荐分支
# ============================================================================


def _make_ls_remote_stdout(branch_names: list[str]) -> str:
    """构造 git ls-remote --heads 的 stdout。"""
    lines = []
    for name in branch_names:
        lines.append(f"abc1234\trefs/heads/{name}")
    return "\n".join(lines)


def _mock_subprocess_result(branch_names: list[str]) -> MagicMock:
    """构造 subprocess.run 的返回值。"""
    result = MagicMock()
    result.returncode = 0
    result.stdout = _make_ls_remote_stdout(branch_names)
    result.stderr = ""
    return result


@pytest.mark.django_db
class TestBranchListAPI:
    @patch("subprocess.run")
    def test_test_connection_returns_all_branches(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        branches = [f"branch-{i}" for i in range(15)] + ["main"]
        mock_run.return_value = _mock_subprocess_result(branches)

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["branches"]) == 16

    @patch("subprocess.run")
    def test_test_connection_returns_recommended_branch(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        branches = ["feature-a", "main", "release-1.0"]
        mock_run.return_value = _mock_subprocess_result(branches)

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        data = response.json()
        assert data["recommended_branch"] == "main"

    @patch("subprocess.run")
    def test_test_connection_recommended_priority(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        branches = ["master", "develop", "feature-b"]
        mock_run.return_value = _mock_subprocess_result(branches)

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        data = response.json()
        assert data["recommended_branch"] == "master"

    @patch("subprocess.run")
    def test_test_connection_no_recommended_branch(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        branches = ["release-1.0", "hotfix-1", "feature-c"]
        mock_run.return_value = _mock_subprocess_result(branches)

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        data = response.json()
        assert data["recommended_branch"] is None

    @patch("subprocess.run")
    def test_test_connection_branches_sorted(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        """排序规则：HEAD（此处无）> main/master > 其余字典序。"""
        branches = ["zebra", "alpha", "main"]
        mock_run.return_value = _mock_subprocess_result(branches)

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        data = response.json()
        assert data["branches"] == ["main", "alpha", "zebra"]

    @patch("subprocess.run")
    def test_test_connection_head_branch_first(
        self, mock_run, authenticated_client, repository_with_credential
    ) -> None:
        """symref 探测到的 HEAD 分支排第一且作为推荐分支，并缓存到模型。"""
        result = MagicMock()
        result.returncode = 0
        result.stdout = (
            "ref: refs/heads/develop\tHEAD\n"
            "abc1234\tHEAD\n"
            "abc1234\trefs/heads/develop\n"
            "def5678\trefs/heads/main\n"
            "aaa9999\trefs/heads/alpha\n"
        )
        result.stderr = ""
        mock_run.return_value = result

        url = reverse("repository-test-connection", args=[repository_with_credential.id])
        response = authenticated_client.post(url)

        data = response.json()
        assert data["head_branch"] == "develop"
        assert data["recommended_branch"] == "develop"
        assert data["branches"][0] == "develop"
        assert data["branches"][1] == "main"

        repository_with_credential.refresh_from_db()
        assert repository_with_credential.remote_head_branch == "develop"


# ============================================================================
# TestBaseBranchValidation — 保存时校验
# ============================================================================


@pytest.mark.django_db
class TestBaseBranchValidation:
    @patch("repositories.views._validate_base_branch", new_callable=AsyncMock, return_value=False)
    def test_invalid_branch_returns_400(
        self, mock_validate, authenticated_client, project_without_repo
    ) -> None:
        url = reverse("repository-list")
        response = authenticated_client.post(
            url,
            {
                "name": "Validation Repo",
                "git_url": "https://github.com/test/val.git",
                "git_platform": "github",
                "default_branch": "main",
                "base_branch": "nonexistent-branch",
                "access_token": "ghp_test_token",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "nonexistent-branch" in str(data["base_branch"])

    @patch("repositories.views._validate_base_branch", new_callable=AsyncMock, return_value=True)
    def test_valid_branch_passes(
        self, mock_validate, authenticated_client, project_without_repo
    ) -> None:
        url = reverse("repository-list")
        response = authenticated_client.post(
            url,
            {
                "name": "Valid Branch Repo",
                "git_url": "https://github.com/test/valid.git",
                "git_platform": "github",
                "default_branch": "main",
                "base_branch": "develop",
                "access_token": "ghp_test_token",
                "space_ids": [str(project_without_repo.id)],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["base_branch"] == "develop"

    @patch("repositories.views._validate_base_branch", new_callable=AsyncMock, return_value=False)
    def test_update_invalid_branch_returns_400(
        self, mock_validate, authenticated_client, repository_with_credential, repository_in_user_space
    ) -> None:
        # 同上：repository_with_credential 建在 repository 之上，需一并授予可见性
        url = reverse("repository-detail", args=[repository_with_credential.id])
        response = authenticated_client.patch(
            url,
            {"base_branch": "bad-branch"},
            format="json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "bad-branch" in str(data)
