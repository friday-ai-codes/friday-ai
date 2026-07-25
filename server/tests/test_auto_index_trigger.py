"""自动索引触发测试

测试覆盖：
- Webhook push 事件接收 + 签名验证（GitHub/GitLab/Gitea）
- APScheduler 定时轮询
- auto_index_enabled 开关
- Webhook 防抖去重
"""

import hashlib
import hmac as hmac_mod
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.models import (
    Repository,
)
from tasks.index_trigger_tasks import (
    _is_duplicate,
    clear_dedup_cache,
    parse_push_event,
    verify_gitlab_token,
    verify_webhook_signature,
)

pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# Webhook 签名验证
# ============================================================================


class TestWebhookSignatureVerification:
    """Webhook work item 签名验证测试。"""

    def test_valid_github_signature(self) -> None:
        payload = b'{"ref":"refs/heads/main","after":"abc123"}'
        secret = "my-secret"
        expected = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={expected}"
        assert verify_webhook_signature(payload, secret, signature) is True

    def test_invalid_signature(self) -> None:
        payload = b'{"ref":"refs/heads/main"}'
        assert verify_webhook_signature(payload, "secret", "sha256=wrong") is False

    def test_raw_hex_signature(self) -> None:
        payload = b"test"
        secret = "key"
        expected = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(payload, secret, expected) is True

    def test_gitlab_token_valid(self) -> None:
        assert verify_gitlab_token("my-token", "my-token") is True

    def test_gitlab_token_invalid(self) -> None:
        assert verify_gitlab_token("my-token", "wrong") is False


# ============================================================================
# Push 事件解析
# ============================================================================


class TestParsePushEvent:
    """Push 事件 payload 解析测试。"""

    def test_github_push(self) -> None:
        payload = {"ref": "refs/heads/main", "after": "abc123"}
        result = parse_push_event("github", payload)
        assert result["ref"] == "refs/heads/main"
        assert result["after"] == "abc123"

    def test_gitlab_push(self) -> None:
        payload = {"ref": "refs/heads/main", "after": "def456", "checkout_sha": "def456"}
        result = parse_push_event("gitlab", payload)
        assert result["after"] == "def456"

    def test_gitea_push(self) -> None:
        payload = {"ref": "refs/heads/main", "after": "ghi789"}
        result = parse_push_event("gitea", payload)
        assert result["after"] == "ghi789"

    def test_unknown_platform(self) -> None:
        result = parse_push_event("bitbucket", {"ref": "x"})
        assert result["ref"] == ""
        assert result["after"] == ""


# ============================================================================
# 防抖去重
# ============================================================================


class TestWebhookDedup:
    """Webhook 防抖去重测试。"""

    def setup_method(self) -> None:
        clear_dedup_cache()

    def test_first_call_not_duplicate(self) -> None:
        assert _is_duplicate("abc123") is False

    def test_second_call_is_duplicate(self) -> None:
        _is_duplicate("abc123")
        assert _is_duplicate("abc123") is True

    def test_different_sha_not_duplicate(self) -> None:
        _is_duplicate("abc123")
        assert _is_duplicate("def456") is False

    @patch("tasks.index_trigger_tasks.time")
    def test_expired_entry_cleaned(self, mock_time: MagicMock) -> None:
        # 第一次调用在 t=0
        mock_time.monotonic.return_value = 0.0
        _is_duplicate("old_sha")

        # 第二次调用在 t=601（超过 600 秒窗口）
        mock_time.monotonic.return_value = 601.0
        assert _is_duplicate("old_sha") is False


# ============================================================================
# work item + Webhook 端点 API 测试
# ============================================================================


