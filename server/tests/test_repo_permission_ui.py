"""implementation 仓库关联权限 API 测试。

测试 SpaceRepository 模型扩展（permission_level 字段）和
项目仓库关联管理 CRUD API 的完整行为。
"""

import pytest
from rest_framework.test import APIClient

from projects.models import Space, SpaceRepository
from repositories.models import Repository


@pytest.fixture
def second_repository(db) -> Repository:
    """创建第二个测试仓库。"""
    return Repository.objects.create(
        name="Second Repo",
        git_url="https://github.com/test/repo2.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.fixture
def third_repository(db) -> Repository:
    """创建第三个测试仓库。"""
    return Repository.objects.create(
        name="Third Repo",
        git_url="https://github.com/test/repo3.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.fixture
def project_admin_client(user, project, project_memberships) -> APIClient:
    """项目 admin 角色客户端（非 superuser）。"""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project_member_client(member_user, project, project_memberships) -> APIClient:
    """项目 member 角色客户端。"""
    client = APIClient()
    client.force_authenticate(user=member_user)
    return client


@pytest.fixture
def project_viewer_client(viewer_user, project, project_memberships) -> APIClient:
    """项目 viewer 角色客户端。"""
    client = APIClient()
    client.force_authenticate(user=viewer_user)
    return client


@pytest.mark.django_db
class TestProjectRepositoryLink:
    """项目仓库关联 API 测试。"""

    def test_project_repo_link_create_batch(
        self, project_admin_client: APIClient, project: Space,
        second_repository: Repository, third_repository: Repository,
    ) -> None:
        """管理员可以批量关联仓库。"""
        response = project_admin_client.post(
            f"/api/spaces/{project.id}/repositories/",
            {"repository_ids": [str(second_repository.id), str(third_repository.id)]},
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["created"]) == 2

    def test_project_repo_link_duplicate_skip(
        self, project_admin_client: APIClient, project: Space,
        repository: Repository, second_repository: Repository,
    ) -> None:
        """重复关联自动跳过（project fixture 已关联 repository）。"""
        response = project_admin_client.post(
            f"/api/spaces/{project.id}/repositories/",
            {"repository_ids": [str(repository.id), str(second_repository.id)]},
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        # repository 已关联应跳过，只创建 second_repository
        assert len(data["created"]) == 1
        assert len(data["skipped"]) == 1

    def test_project_repo_link_permission_default(
        self, project_admin_client: APIClient, project: Space,
        second_repository: Repository,
    ) -> None:
        """默认权限为 read_write。"""
        project_admin_client.post(
            f"/api/spaces/{project.id}/repositories/",
            {"repository_ids": [str(second_repository.id)]},
            format="json",
        )
        link = SpaceRepository.objects.get(
            space=project, repository=second_repository,
        )
        assert link.permission_level == "read_write"

    def test_project_repo_link_update_permission(
        self, project_admin_client: APIClient, project: Space,
        repository: Repository,
    ) -> None:
        """修改关联的 permission_level。"""
        link = SpaceRepository.objects.get(
            space=project, repository=repository,
        )
        response = project_admin_client.patch(
            f"/api/spaces/{project.id}/repositories/{link.pk}/",
            {"permission_level": "read_only"},
            format="json",
        )
        assert response.status_code == 200
        link.refresh_from_db()
        assert link.permission_level == "read_only"

    def test_project_repo_link_delete(
        self, project_admin_client: APIClient, project: Space,
        repository: Repository,
    ) -> None:
        """移除关联。"""
        link = SpaceRepository.objects.get(
            space=project, repository=repository,
        )
        response = project_admin_client.delete(
            f"/api/spaces/{project.id}/repositories/{link.pk}/",
        )
        assert response.status_code == 204
        assert not SpaceRepository.objects.filter(
            space=project, repository=repository,
        ).exists()

    def test_project_repo_link_list_viewer(
        self, project_viewer_client: APIClient, project: Space,
        repository: Repository,
    ) -> None:
        """viewer 可查看项目关联的仓库列表。"""
        response = project_viewer_client.get(
            f"/api/spaces/{project.id}/repositories/",
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_project_repo_link_create_forbidden_member(
        self, project_member_client: APIClient, project: Space,
        second_repository: Repository,
    ) -> None:
        """member 无法创建关联。"""
        response = project_member_client.post(
            f"/api/spaces/{project.id}/repositories/",
            {"repository_ids": [str(second_repository.id)]},
            format="json",
        )
        assert response.status_code == 403

    def test_project_repo_link_create_forbidden_viewer(
        self, project_viewer_client: APIClient, project: Space,
        second_repository: Repository,
    ) -> None:
        """viewer 无法创建关联。"""
        response = project_viewer_client.post(
            f"/api/spaces/{project.id}/repositories/",
            {"repository_ids": [str(second_repository.id)]},
            format="json",
        )
        assert response.status_code == 403

    def test_me_api_returns_memberships(
        self, project_admin_client: APIClient, project: Space,
    ) -> None:
        """/me 返回 space_memberships 含 role（rename: project_memberships → space_memberships）。"""
        response = project_admin_client.get("/api/auth/me/")
        assert response.status_code == 200
        data = response.json()
        assert "space_memberships" in data
        memberships = data["space_memberships"]
        assert len(memberships) >= 1
        assert "role" in memberships[0]

    def test_repository_list_linked_count(
        self, project_admin_client: APIClient, repository: Repository,
    ) -> None:
        """仓库列表返回 linked_spaces_count。"""
        response = project_admin_client.get("/api/repositories/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert "linked_spaces_count" in data[0]
        # repository 已关联 project，count >= 1
        repo_data = next(r for r in data if r["id"] == str(repository.id))
        assert repo_data["linked_spaces_count"] >= 1
