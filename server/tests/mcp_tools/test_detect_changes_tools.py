"""``detect_changes`` MCP + 对话双面守护用例（覆盖 IMPACT-06 延续 / D-13）。

范式照 ``test_impact_trace_tools.py``：模块级 ``pytestmark`` + URL 常量 +
``mcp_client`` fixture。

⛔ 不得 mock ``run_detect_changes``——双面哨兵必须打真实共享编排（或同源真实路径），
否则 MCP↔对话同源断言失去意义。可 mock ``diff_mirror`` / ``ensure_mirror_commit``。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from rest_framework.test import APIClient

from services.repo_mirror import DiffMirrorResult, MirrorSnapshot

pytestmark = pytest.mark.django_db

DETECT_CHANGES_URL = "/api/mcp/tools/detect_changes/"

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

_MODIFIED_DIFF = """\
diff --git a/src/svc.py b/src/svc.py
index 1111111..2222222 100644
--- a/src/svc.py
+++ b/src/svc.py
@@ -3,1 +3,1 @@
-    return 1
+    return 2
"""


def _assert_surfaces_byte_equal(mcp_data: dict, tool_data: dict) -> None:
    """键集先行（报错可读），再 ``json.dumps(sort_keys=True)`` 逐字节比对。"""
    mcp_keys = set(mcp_data)
    tool_keys = set(tool_data)
    assert mcp_keys == tool_keys, (
        f"双面 data 键集不一致：仅 MCP={sorted(mcp_keys - tool_keys)} "
        f"仅对话={sorted(tool_keys - mcp_keys)}"
    )
    mcp_dump = json.dumps(mcp_data, sort_keys=True, ensure_ascii=False, default=str)
    tool_dump = json.dumps(tool_data, sort_keys=True, ensure_ascii=False, default=str)
    assert mcp_dump == tool_dump


@pytest.fixture(autouse=True)
def _reset_code_graph_state():
    """用例间清进程级缓存，防止上一个用例的状态污染下一个。

    ⚠️ 必须在本文件再写一份：pytest conftest 作用域是「所在目录及其子目录」，
    ``tests/services/code_graph/conftest.py`` 的同名钩子对 ``tests/mcp_tools/`` **不可见**。
    """
    from services.exclusion import invalidate_matcher_cache

    def _reset() -> None:
        invalidate_matcher_cache()
        try:
            access = importlib.import_module("services.code_graph.access")
        except ImportError:
            pass
        else:
            access.invalidate_matcher_fingerprint_cache()

        try:
            cache = importlib.import_module("services.code_graph.cache")
        except ImportError:
            return
        cache._reset_for_tests()

    _reset()
    yield
    _reset()


def _snap(sha: str, *, repository_id: str, ref: str = "main") -> MirrorSnapshot:
    return MirrorSnapshot(
        repository_id=repository_id,
        repo_dir=Path("/tmp/friday-mirror-test"),
        commit_sha=sha,
        ref=ref,
        matches_index=sha == BASE_SHA,
    )


def _seed_symbol(repository) -> Any:
    from codegraph.models import Symbol

    return Symbol.objects.create(
        repository=repository,
        branch_name="",
        name="svc",
        symbol_type="FUNCTION",
        file_path="src/svc.py",
        start_line=1,
        end_line=20,
    )


def _patch_mirror_for_mcp(repository_id: str):
    async def _ensure_commit(repo_id: str, branch: str | None = None):
        if branch is None:
            return _snap(BASE_SHA, repository_id=repo_id, ref="main")
        return _snap(HEAD_SHA, repository_id=repo_id, ref=branch)

    async def _ensure_sha(repo_id: str, sha: str, **_kwargs):
        return _snap(sha, repository_id=repo_id, ref=sha[:12])

    async def _diff(base, head, **_kwargs):
        return DiffMirrorResult(
            base_sha=base.commit_sha,
            head_sha=head.commit_sha,
            unified_diff=_MODIFIED_DIFF,
        )

    return (
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=_ensure_commit),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=_ensure_sha),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=_diff),
    )


def test_mcp_detect_changes_requires_pat(indexed_repository) -> None:
    """无 PAT → 401 ``authentication_failed``（fail-closed）。"""
    client = APIClient()
    response = client.post(
        DETECT_CHANGES_URL,
        {"repository_id": str(indexed_repository.id), "compare": "feature/x"},
        format="json",
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_failed"


def test_mcp_detect_changes_success_envelope(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    """MCP 成功信封含 ok / staleness / affected 字段形状；打真实编排（mock mirror）。"""
    client, _plaintext = mcp_client
    _seed_symbol(indexed_repository)
    repo_id = str(indexed_repository.id)

    async def _impact(**kwargs):
        return {
            "ok": True,
            "tool": "impact_analysis",
            "graph": {"resolution_rate": 0.17, "degraded": ""},
        }

    ensure_c, ensure_s, diff_m = _patch_mirror_for_mcp(repo_id)
    with (
        mock.patch("services.code_graph_tools._code_graph_access") as access_factory,
        ensure_c,
        ensure_s,
        diff_m,
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        response = client.post(
            DETECT_CHANGES_URL,
            {
                "repository_id": repo_id,
                "compare": "feature/x",
                "base_ref": "origin/develop",
            },
            format="json",
        )

    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True
    assert body.get("tool") == "detect_changes"
    assert body.get("repository_id") == repo_id
    assert body.get("diff_base_sha") == BASE_SHA
    assert body.get("diff_head_sha") == HEAD_SHA
    assert body.get("base_ref") == "origin/develop"
    assert isinstance(body.get("files"), list)
    assert isinstance(body.get("impacts"), list)
    assert isinstance(body.get("summary"), dict)
    assert body.get("affected_processes") == []
    assert isinstance(body.get("staleness"), dict)
    assert isinstance(body.get("graph"), dict)
    assert "resolution_rate" in body["graph"]
    assert body.get("run_id")


def test_conversational_detect_changes_registered() -> None:
    """对话侧注册断言的薄包装——权威用例在 agents 侧，避免双份维护。

    见 ``tests/agents/tools/test_graph_tools.py::test_detect_changes_registered_in_indexed_tools``。
    """
    from tests.agents.tools.test_graph_tools import (
        test_detect_changes_registered_in_indexed_tools as _agents_registered,
    )

    _agents_registered()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_two_surfaces_same_payload_detect_changes(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    access_user,
    project,
) -> None:
    """**双面同源**：同一输入下 MCP 与对话壳 ``data`` 逐字节相同（D-13 / IMPACT-06）。

    成功态 + ``repository_not_indexed`` 硬错误态各一轮。``run_id`` 是 MCP 面唯一
    允许且写死的差异。⛔ 不许 mock ``run_detect_changes``——否则哨兵退化为自证。

    （Req: DIFF-01/DIFF-02, 决策: D-13）
    """
    from asgiref.sync import sync_to_async

    from agents.tools.graph_tools import detect_changes
    from chat.models import Conversation

    client, _plaintext = mcp_client
    conversation = await Conversation.objects.acreate(
        space=project,
        title="dual-surface-detect-changes",
        created_by=access_user,
    )
    await sync_to_async(_seed_symbol)(indexed_repository)
    repo_id = str(indexed_repository.id)

    payload = {
        "repository_id": repo_id,
        "compare": "feature/x",
        "base_ref": "origin/develop",
        "max_depth": 3,
        "min_confidence": 1.0,
        "limit": 200,
    }

    # —— 第一轮：成功态（mock 仅 mirror 下层；编排层真实跑）——
    ensure_c, ensure_s, diff_m = _patch_mirror_for_mcp(repo_id)
    with ensure_c, ensure_s, diff_m:
        response = await sync_to_async(client.post)(
            DETECT_CHANGES_URL, payload, format="json"
        )
        assert response.status_code == 200
        mcp_body = response.json()
        mcp_data = {k: v for k, v in mcp_body.items() if k != "run_id"}

        tool_result = await detect_changes(
            **payload,
            conversation_id=str(conversation.id),
        )

    assert tool_result.success is True
    tool_data = tool_result.output["data"]
    assert mcp_body.get("ok") is True
    assert tool_data.get("ok") is True
    assert "run_id" in mcp_body
    assert "run_id" not in tool_data
    _assert_surfaces_byte_equal(mcp_data, tool_data)

    # —— 第二轮：硬错误 repository_not_indexed（索引水位清空，壳层仍放行 INDEXED）——
    def _clear_index_sha() -> None:
        indexed_repository.last_indexed_commit_sha = ""
        indexed_repository.save(update_fields=["last_indexed_commit_sha"])

    await sync_to_async(_clear_index_sha)()
    hard_payload = {
        "repository_id": repo_id,
        "compare": "feature/x",
        "max_depth": 3,
        "min_confidence": 1.0,
        "limit": 200,
    }

    hard_response = await sync_to_async(client.post)(
        DETECT_CHANGES_URL, hard_payload, format="json"
    )
    assert hard_response.status_code == 200
    hard_mcp_body = hard_response.json()
    assert hard_mcp_body["ok"] is False
    assert hard_mcp_body["error_code"] == "repository_not_indexed"
    hard_mcp_data = {k: v for k, v in hard_mcp_body.items() if k != "run_id"}

    hard_tool = await detect_changes(
        **hard_payload,
        conversation_id=str(conversation.id),
    )
    assert hard_tool.success is True
    hard_tool_data = hard_tool.output["data"]
    assert hard_tool_data["error_code"] == "repository_not_indexed"

    assert "run_id" in hard_mcp_body
    assert "run_id" not in hard_tool_data
    _assert_surfaces_byte_equal(hard_mcp_data, hard_tool_data)


def test_tool_trace_payload_detect_changes_counts_only() -> None:
    """RetrievalTrace 只记计数，无路径/符号名（T-123-TRACE）。

    本用例无 DB：构造假编排信封 → ``tool_trace_payload`` → 序列化文本断言。
    """
    import json

    from services.code_graph_tools import tool_trace_payload

    fake = {
        "ok": True,
        "tool": "detect_changes",
        "repository_id": "repo-uuid-1",
        "diff_base_sha": "a" * 40,
        "diff_head_sha": "b" * 40,
        "files": [
            {
                "path": "src/secret_leak.py",
                "change_type": "modified",
                "symbols": [
                    {
                        "uid": "sym-1",
                        "name": "leaky_helper",
                        "file_path": "src/secret_leak.py",
                        "changeType": "modified",
                        "impact_seed": True,
                    }
                ],
            }
        ],
        "impacts": [
            {"symbol_id": "sym-1", "impact": {"ok": True}},
            {
                "symbol_id": "sym-2",
                "impact_error": "graph_unavailable",
                "unavailable_reason": "x",
            },
        ],
        "summary": {
            "affected_symbol_count": 1,
            "impact_seed_count": 1,
            "truncated": False,
            "not_expanded": False,
            "file_count": 1,
        },
        "graph": {"resolution_rate": 0.17, "degraded": ""},
    }
    payload = tool_trace_payload(
        fake, tool="detect_changes", duration_ms=12, orchestration_ms=8
    )
    assert isinstance(payload, dict)
    assert payload["result_count"] == 1
    assert payload["total_found"] == 1
    assert payload["files_touched"] == 1
    assert payload["impacts_ok"] == 1
    assert payload["impacts_failed"] == 1
    assert payload["truncated"] == 0
    assert payload["risk_level"] == ""
    assert payload["cross_repo_entry_count"] == 0

    dumped = json.dumps(payload, ensure_ascii=False)
    assert "file_path" not in dumped
    assert "secret_leak" not in dumped
    assert "leaky_helper" not in dumped
    assert "src/" not in dumped
