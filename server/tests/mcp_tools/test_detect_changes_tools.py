"""``detect_changes`` MCP + 对话双面守护用例（覆盖 IMPACT-06 延续 / D-13）。

范式照 ``test_impact_trace_tools.py``：模块级 ``pytestmark`` + URL 常量 +
``mcp_client`` fixture。

⛔ 不得 mock ``run_detect_changes``——双面哨兵必须打真实共享编排（或同源真实路径），
否则 MCP↔对话同源断言失去意义。可 mock ``diff_mirror`` / ``ensure_mirror_commit``。

对话壳由 123-04、双面同源由 123-05 填实。
"""

from __future__ import annotations

import importlib
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


@pytest.mark.skip(reason="Wave 0 桩：由 123-04 落地")
def test_conversational_detect_changes_registered() -> None:
    """对话侧 detect_changes @tool 已注册且 schema 对齐。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 123-05 落地")
def test_two_surfaces_same_payload_detect_changes() -> None:
    """MCP↔对话 data 逐字节同源（去 run_id）；含成功 + 硬错误态。"""
    pytest.fail("Wave 0 桩")


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