class TestRepositoryWebhookView:
    """Webhook 端点集成测试。"""

    @pytest.fixture
    def webhook_repo(self, repository: Repository) -> Repository:
        repository.auto_index_enabled = True
        repository.webhook_secret = "test-secret"
        repository.git_platform = "github"
        repository.save()
        return repository

    def _make_signature(self, payload: bytes, secret: str) -> str:
        h = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={h}"

    @patch("tasks.index_trigger_tasks.clone_and_index_repository", new_callable=AsyncMock)
    def test_webhook_triggers_index(
        self, mock_clone: AsyncMock, api_client, webhook_repo: Repository
    ) -> None:
        mock_clone.return_value = {"status": "success"}
        import json
        payload = json.dumps({"ref": "refs/heads/main", "after": "a" * 40})
        sig = self._make_signature(payload.encode(), "test-secret")

        response = api_client.post(
            f"/api/repositories/{webhook_repo.id}/webhooks/push/",
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "triggered"

    def test_webhook_invalid_signature(self, api_client, webhook_repo: Repository) -> None:
        import json
        payload = json.dumps({"ref": "refs/heads/main", "after": "b" * 40})

        response = api_client.post(
            f"/api/repositories/{webhook_repo.id}/webhooks/push/",
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=invalid",
        )
        assert response.status_code == 401

    def test_webhook_disabled_auto_index(self, api_client, repository: Repository) -> None:
        # auto_index_enabled 默认为 False
        response = api_client.post(
            f"/api/repositories/{repository.id}/webhooks/push/",
            data={"ref": "refs/heads/main", "after": "c" * 40},
            format="json",
        )
        assert response.status_code == 403

    # 必须 patch 真正的异步派发点 DurableTaskService.defer，而不是
    # clone_and_index_repository——后者只在分支重建路径上，不在 trigger_auto_index 的
    # 链路里，patch 它对本用例无效。放任 defer 执行会让进程内 durable 兜底把仓库置为
    # INDEXING，而 trigger_auto_index 的判断顺序是「already_indexing 先于 SHA 去重」，
    # 于是第二次请求可能提前返回 skipped、而非本用例要验证的 duplicate（竞态：单独跑
    # 常侥幸通过，全量跑必现）。
    @patch("durable.DurableTaskService.defer", new_callable=AsyncMock)
    def test_webhook_dedup_same_sha(
        self, mock_defer: AsyncMock, api_client, webhook_repo: Repository
    ) -> None:
        clear_dedup_cache()
        import json
        sha = "d" * 40
        payload = json.dumps({"ref": "refs/heads/main", "after": sha})
        sig = self._make_signature(payload.encode(), "test-secret")

        # 第一次触发
        r1 = api_client.post(
            f"/api/repositories/{webhook_repo.id}/webhooks/push/",
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
        )
        assert r1.status_code == 202

        # 第二次应该被去重
        r2 = api_client.post(
            f"/api/repositories/{webhook_repo.id}/webhooks/push/",
            data=payload,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "duplicate"


# ============================================================================
# 定时轮询
# ============================================================================


class TestPollRepositoryUpdates:
    """定时轮询测试。"""

    @pytest.mark.asyncio
    @patch("tasks.index_trigger_tasks._get_remote_head_sha", new_callable=AsyncMock)
    @patch("tasks.index_trigger_tasks.clone_and_index_repository", new_callable=AsyncMock)
    async def test_poll_triggers_when_sha_changed(
        self, mock_clone: AsyncMock, mock_remote: AsyncMock, repository: Repository
    ) -> None:
        from asgiref.sync import sync_to_async

        from tasks.index_trigger_tasks import poll_repository_updates

        clear_dedup_cache()

        def _setup() -> None:
            repository.auto_index_enabled = True
            repository.last_indexed_commit_sha = "a" * 40
            repository.save()

        await sync_to_async(_setup)()

        mock_remote.return_value = "b" * 40
        mock_clone.return_value = {"status": "success"}

        result = await poll_repository_updates()
        assert result["checked"] == 1
        assert result["triggered"] == 1

    @pytest.mark.asyncio
    @patch("tasks.index_trigger_tasks._get_remote_head_sha", new_callable=AsyncMock)
    async def test_poll_skips_when_sha_same(
        self, mock_remote: AsyncMock, repository: Repository
    ) -> None:
        from asgiref.sync import sync_to_async

        from tasks.index_trigger_tasks import poll_repository_updates

        def _setup() -> None:
            repository.auto_index_enabled = True
            repository.last_indexed_commit_sha = "a" * 40
            repository.save()

        await sync_to_async(_setup)()

        mock_remote.return_value = "a" * 40

        result = await poll_repository_updates()
        assert result["checked"] == 1
        assert result["triggered"] == 0

    @pytest.mark.asyncio
    async def test_poll_skips_disabled_repos(self, repository: Repository) -> None:
        from tasks.index_trigger_tasks import poll_repository_updates

        # auto_index_enabled 默认 False
        result = await poll_repository_updates()
        assert result["checked"] == 0
