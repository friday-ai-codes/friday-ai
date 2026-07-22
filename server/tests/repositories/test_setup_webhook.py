"""Quick 260722-npg：GitLab 仓库一键自动配置 push webhook。

覆盖：
- 平台守卫：非 GitLab 仓库 → 400（提示手动配置）。
- 凭证守卫：无 token → 400（提示配置凭证）。
- 成功路径：mock GitLabClient.ensure_push_webhook，断言回调 URL / secret /
  branch_filter 传参正确，webhook_secret 自动生成、auto_index_enabled 被启用。
- 失败路径：GitLab 侧失败（如 403 权限不足）→ 400 + 已翻译中文提示。
- translate_gitlab_hook_error：401/403/404/422 → 中文提示，不含上游响应体。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from repositories.models import Repository
from services.git_platform.gitlab_client import translate_gitlab_hook_error
from services.git_platform.models import WebhookSetupResult

pytestmark = pytest.mark.django_db(transaction=True)

SETUP_URL = "/api/repositories/{repo_id}/setup-webhook/"


@pytest.fixture
def gitlab_repository(db):
    """GitLab 平台的测试仓库。"""
    return Repository.objects.create(
        name="GitLab Repo",
        git_url="https://gitlab.example.com/group/proj.git",
        git_platform="gitlab",
        default_branch="main",
        auto_index_enabled=False,
    )


@pytest.fixture
def gitlab_repository_with_credential(db, gitlab_repository):
    """带 per-repo access token 凭证的 GitLab 仓库。"""
    from common.encryption import encrypt_value
    from repositories.models import AuthType, GitCredential

    GitCredential.objects.create(
        repository=gitlab_repository,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("glpat-test-token-xyz"),
    )
    return gitlab_repository


class TestSetupWebhookGuards:
    def test_non_gitlab_platform_rejected(self, authenticated_admin_client, repository):
        """GitHub 仓库 → 400，提示仅支持 GitLab。"""
        resp = authenticated_admin_client.post(
            SETUP_URL.format(repo_id=repository.id), {}, format="json"
        )
        assert resp.status_code == 400
        assert "GitLab" in resp.json()["detail"]

    def test_missing_credential_rejected(self, authenticated_admin_client, gitlab_repository):
        """无任何 Git 凭证 → 400，提示配置凭证。"""
        resp = authenticated_admin_client.post(
            SETUP_URL.format(repo_id=gitlab_repository.id), {}, format="json"
        )
        assert resp.status_code == 400
        assert "凭证" in resp.json()["detail"]


class TestSetupWebhookSuccess:
    def test_creates_hook_generates_secret_and_enables_auto_index(
        self, authenticated_admin_client, gitlab_repository_with_credential
    ):
        repo = gitlab_repository_with_credential
        assert not repo.webhook_secret
        assert repo.auto_index_enabled is False

        mock_ensure = AsyncMock(
            return_value=WebhookSetupResult(success=True, action="created", hook_id="7")
        )
        with patch(
            "services.git_platform.gitlab_client.GitLabClient.ensure_push_webhook",
            mock_ensure,
        ):
            resp = authenticated_admin_client.post(
                SETUP_URL.format(repo_id=repo.id), {}, format="json"
            )

        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["action"] == "created"
        assert body["hook_id"] == "7"
        assert body["branch_filter"] == "main"
        assert body["auto_index_enabled"] is True
        assert f"/api/repositories/{repo.id}/webhooks/push/" in body["webhook_url"]

        repo.refresh_from_db()
        assert repo.webhook_secret  # 自动生成
        assert repo.auto_index_enabled is True  # 接收端 fail-closed，顺手启用

        # ensure_push_webhook 收到的 secret 与落库一致、branch filter 用默认分支
        call_kwargs = mock_ensure.call_args.kwargs
        assert call_kwargs["secret"] == repo.webhook_secret
        assert call_kwargs["branch_filter"] == "main"
        assert call_kwargs["url"].endswith(f"/api/repositories/{repo.id}/webhooks/push/")

    def test_branch_filter_override(
        self, authenticated_admin_client, gitlab_repository_with_credential
    ):
        """显式传 branch_filter（含空串 = 全部分支）时透传给 GitLab。"""
        repo = gitlab_repository_with_credential
        mock_ensure = AsyncMock(
            return_value=WebhookSetupResult(success=True, action="updated", hook_id="7")
        )
        with patch(
            "services.git_platform.gitlab_client.GitLabClient.ensure_push_webhook",
            mock_ensure,
        ):
            resp = authenticated_admin_client.post(
                SETUP_URL.format(repo_id=repo.id), {"branch_filter": ""}, format="json"
            )

        assert resp.status_code == 200, resp.content
        assert resp.json()["branch_filter"] == ""
        assert mock_ensure.call_args.kwargs["branch_filter"] == ""

    def test_existing_secret_not_regenerated(
        self, authenticated_admin_client, gitlab_repository_with_credential
    ):
        """已有 secret 时不重新生成（避免使既有 hook 验签失效）。"""
        repo = gitlab_repository_with_credential
        repo.webhook_secret = "existing-secret"
        repo.save(update_fields=["webhook_secret"])

        with patch(
            "services.git_platform.gitlab_client.GitLabClient.ensure_push_webhook",
            AsyncMock(return_value=WebhookSetupResult(success=True, action="updated", hook_id="7")),
        ):
            resp = authenticated_admin_client.post(
                SETUP_URL.format(repo_id=repo.id), {}, format="json"
            )

        assert resp.status_code == 200
        repo.refresh_from_db()
        assert repo.webhook_secret == "existing-secret"


class TestSetupWebhookFailure:
    def test_gitlab_error_translated(
        self, authenticated_admin_client, gitlab_repository_with_credential
    ):
        repo = gitlab_repository_with_credential
        with patch(
            "services.git_platform.gitlab_client.GitLabClient.ensure_push_webhook",
            AsyncMock(
                return_value=WebhookSetupResult(
                    success=False,
                    error="服务账号权限不足：创建 Webhook 需要该 token 对应账号在项目中为 Maintainer 及以上角色，且 PAT 具有 api scope",
                )
            ),
        ):
            resp = authenticated_admin_client.post(
                SETUP_URL.format(repo_id=repo.id), {}, format="json"
            )

        assert resp.status_code == 400
        assert "Maintainer" in resp.json()["detail"]

        # 失败时不应把 auto_index_enabled 打开
        repo.refresh_from_db()
        assert repo.auto_index_enabled is False


class TestTranslateGitlabHookError:
    @pytest.mark.parametrize(
        ("code", "keyword"),
        [
            (401, "凭证无效"),
            (403, "Maintainer"),
            (404, "项目不存在"),
            (422, "内网地址"),
            (500, "HTTP 500"),
        ],
    )
    def test_status_code_translated(self, code, keyword):
        class FakeGitlabError(Exception):
            response_code = None

        exc = FakeGitlabError("upstream body with glpat-SECRET should not leak")
        exc.response_code = code
        message = translate_gitlab_hook_error(exc)
        assert keyword in message
        # 上游响应体/异常文本绝不进入用户提示
        assert "glpat-SECRET" not in message
