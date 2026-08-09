"""run_list_processes / run_get_process + 薄壳 call-through 验收（EXEC-02 / D-06）。"""

from __future__ import annotations

from unittest import mock
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate


@pytest.fixture
def user_obj(db):
    User = get_user_model()
    return User.objects.create_user(username="pq-orch", password="x")


@pytest.mark.django_db(transaction=True)
async def test_run_list_processes_and_get_process(indexed_repo, user_obj) -> None:
    """共享编排：list 过滤/排序 + get by process_key；信封含 ok/staleness。

    默认 cross_community 优先排序。

    （Req: EXEC-02, 决策: D-06）
    """
    from codegraph.models import ProcessTrace
    from services.code_graph_tools import run_get_process, run_list_processes

    def _seed():
        ProcessTrace.objects.create(
            repository=indexed_repo,
            branch_name="",
            process_key="GET:/intra",
            name="GET /intra",
            entry_endpoint={},
            steps=[{"symbol_id": "s1", "name": "a", "file_path": "a.py", "depth": 0}],
            step_count=1,
            community_class=ProcessTrace.CommunityClass.INTRA_COMMUNITY,
            built_at_sha=indexed_repo.last_indexed_commit_sha or "",
        )
        ProcessTrace.objects.create(
            repository=indexed_repo,
            branch_name="",
            process_key="POST:/cross",
            name="POST /cross",
            entry_endpoint={},
            steps=[
                {"symbol_id": "s2", "name": "b", "file_path": "b.py", "depth": 0},
                {"symbol_id": "s3", "name": "c", "file_path": "c.py", "depth": 1},
            ],
            step_count=2,
            community_class=ProcessTrace.CommunityClass.CROSS_COMMUNITY,
            built_at_sha=indexed_repo.last_indexed_commit_sha or "",
        )

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)

    with mock.patch("services.code_graph_tools._code_graph_access") as access_factory:
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        listed = await run_list_processes(
            repository_id=repo_id,
            repo=indexed_repo,
            graph_branch=None,
            user=user_obj,
        )

    assert listed["ok"] is True
    assert listed["tool"] == "list_processes"
    assert "staleness" in listed
    keys = [p["process_key"] for p in listed["processes"]]
    assert keys[0] == "POST:/cross"
    assert "GET:/intra" in keys
    assert listed["summary"]["returned"] == 2

    with mock.patch("services.code_graph_tools._code_graph_access") as access_factory:
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        got = await run_get_process(
            repository_id=repo_id,
            repo=indexed_repo,
            graph_branch=None,
            user=user_obj,
            process_key="POST:/cross",
        )

    assert got["ok"] is True
    assert got["tool"] == "get_process"
    assert got["process"]["process_key"] == "POST:/cross"
    assert isinstance(got["process"].get("steps"), list)
    assert len(got["process"]["steps"]) == 2
    assert "staleness" in got


@pytest.mark.django_db(transaction=True)
async def test_mcp_list_get_process_call_through(indexed_repo) -> None:
    """薄壳 View 只调 run_list_processes / run_get_process，无算法分叉。

    （Req: EXEC-02, 决策: D-06）
    """
    from mcp_tools.views import GetProcessView, ListProcessesView

    User = get_user_model()
    user = await sync_to_async(User.objects.create_user)(
        username="pq-mcp-user", password="x"
    )
    factory = APIRequestFactory()
    repo_id = str(indexed_repo.id)

    list_mock = AsyncMock(
        return_value={
            "ok": True,
            "tool": "list_processes",
            "repository_id": repo_id,
            "processes": [],
            "summary": {"returned": 0, "total": 0, "truncated": False},
            "staleness": {},
            "degradation": {},
        }
    )
    get_mock = AsyncMock(
        return_value={
            "ok": True,
            "tool": "get_process",
            "repository_id": repo_id,
            "process": {"process_key": "GET:/x", "steps": []},
            "staleness": {},
            "degradation": {},
        }
    )
    run = mock.Mock(run_id="run-pq")

    with (
        mock.patch("services.code_graph_tools.run_list_processes", list_mock),
        mock.patch("services.code_graph_tools.run_get_process", get_mock),
        mock.patch.object(
            ListProcessesView, "_begin", new=AsyncMock(return_value=(run, None))
        ),
        mock.patch.object(
            ListProcessesView,
            "_get_indexed_repo",
            new=AsyncMock(return_value=(indexed_repo, None)),
        ),
        mock.patch.object(ListProcessesView, "_record", new=AsyncMock()),
        mock.patch.object(
            GetProcessView, "_begin", new=AsyncMock(return_value=(run, None))
        ),
        mock.patch.object(
            GetProcessView,
            "_get_indexed_repo",
            new=AsyncMock(return_value=(indexed_repo, None)),
        ),
        mock.patch.object(GetProcessView, "_record", new=AsyncMock()),
    ):
        req = factory.post(
            "/api/mcp/tools/list_processes/",
            {"repository_id": repo_id},
            format="json",
        )
        force_authenticate(req, user=user)
        resp = ListProcessesView.as_view()(req)
        if hasattr(resp, "__await__"):
            resp = await resp
        assert getattr(resp, "status_code", 200) == 200
        assert list_mock.await_count == 1

        req2 = factory.post(
            "/api/mcp/tools/get_process/",
            {"repository_id": repo_id, "process_key": "GET:/x"},
            format="json",
        )
        force_authenticate(req2, user=user)
        resp2 = GetProcessView.as_view()(req2)
        if hasattr(resp2, "__await__"):
            resp2 = await resp2
        assert getattr(resp2, "status_code", 200) == 200
        assert get_mock.await_count == 1


@pytest.mark.asyncio
async def test_agents_list_get_process_call_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@tool 同名只调同一 run_*。

    （Req: EXEC-02, 决策: D-06）
    """
    import agents.tools.graph_tools as graph_tools

    user = mock.Mock(id=9)
    monkeypatch.setattr(
        graph_tools, "_resolve_conversation_user", AsyncMock(return_value=user)
    )
    monkeypatch.setattr(
        graph_tools,
        "_resolve_tool_repo",
        AsyncMock(return_value=(mock.Mock(id="repo"), None)),
    )
    monkeypatch.setattr(graph_tools, "_record_chat_retrieval", AsyncMock())

    list_mock = AsyncMock(
        return_value={
            "ok": True,
            "tool": "list_processes",
            "processes": [],
            "summary": {"returned": 0},
        }
    )
    get_mock = AsyncMock(
        return_value={
            "ok": True,
            "tool": "get_process",
            "process": {"process_key": "k", "steps": []},
        }
    )
    monkeypatch.setattr("services.code_graph_tools.run_list_processes", list_mock)
    monkeypatch.setattr("services.code_graph_tools.run_get_process", get_mock)
    monkeypatch.setattr(
        "services.code_graph_tools.resolve_tool_graph_branch",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "services.code_graph_tools.tool_trace_payload",
        lambda *a, **k: {"tool": k.get("tool", "")},
    )

    list_result = await graph_tools.list_processes(
        repository_id="00000000-0000-4000-8000-000000000001",
        conversation_id="00000000-0000-4000-8000-000000000002",
    )
    assert list_result.success is True
    assert list_mock.await_count == 1
    assert get_mock.await_count == 0

    get_result = await graph_tools.get_process(
        repository_id="00000000-0000-4000-8000-000000000001",
        process_key="GET:/x",
        conversation_id="00000000-0000-4000-8000-000000000002",
    )
    assert get_result.success is True
    assert get_mock.await_count == 1
