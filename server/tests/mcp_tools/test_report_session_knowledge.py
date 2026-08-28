"""MCP ``report_session_knowledge`` 会话 Capture 契约（Phase 142 Wave 0）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from initiatives.models import Project, ProjectMember, ProjectMemory, SessionCapture
from initiatives.services import MemoryService
from interactions.models import ToolCallRecord
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

_URL = "/api/mcp/tools/report_session_knowledge/"
_RESPONSE_KEYS = {
    "accepted",
    "capture_id",
    "reason",
    "repository_id",
    "project_id",
    "idempotent_hit",
    "run_id",
}


async def _post(client: APIClient, payload: dict) -> tuple[int, dict]:
    response = await sync_to_async(client.post)(_URL, payload, format="json")
    body = (
        response.json()
        if response.headers.get("Content-Type", "").startswith("application/json")
        else {}
    )
    return response.status_code, body


@sync_to_async
def _capture(capture_id: str) -> SessionCapture:
    return SessionCapture.objects.get(pk=capture_id)


@sync_to_async
def _capture_count() -> int:
    return SessionCapture.objects.count()


@sync_to_async
def _memory_count() -> int:
    return ProjectMemory.objects.count()


@sync_to_async
def _tool_call() -> ToolCallRecord:
    return ToolCallRecord.objects.filter(tool_name="report_session_knowledge").latest("created_at")


async def _make_project(access_user, repository):
    space = await sync_to_async(Space.objects.create)(
        name="Session Capture Space",
        feishu_project_key="session-capture-space",
    )
    await sync_to_async(space.repositories.add)(repository)
    project = await Project.objects.acreate(
        space=space,
        name="Session Capture Project",
        feishu_project_key="session-capture-project",
        created_by=access_user,
    )
    await ProjectMember.objects.acreate(project=project, user=access_user)
    return project


async def test_member_report_persists_capture(mcp_client, access_user, repository) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, repository)
    status_code, body = await _post(
        client,
        {
            "question": "如何保持会话知识可追溯？",
            "answer": "将可见答案精华写入独立 Capture 账本。",
            "repository_id": str(repository.id),
            "git_url": repository.git_url,
            "branch_name": "feat/session-capture",
            "project_id": str(project.id),
            "session_id": "session-member",
            "response_model": "test-model",
            "provider": "test-provider",
            "input_tokens": 101,
            "output_tokens": 37,
            "client": "cursor-test",
        },
    )

    assert status_code == 200
    assert set(body) == _RESPONSE_KEYS
    assert body["accepted"] is True
    capture = await _capture(body["capture_id"])
    assert capture.repository_id == repository.id
    assert capture.project_id == project.id
    assert capture.initiated_by_user_id == str(access_user.id)


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "answer"},
        {"question": "question"},
        {"question": "", "answer": "answer"},
        {"question": "question", "answer": ""},
        {"question": "   ", "answer": "answer"},
        {"question": "question", "answer": " \t "},
    ],
)
async def test_missing_question_or_answer_400(mcp_client, payload) -> None:
    client, _ = mcp_client
    status_code, body = await _post(client, payload)

    assert status_code == 400
    assert body["error_code"] == "invalid_params"
    assert await _capture_count() == 0


async def test_missing_token_401() -> None:
    status_code, body = await _post(
        APIClient(),
        {"question": "question", "answer": "answer"},
    )

    assert status_code == 401
    assert body["error_code"] == "authentication_failed"
    assert await _capture_count() == 0


async def test_unanchored_still_accepted(mcp_client) -> None:
    client, _ = mcp_client
    status_code, body = await _post(
        client,
        {"question": "无挂钩也收吗？", "answer": "先收 Capture，后续再补标。"},
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert body["reason"] == "unanchored"
    assert body["reason"] != "branch_unresolved"
    assert await _capture(body["capture_id"])


async def test_unresolved_repo_still_accepted(mcp_client) -> None:
    client, _ = mcp_client
    status_code, body = await _post(
        client,
        {
            "question": "仓库 URL 无法解析怎么办？",
            "answer": "挂钩失败不影响 Capture 落账。",
            "git_url": "not-a-git-url",
        },
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert body["reason"] == "repo_unresolved"
    assert await _capture(body["capture_id"])


async def test_default_branch_does_not_mean_rejected(mcp_client) -> None:
    client, _ = mcp_client
    status_code, body = await _post(
        client,
        {
            "question": "只有默认分支时是否拒绝？",
            "answer": "分支不是 Capture 的接受门闩。",
            "branch_name": "main",
        },
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert body["reason"] == "unanchored"
    assert body["reason"] != "branch_unresolved"


async def test_link_reason_passthrough(mcp_client, repository) -> None:
    client, _ = mcp_client
    status_code, body = await _post(
        client,
        {
            "question": "无仓库权限时是否仍收？",
            "answer": "只拒绝挂钩，不拒绝独立 Capture。",
            "repository_id": str(repository.id),
        },
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert body["reason"] == "repo_unauthorized"
    capture = await _capture(body["capture_id"])
    assert capture.link_reason == body["reason"]
    assert capture.repository_id is None


async def test_idempotent_hit_keeps_first_write(mcp_client) -> None:
    client, _ = mcp_client
    first_status, first = await _post(
        client,
        {
            "question": "同一个问题应如何重试？",
            "answer": "首次答案。",
            "session_id": "session-idempotent",
        },
    )
    second_status, second = await _post(
        client,
        {
            "question": "同一个问题应如何重试？",
            "answer": "不应覆盖的第二次答案。",
            "session_id": "session-idempotent",
            "git_url": "invalid-url",
        },
    )

    assert first_status == second_status == 200
    assert first["capture_id"] == second["capture_id"]
    assert first["idempotent_hit"] is False
    assert second["idempotent_hit"] is True
    capture = await _capture(first["capture_id"])
    assert capture.answer == "首次答案。"
    assert capture.link_reason == "unanchored"
    assert await _capture_count() == 1


async def test_session_tool_does_not_write_project_memory(
    mcp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = AsyncMock(side_effect=AssertionError("会话 Capture 不得写 ProjectMemory"))
    monkeypatch.setattr(MemoryService, "append", append)
    client, _ = mcp_client

    status_code, body = await _post(
        client,
        {"question": "应该写项目记忆吗？", "answer": "不，新工具只写 Capture。"},
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert await _memory_count() == 0
    append.assert_not_awaited()


async def test_redaction_on_mcp_path(mcp_client) -> None:
    client, _ = mcp_client
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    status_code, body = await _post(
        client,
        {
            "question": f"如何处理密钥 {secret}？",
            "answer": f"答案也不得保留 {secret}。",
        },
    )

    assert status_code == 200
    capture = await _capture(body["capture_id"])
    assert secret not in capture.question
    assert secret not in capture.answer


async def test_client_metadata_is_accepted_and_audited(mcp_client) -> None:
    client, _ = mcp_client
    client_name = "unknown-client/experimental-2026"
    status_code, body = await _post(
        client,
        {
            "question": "客户端标识是否开放？",
            "answer": "任意非空标识应进入调用审计。",
            "client": client_name,
        },
    )

    assert status_code == 200
    assert body["accepted"] is True
    assert await _capture(body["capture_id"])
    assert "client" not in {field.name for field in SessionCapture._meta.get_fields()}
    tool_call = await _tool_call()
    assert tool_call.input["client"] == client_name


async def test_accepted_enqueues_durable_eval(
    mcp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture 持久化返回后才允许投递 eval，payload 不复制正文。"""
    import mcp_tools.views as views

    order: list[str] = []
    original_persist = views.CaptureService.persist

    async def traced_persist(self, **kwargs):
        result = await original_persist(self, **kwargs)
        assert await SessionCapture.objects.filter(pk=result.capture.id).aexists()
        order.append("persisted")
        return result

    async def traced_enqueue(capture_id: str, *, initiated_by_user_id: str | None = None):
        assert order == ["persisted"]
        assert await SessionCapture.objects.filter(pk=capture_id).aexists()
        order.append("enqueued")
        return "job-eval"

    monkeypatch.setattr(views.CaptureService, "persist", traced_persist)
    monkeypatch.setattr(
        views,
        "enqueue_session_capture_eval",
        traced_enqueue,
        raising=False,
    )
    client, _ = mcp_client

    status_code, body = await _post(
        client,
        {"question": "持久化和投递顺序？", "answer": "必须先持久化，再投递。"},
    )

    assert status_code == 200
    assert set(body) == _RESPONSE_KEYS
    assert body["accepted"] is True
    assert order == ["persisted", "enqueued"]


