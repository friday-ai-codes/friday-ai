"""assemble_affected_processes 验收（EXEC-03 / D-07）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import networkx as nx
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from services.code_graph import CodeGraph, GraphMeta
from services.code_graph.affected_processes import assemble_affected_processes
from services.code_graph_tools import run_detect_changes, run_impact
from services.repo_mirror import DiffMirrorResult, MirrorSnapshot

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

_ORDERS_DIFF = """\
diff --git a/src/orders.py b/src/orders.py
index 1111111..2222222 100644
--- a/src/orders.py
+++ b/src/orders.py
@@ -3,1 +3,1 @@
-    return 1
+    return 2
"""


def _process(**overrides) -> SimpleNamespace:
    base = {
        "name": "GET /api/orders",
        "process_key": "GET:/api/orders",
        "steps": [
            {
                "symbol_id": "sym-a",
                "name": "handle_orders",
                "file_path": "src/orders.py",
                "depth": 0,
            },
            {
                "symbol_id": "sym-b",
                "name": "load_cart",
                "file_path": "src/cart.py",
                "depth": 1,
            },
        ],
        "step_count": 2,
        "community_class": "cross_community",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _meta(**overrides) -> GraphMeta:
    fields = {
        "repository_id": "repo-1",
        "branch": "",
        "node_count": 1,
        "edge_count": 0,
        "estimated_bytes": 128,
        "resolution_rate": 1.0,
        "low_resolution": False,
        "partial_edges": False,
        "partial_reason": "",
        "degraded": "",
        "cross_repo_unresolved_count": 0,
        "cross_repo_branch_unfiltered": False,
        "excluded_file_count": 0,
        "include_low_confidence": False,
        "built_signature": "sig",
        "built_at": timezone.now(),
    }
    fields.update(overrides)
    return GraphMeta(**fields)


def _snap(sha: str, *, repository_id: str, ref: str = "main") -> MirrorSnapshot:
    return MirrorSnapshot(
        repository_id=repository_id,
        repo_dir=Path("/tmp/friday-mirror-test"),
        commit_sha=sha,
        ref=ref,
        matches_index=sha == BASE_SHA,
    )


@pytest.fixture
def user_obj(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(username="ap-orch", password="x")


def test_assemble_affected_processes_single_dialect() -> None:
    """输出键 name/process_key/affected_steps/total_steps/community_class。

    （Req: EXEC-03, 决策: D-07）
    """
    proc = _process()
    out = assemble_affected_processes(
        hit_symbol_ids={"sym-b"},
        hit_file_name_keys=set(),
        processes=[proc],
    )
    assert len(out) == 1
    row = out[0]
    assert set(row) >= {
        "name",
        "process_key",
        "affected_steps",
        "total_steps",
        "community_class",
        "step",
    }
    assert row["name"] == "GET /api/orders"
    assert row["process_key"] == "GET:/api/orders"
    assert row["affected_steps"] == [1]
    assert row["total_steps"] == 2
    assert row["community_class"] == "cross_community"
    assert row["step"] == 1

    out2 = assemble_affected_processes(
        hit_symbol_ids=set(),
        hit_file_name_keys={"src/orders.py:handle_orders"},
        processes=[proc],
    )
    assert out2[0]["affected_steps"] == [0]
    assert out2[0]["step"] == 0


def test_no_intersection_returns_empty_list() -> None:
    """无 Process 行 / 无交集 → []（合法 fail-soft）。

    （Req: EXEC-03, 决策: D-07）
    """
    assert (
        assemble_affected_processes(
            hit_symbol_ids={"missing"},
            hit_file_name_keys=set(),
            processes=[],
        )
        == []
    )
    assert (
        assemble_affected_processes(
            hit_symbol_ids={"missing"},
            hit_file_name_keys={"x.py:y"},
            processes=[_process()],
        )
        == []
    )


@pytest.mark.django_db(transaction=True)
async def test_run_impact_fills_affected_processes(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """run_impact 信封回填 affected_processes（单一方言）。

    （Req: EXEC-03, 决策: D-07）
    """
    from codegraph.models import ProcessTrace

    def _seed():
        return symbols_factory("handle_orders", "src/orders.py", start_line=1, end_line=20)

    seed = await sync_to_async(_seed)()
    seed_id = str(seed.id)

    def _mk_process():
        return ProcessTrace.objects.create(
            repository=indexed_repo,
            branch_name="",
            process_key="GET:/api/orders",
            name="GET /api/orders",
            entry_endpoint={
                "http_method": "GET",
                "url_path": "/api/orders",
                "handler_name": "handle_orders",
                "file_path": "src/orders.py",
                "line_number": 1,
            },
            steps=[
                {
                    "symbol_id": seed_id,
                    "name": "handle_orders",
                    "file_path": "src/orders.py",
                    "depth": 0,
                }
            ],
            step_count=1,
            community_class=ProcessTrace.CommunityClass.CROSS_COMMUNITY,
            built_at_sha=indexed_repo.last_indexed_commit_sha or "",
        )

    await sync_to_async(_mk_process)()

    g = nx.MultiDiGraph()
    g.add_node(
        seed_id,
        name="handle_orders",
        symbol_type="FUNCTION",
        file_path="src/orders.py",
        start_line=1,
        end_line=20,
    )
    fake = CodeGraph(
        graph=g,
        meta=_meta(repository_id=str(indexed_repo.id)),
        chunk_evidence={},
    )

    with (
        mock.patch("services.code_graph_tools._code_graph_access") as access_factory,
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=fake),
        ),
        mock.patch(
            "services.code_graph_cross_repo.collect_cross_repo_impact",
            new=mock.AsyncMock(return_value=[]),
        ),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_impact(
            repository_id=str(indexed_repo.id),
            repo=indexed_repo,
            graph_branch=None,
            user=user_obj,
            symbol_id=seed_id,
        )

    assert result["ok"] is True
    assert result["affected_processes"]
    row = result["affected_processes"][0]
    assert row["process_key"] == "GET:/api/orders"
    assert row["affected_steps"] == [0]
    assert row["total_steps"] == 1


@pytest.mark.django_db(transaction=True)
async def test_run_detect_changes_fills_affected_processes(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """run_detect_changes 信封回填 affected_processes。

    （Req: EXEC-03, 决策: D-07）
    """
    from codegraph.models import ProcessTrace

    def _seed():
        return symbols_factory("handle_orders", "src/orders.py", start_line=1, end_line=20)

    seed = await sync_to_async(_seed)()
    seed_id = str(seed.id)

    def _mk_process():
        return ProcessTrace.objects.create(
            repository=indexed_repo,
            branch_name="",
            process_key="GET:/api/orders",
            name="GET /api/orders",
            entry_endpoint={},
            steps=[
                {
                    "symbol_id": seed_id,
                    "name": "handle_orders",
                    "file_path": "src/orders.py",
                    "depth": 0,
                }
            ],
            step_count=1,
            community_class=ProcessTrace.CommunityClass.INTRA_COMMUNITY,
            built_at_sha=indexed_repo.last_indexed_commit_sha or "",
        )

    await sync_to_async(_mk_process)()
    repo_id = str(indexed_repo.id)

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
            unified_diff=_ORDERS_DIFF,
        )

    async def _impact(**kwargs):
        return {
            "ok": True,
            "seed": {
                "symbol_id": seed_id,
                "name": "handle_orders",
                "file_path": "src/orders.py",
            },
            "groups": {},
            "summary": {"total_found": 0, "returned": 0},
            "graph": {"resolution_rate": 1.0},
            "affected_processes": [],
        }

    with (
        mock.patch("services.code_graph_tools._code_graph_access") as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=_ensure_commit),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=_ensure_sha),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=_diff),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(),
        ),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=repo_id,
            repo=indexed_repo,
            user=user_obj,
            compare="feature/x",
        )

    assert result["ok"] is True
    assert result["affected_processes"]
    assert result["affected_processes"][0]["process_key"] == "GET:/api/orders"
