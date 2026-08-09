"""``run_detect_changes`` 编排壳用例（覆盖 D-01..D-04 / D-09..D-12 / D-14）。

与 ``test_detect_changes.py`` 的分工：内核是纯函数、零 DB；本文件测的是**编排壳**——
base pin、hard reject、batch ``run_impact``、staleness。需要库或 mock，故单独成文件。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from services.code_graph import CodeGraph, GraphAccessDenied, GraphError, GraphMeta
from services.code_graph_tools import run_detect_changes
from services.repo_mirror import DiffMirrorResult, MirrorError, MirrorSnapshot

pytestmark = pytest.mark.django_db

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

# 新行故意带尾随空白；用显式空格拼出，避免源码 W291。
_FORMATTING_DIFF = (
    "diff --git a/src/fmt.py b/src/fmt.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/src/fmt.py\n"
    "+++ b/src/fmt.py\n"
    "@@ -2,1 +2,1 @@\n"
    "-def fmt():\n"
    "+def fmt():" + "  " + "\n"
)


def _snap(
    sha: str,
    *,
    repository_id: str,
    ref: str = "main",
) -> MirrorSnapshot:
    return MirrorSnapshot(
        repository_id=repository_id,
        repo_dir=Path("/tmp/friday-mirror-test"),
        commit_sha=sha,
        ref=ref,
        matches_index=sha == BASE_SHA,
    )


def _meta(**overrides) -> GraphMeta:
    fields = {
        "repository_id": "repo-1",
        "branch": "",
        "node_count": 12,
        "edge_count": 20,
        "estimated_bytes": 1024,
        "resolution_rate": 0.17,
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


def _fake_graph() -> CodeGraph:
    import networkx as nx

    return CodeGraph(meta=_meta(), graph=nx.MultiDiGraph(), chunk_evidence={})


@pytest.fixture
def user_obj(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(username="dc-orch", password="x")


def _patch_mirror_pipeline(
    *,
    repository_id: str,
    unified_diff: str = _MODIFIED_DIFF,
    base_sha: str = BASE_SHA,
    head_sha: str = HEAD_SHA,
    raise_on_diff: Exception | None = None,
):
    """Return context-manager patches for mirror helpers + call capture."""
    ensure_calls: list[dict[str, Any]] = []
    diff_calls: list[tuple[Any, Any]] = []

    async def _ensure_commit(repo_id: str, branch: str | None = None):
        ensure_calls.append({"repository_id": repo_id, "branch": branch})
        if branch is None:
            return _snap(base_sha, repository_id=repo_id, ref="main")
        return _snap(head_sha, repository_id=repo_id, ref=branch)

    async def _ensure_sha(repo_id: str, sha: str, **_kwargs):
        ensure_calls.append({"repository_id": repo_id, "sha": sha})
        return _snap(sha, repository_id=repo_id, ref=sha[:12])

    async def _diff(base, head, **_kwargs):
        diff_calls.append((base, head))
        if raise_on_diff is not None:
            raise raise_on_diff
        return DiffMirrorResult(
            base_sha=base.commit_sha,
            head_sha=head.commit_sha,
            unified_diff=unified_diff,
        )

    return ensure_calls, diff_calls, _ensure_commit, _ensure_sha, _diff


@pytest.mark.django_db(transaction=True)
async def test_diff_base_pinned_to_last_indexed(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """mock mirror：diff argv 左端 == last_indexed_commit_sha（D-01）。"""
    assert inspect.iscoroutinefunction(run_detect_changes)

    def _seed():
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)
    ensure_calls, diff_calls, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(
        repository_id=repo_id
    )

    async def _impact(**kwargs):
        return {"ok": True, "tool": "impact_analysis", "graph": {"resolution_rate": 0.17}}

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    # base pin: ensure_mirror_sha(indexed)，禁止 ensure_mirror_commit 分支 tip 回退
    assert ensure_calls[0].get("sha") == indexed_repo.last_indexed_commit_sha
    assert "branch" not in ensure_calls[0]
    assert diff_calls[0][0].commit_sha == indexed_repo.last_indexed_commit_sha
    assert result["diff_base_sha"] == indexed_repo.last_indexed_commit_sha


@pytest.mark.django_db(transaction=True)
async def test_base_ref_declarative_only(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """传 base_ref 不改变 argv 左端（D-02 / DIFF-02 / T-123-BASE）。"""

    def _seed():
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)
    ensure_calls, diff_calls, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(
        repository_id=repo_id
    )

    async def _impact(**kwargs):
        return {"ok": True, "graph": {"resolution_rate": 0.17}}

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
        ),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=repo_id,
            repo=indexed_repo,
            user=user_obj,
            compare="feature/x",
            base_ref="origin/develop",
        )

    assert result["ok"] is True
    assert result["base_ref"] == "origin/develop"
    assert diff_calls[0][0].commit_sha == indexed_repo.last_indexed_commit_sha
    assert ensure_calls[0].get("sha") == indexed_repo.last_indexed_commit_sha
    assert "branch" not in ensure_calls[0]


@pytest.mark.django_db(transaction=True)
async def test_hard_reject_unindexed(indexed_repo, user_obj) -> None:
    """空索引 → ok=False repository_not_indexed，非空清单（D-03）。"""

    def _clear():
        indexed_repo.last_indexed_commit_sha = ""
        indexed_repo.save(update_fields=["last_indexed_commit_sha"])

    await sync_to_async(_clear)()
    await sync_to_async(indexed_repo.refresh_from_db)()

    with mock.patch(
        "services.code_graph_tools._code_graph_access"
    ) as access_factory:
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=str(indexed_repo.id),
            repo=indexed_repo,
            user=user_obj,
            compare="feature/x",
        )

    assert result["ok"] is False
    assert result["error_code"] == "repository_not_indexed"
    assert "files" not in result or result.get("files") in (None, [])
    assert result.get("impacts") in (None, [], ())


@pytest.mark.django_db(transaction=True)
async def test_hard_reject_mirror_error(indexed_repo, user_obj) -> None:
    """MirrorError → ok=False + error_code，非空清单（D-03）。"""
    repo_id = str(indexed_repo.id)
    ensure_calls, diff_calls, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(
        repository_id=repo_id,
        raise_on_diff=MirrorError("mirror_fetch_failed", "fetch boom"),
    )

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=repo_id,
            repo=indexed_repo,
            user=user_obj,
            compare="feature/x",
        )

    assert result["ok"] is False
    assert result["error_code"] == "mirror_fetch_failed"
    assert result.get("impacts") in (None, [], ())


@pytest.mark.django_db(transaction=True)
async def test_hard_reject_acl(indexed_repo, user_obj) -> None:
    """GraphAccessDenied → 上抛，无空成功 affected（D-03 / T-123-ACL）。"""

    async def _deny(*_a, **_k):
        raise GraphAccessDenied("denied")

    with mock.patch(
        "services.code_graph_tools._code_graph_access"
    ) as access_factory:
        access_factory.return_value.ensure_repository_readable = _deny
        with pytest.raises(GraphAccessDenied):
            await run_detect_changes(
                repository_id=str(indexed_repo.id),
                repo=indexed_repo,
                user=user_obj,
                compare="feature/x",
            )


@pytest.mark.django_db(transaction=True)
async def test_batch_impact_calls_run_impact_with_symbol_id(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """spy：默认 max_depth=3 / min_confidence=1.0 / graph_branch=None（D-09/D-10）。"""

    def _seed():
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    sym = await sync_to_async(_seed)()
    sid = str(sym.id)
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(repository_id=repo_id)
    impact_calls: list[dict[str, Any]] = []

    async def _impact(**kwargs):
        impact_calls.append(kwargs)
        return {
            "ok": True,
            "tool": "impact_analysis",
            "graph": {"resolution_rate": 0.17},
        }

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    assert len(impact_calls) >= 1
    call = impact_calls[0]
    assert call["symbol_id"] == sid
    assert call["graph_branch"] is None
    assert call["max_depth"] == 3
    assert call["min_confidence"] == 1.0
    assert call["include_low_confidence"] is False
    assert call["limit"] == 200
    assert "staleness" in result and result["staleness"].get("as_of")
    assert isinstance(result["graph"].get("resolution_rate"), float)
    assert result["affected_processes"] == []


@pytest.mark.django_db(transaction=True)
async def test_formatting_only_skipped_from_impact_seeds(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """formatting_only 不进 batch impact 种子（D-07）。"""

    def _seed():
        return symbols_factory("fmt", "src/fmt.py", start_line=1, end_line=10)

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(
        repository_id=repo_id, unified_diff=_FORMATTING_DIFF
    )
    impact_mock = mock.AsyncMock(
        return_value={"ok": True, "graph": {"resolution_rate": 0.17}}
    )

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", impact_mock),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    assert impact_mock.await_count == 0
    assert result["summary"].get("impact_seed_count", 0) == 0


@pytest.mark.django_db(transaction=True)
async def test_threshold_skips_batch_impact(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """>100 → 零次 run_impact + not_expanded（D-08 / T-123-DOS）。"""
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(repository_id=repo_id)

    # Fabricate >100 impact seeds without creating 101 ORM rows.
    fake_files = [
        {
            "path": "src/svc.py",
            "change_type": "modified",
            "old_path": "src/svc.py",
            "new_path": "src/svc.py",
            "symbols": [
                {
                    "uid": f"uid-{i}",
                    "name": f"fn{i}",
                    "symbol_type": "function",
                    "file_path": "src/svc.py",
                    "start_line": i,
                    "end_line": i,
                    "changeType": "modified",
                    "lines_changed": 1,
                    "impact_seed": True,
                }
                for i in range(101)
            ],
            "file_summary": {"changeType": "modified"},
        }
    ]
    fake_overlap = {
        "files": fake_files,
        "summary": {
            "affected_symbol_count": 101,
            "truncated": True,
            "not_expanded": True,
            "file_count": 1,
        },
    }
    impact_mock = mock.AsyncMock()

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch(
            "services.code_graph.detect_changes.detect_affected_symbols",
            return_value=fake_overlap,
        ),
        mock.patch("services.code_graph_tools.run_impact", impact_mock),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    assert impact_mock.await_count == 0
    assert result["impacts"] == []
    assert result["summary"]["truncated"] is True
    assert result["summary"]["not_expanded"] is True
    assert isinstance(result["graph"].get("resolution_rate"), (int, float))


@pytest.mark.django_db(transaction=True)
async def test_impact_fail_soft_per_symbol(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """单符号 GraphError → impact_error，整体 ok=True（D-12）。"""

    def _seed():
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(repository_id=repo_id)

    async def _boom(**_kwargs):
        raise GraphError("graph boom")

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_boom),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    assert len(result["impacts"]) >= 1
    row = result["impacts"][0]
    assert "impact_error" in row
    assert "unavailable_reason" in row


@pytest.mark.django_db(transaction=True)
async def test_staleness_behind_still_ok(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """behind 大仍 ok=True + as_of（D-04/D-14）。"""

    def _seed_and_stale():
        indexed_repo.behind_commits = 42
        indexed_repo.behind_commits_calculated_at = timezone.now()
        indexed_repo.save(
            update_fields=["behind_commits", "behind_commits_calculated_at"]
        )
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    await sync_to_async(_seed_and_stale)()
    await sync_to_async(indexed_repo.refresh_from_db)()
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(repository_id=repo_id)

    async def _impact(**kwargs):
        return {"ok": True, "graph": {"resolution_rate": 0.17}}

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
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
    assert result["staleness"]["as_of"] == indexed_repo.last_indexed_commit_sha
    assert result["staleness"]["behind_commits"] == 42


@pytest.mark.django_db(transaction=True)
async def test_affected_processes_placeholder_empty(
    indexed_repo, symbols_factory, user_obj
) -> None:
    """affected_processes == []（D-12；Phase 126 回填）。"""

    def _seed():
        return symbols_factory("svc", "src/svc.py", start_line=1, end_line=20)

    await sync_to_async(_seed)()
    repo_id = str(indexed_repo.id)
    _, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(repository_id=repo_id)

    async def _impact(**kwargs):
        return {"ok": True, "graph": {"resolution_rate": 0.17}}

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
        mock.patch("services.code_graph_tools.run_impact", side_effect=_impact),
        mock.patch(
            "services.code_graph_tools.fetch_graph_for_tool",
            new=mock.AsyncMock(return_value=_fake_graph()),
        ),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=repo_id,
            repo=indexed_repo,
            user=user_obj,
            compare="feature/x",
        )

    assert result["affected_processes"] == []


@pytest.mark.django_db(transaction=True)
async def test_compare_equals_base_sha_explicit(indexed_repo, user_obj) -> None:
    """head == base → 明确 error_code，不静默可信无改动。"""
    repo_id = str(indexed_repo.id)
    same = indexed_repo.last_indexed_commit_sha
    ensure_calls, _, ensure_c, ensure_s, diff_fn = _patch_mirror_pipeline(
        repository_id=repo_id, base_sha=same, head_sha=same
    )

    with (
        mock.patch(
            "services.code_graph_tools._code_graph_access"
        ) as access_factory,
        mock.patch("services.repo_mirror.ensure_mirror_commit", side_effect=ensure_c),
        mock.patch("services.repo_mirror.ensure_mirror_sha", side_effect=ensure_s),
        mock.patch("services.repo_mirror.diff_mirror", side_effect=diff_fn),
    ):
        access_factory.return_value.ensure_repository_readable = mock.AsyncMock()
        result = await run_detect_changes(
            repository_id=repo_id,
            repo=indexed_repo,
            user=user_obj,
            compare=same,  # 40-char sha equal to index waterline
        )

    assert result["ok"] is False
    assert result["error_code"] == "empty_diff_range"
    assert result.get("impacts") in (None, [], ())