async def test_enqueue_failure_still_accepted(
    mcp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """队列故障不得追溯性撤销已接受的 Capture。"""
    import mcp_tools.views as views

    enqueue = AsyncMock(side_effect=RuntimeError("queue unavailable"))
    monkeypatch.setattr(
        views,
        "enqueue_session_capture_eval",
        enqueue,
        raising=False,
    )
    client, _ = mcp_client

    status_code, body = await _post(
        client,
        {"question": "队列故障是否拒绝？", "answer": "不，已持久化仍 accepted。"},
    )

    assert status_code == 200
    assert set(body) == _RESPONSE_KEYS
    assert body["accepted"] is True
    assert await SessionCapture.objects.filter(pk=body["capture_id"]).aexists()
    enqueue.assert_awaited_once()


async def test_terminal_capture_does_not_reenqueue(
    mcp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """幂等命中终态不重派；响应仍保持原七键契约。"""
    import mcp_tools.views as views

    enqueue = AsyncMock(return_value="job-eval")
    monkeypatch.setattr(
        views,
        "enqueue_session_capture_eval",
        enqueue,
        raising=False,
    )
    client, _ = mcp_client
    payload = {
        "question": "终态重放是否重派？",
        "answer": "不重派。",
        "session_id": "terminal-replay",
    }

    first_status, first = await _post(client, payload)
    await SessionCapture.objects.filter(pk=first["capture_id"]).aupdate(status="evaluated_low")
    second_status, second = await _post(client, payload)

    assert first_status == second_status == 200
    assert set(first) == set(second) == _RESPONSE_KEYS
    assert second["accepted"] is True
    assert second["idempotent_hit"] is True
    enqueue.assert_awaited_once()


async def test_pending_or_failed_capture_can_reenqueue(
    mcp_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pending/failed 重放可进入稳定 key 去重的恢复入口。"""
    import mcp_tools.views as views

    enqueue = AsyncMock(return_value="job-eval")
    monkeypatch.setattr(
        views,
        "enqueue_session_capture_eval",
        enqueue,
        raising=False,
    )
    client, _ = mcp_client
    payload = {
        "question": "失败态如何恢复？",
        "answer": "按相同 capture id 使用稳定 key 重派。",
        "session_id": "failed-replay",
    }

    _, first = await _post(client, payload)
    await SessionCapture.objects.filter(pk=first["capture_id"]).aupdate(status="eval_failed")
    _, second = await _post(client, payload)

    assert second["capture_id"] == first["capture_id"]
    assert second["accepted"] is True
    assert enqueue.await_count == 2
    assert {call.args[0] for call in enqueue.await_args_list} == {first["capture_id"]}
