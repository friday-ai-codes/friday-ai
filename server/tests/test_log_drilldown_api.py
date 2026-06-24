"""调用下钻 API 测试（LOG-04）。

覆盖：
- MCP 调用下钻：按 request_id 见触发用户（token_fingerprint=user:<id>）+ run 明细
  （工具/召回，已脱敏直出，无明文）；
- PAT 路径：token_fingerprint=AccessToken.token_hash 反查所有者用户（绝不回 token）；
- AI 对话下钻：按 conversation_id 取全部消息 + created_by 归因（关联键不复制正文）；
- IsSuperUser 403 / 200。
"""

from __future__ import annotations

import pytest

CALL_URL = "/api/system/calls/drilldown/"


@pytest.fixture
def mcp_run(db, user):
    """造一个 MCP InteractionRun（token_fingerprint=user:<id>）+ 工具/召回明细。"""
    from interactions.models import InteractionRun, RetrievalTrace, ToolCallRecord

    run = InteractionRun.objects.create(
        source="mcp",
        request_id="r1",
        token_fingerprint=f"user:{user.id}",
    )
    ToolCallRecord.objects.create(
        run=run,
        tool_name="search_code",
        status="ok",
        input={"q": "needle"},
        output={"hits": ["chunk-a"]},
        duration_ms=12,
    )
    RetrievalTrace.objects.create(
        run=run,
        seq=0,
        kind="chunk",
        payload={"text": "redacted-evidence"},
    )
    return run, user


@pytest.mark.django_db
class TestCallDrilldown:
    def test_requires_param(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        assert api_client.get(CALL_URL).status_code == 400

    def test_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(CALL_URL, {"request_id": "r1"}).status_code == 403

    def test_mcp_drilldown_by_request_id(self, api_client, admin_user, mcp_run):
        run, owner = mcp_run
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(CALL_URL, {"request_id": "r1"})
        assert resp.status_code == 200
        data = resp.json()

        # 触发用户可见（user:<id> 解析）。
        assert data["user"]["id"] == str(owner.id)
        assert data["user"]["username"] == owner.username
        # run 明细：工具调用 + 召回。
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool_name"] == "search_code"
        assert len(data["retrieval"]) == 1
        assert data["retrieval"][0]["kind"] == "chunk"
        # token_fingerprint 是 user:<id>（非明文 token）。
        assert data["run"]["token_fingerprint"] == f"user:{owner.id}"

    def test_drilldown_by_run_id(self, api_client, admin_user, mcp_run):
        run, _owner = mcp_run
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(CALL_URL, {"run_id": str(run.run_id)})
        assert resp.status_code == 200
        assert resp.json()["run"]["run_id"] == str(run.run_id)

    def test_not_found(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        assert api_client.get(CALL_URL, {"request_id": "nope"}).status_code == 404

    def test_pat_fingerprint_resolves_owner_no_token(self, api_client, admin_user, user):
        """PAT 路径：token_fingerprint=token_hash 反查所有者，绝不回明文 token。"""
        from access_tokens.models import AccessToken
        from interactions.models import InteractionRun

        token_hash = "a" * 64
        AccessToken.objects.create(
            name="t1",
            token_hash=token_hash,
            token_prefix="friday_pat_",
            created_by=user,
        )
        InteractionRun.objects.create(
            source="mcp",
            request_id="r-pat",
            token_fingerprint=token_hash,
        )

        api_client.force_authenticate(user=admin_user)
        data = api_client.get(CALL_URL, {"request_id": "r-pat"}).json()
        assert data["user"]["id"] == str(user.id)
        # 回显的 fingerprint 仅为 hash，绝不含明文 token 前缀。
        assert "friday_pat_" not in str(data)


@pytest.mark.django_db
class TestConversationDrilldown:
    def _conv_url(self, conv_id) -> str:
        return f"/api/system/conversations/{conv_id}/drilldown/"

    def test_non_superuser_forbidden(self, api_client, user):
        from chat.models import Conversation

        conv = Conversation.objects.create(title="t", created_by=user)
        api_client.force_authenticate(user=user)
        assert api_client.get(self._conv_url(conv.id)).status_code == 403

    def test_conversation_drilldown_returns_messages_and_owner(
        self, api_client, admin_user, user
    ):
        from chat.models import Conversation, Message

        conv = Conversation.objects.create(title="排障会话", created_by=user)
        Message.objects.create(conversation=conv, role="user", content="问题1")
        Message.objects.create(conversation=conv, role="assistant", content="回答1")

        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(self._conv_url(conv.id))
        assert resp.status_code == 200
        data = resp.json()

        assert data["conversation"]["id"] == str(conv.id)
        assert data["created_by"]["id"] == str(user.id)
        assert len(data["messages"]) == 2
        # 正序（created_at）。
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"

    def test_related_logs_keys_only_no_body_copy(
        self, api_client, admin_user, user
    ):
        """关联键下钻：按 correlation.conversation_id 取 SystemLogEntry 摘要，不复制正文。"""
        from django.utils import timezone

        from chat.models import Conversation
        from system.models import SystemLogEntry

        conv = Conversation.objects.create(title="t", created_by=user)
        SystemLogEntry.objects.create(
            ts=timezone.now(),
            level="info",
            component="chat",
            event="chat_turn_completed",
            message="正文不应被复制到下钻",
            correlation={"conversation_id": str(conv.id), "run_id": "run-xyz"},
        )

        api_client.force_authenticate(user=admin_user)
        data = api_client.get(self._conv_url(conv.id)).json()
        assert len(data["related_logs"]) == 1
        link = data["related_logs"][0]
        assert link["event"] == "chat_turn_completed"
        assert link["correlation"]["conversation_id"] == str(conv.id)
        # 只回关联键 + 摘要，不复制日志正文（message）。
        assert "message" not in link

    def test_not_found(self, api_client, admin_user):
        import uuid

        api_client.force_authenticate(user=admin_user)
        assert api_client.get(self._conv_url(uuid.uuid4())).status_code == 404
