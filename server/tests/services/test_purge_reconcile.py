"""对账 + 两模式清理服务 / API 守护测试（Phase 23 Plan 02，EXCL-04 / EXCL-06）。

服务层（Task 1）：
- ``compute_reconciliation`` 列出「已索引但现命中排除」的差异文件（FileIndex ∪
  ChunkRegistry ∩ 现行匹配器），匹配器构造失败时置 ``degraded`` + ``error``（W3，
  绝不谎报 ``match_count=0`` 假干净）。
- ``run_cleanup(mode="normal")`` 对差异文件逐一调 ``purge_file`` 删净派生面，写出
  ``CleanupRun(status=completed)``；清理后再次对账差异归零（EXCL-04）。
- 清理埋 ``purge.started`` / ``purge.completed`` 审计事件；非法 mode → ValueError；
  ``mode=sensitive`` 但敏感模块未就绪 → failures + ``CleanupRun.error`` 记录且普通清理
  结果不受损（懒导入契约，23-03 提供）。

API 层（Task 2）：
- GET 对账返回差异 JSON（含 degraded）；degraded 场景 GET 返回 ``degraded=true``。
- POST {mode} → 202 + ``run_id`` 且 ``run_in_background`` 被调用（带 cleanup_run_id）。
- GET status 返回最近一次 CleanupRun（含 sensitive 的 unscrubbed/caveat 原样透传）；
  无记录 → ``{status: "none"}``。
- 未认证 → 401/403；不存在仓库 → 404。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db(transaction=True)

RECONCILE_URL = "/api/repositories/{repo_id}/reconcile/"
STATUS_URL = "/api/repositories/{repo_id}/reconcile/status/"


def _seed_chunk(repository: Any, *, file_path: str, branch_name: str = "", index: int = 0) -> Any:
    from code_relations.models import ChunkRegistry

    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repository,
        branch_name=branch_name,
        file_path=file_path,
        chunk_index=index,
    )


class _QdrantSpy:
    """同步 stub：捕获主/overlay 删除调用，返回成功（避免真实 Qdrant 依赖）。"""

    def __init__(self) -> None:
        self.main_calls: list[tuple[str, str]] = []
        self.field_calls: list[tuple[str, str, str]] = []

    def delete_by_file_path(self, repository_id: str, file_path: str) -> bool:
        self.main_calls.append((repository_id, file_path))
        return True

    def delete_by_payload_field(self, collection_name: str, field: str, value: str) -> bool:
        self.field_calls.append((collection_name, field, value))
        return True


@pytest.fixture(autouse=True)
def _block_background():
    """阻断 pre_delete 信号的后台 reconcile 投递与摘要重建后台调度，避免真实外部依赖。"""
    with (
        patch("code_relations.signals.run_in_background", return_value=None),
        patch("services.background_runner.run_in_background", return_value=None),
    ):
        yield


async def _seed_indexed_and_rule(repository: Any) -> None:
    """构造 3 个已索引文件 + 1 条命中其中 1 个的 per-repo 排除规则（glob ``b.py``）。"""
    from asgiref.sync import sync_to_async

    from repositories.models import FileIndex, RepoExclusionRule
    from services.exclusion import invalidate_matcher_cache

    for p in ("src/a.py", "src/b.py", "src/c.py"):
        await sync_to_async(FileIndex.objects.create)(
            repository=repository, file_path=p, file_hash="h"
        )
    await sync_to_async(_seed_chunk)(repository, file_path="src/b.py")
    await sync_to_async(RepoExclusionRule.objects.create)(
        repository=repository, pattern="b.py", rule_type="glob", source="user"
    )
    invalidate_matcher_cache(str(repository.id))


# ============================================================================
# Task 1: 服务层
# ============================================================================


async def test_reconcile_lists_indexed_but_excluded(repository: Any) -> None:
    """对账列出「已索引但现命中排除」的差异文件，degraded=False。"""
    from services.purge_reconcile import compute_reconciliation

    await _seed_indexed_and_rule(repository)

    report = await compute_reconciliation(str(repository.id))
    assert report.indexed_count == 3
    assert report.excluded_paths == ["src/b.py"]
    assert report.match_count == 1
    assert report.degraded is False
    assert report.error == ""
    assert report.suggested_mode == "normal"


async def test_reconcile_degraded_when_matcher_build_fails(
    repository: Any, monkeypatch: Any
) -> None:
    """匹配器构造失败 → degraded=True + error，match_count=0（W3，不谎报已一致）。"""
    from asgiref.sync import sync_to_async

    from repositories.models import FileIndex
    from services import purge_reconcile

    await sync_to_async(FileIndex.objects.create)(
        repository=repository, file_path="x.py", file_hash="h"
    )

    async def _boom(_repo_id: str) -> Any:
        raise RuntimeError("matcher boom")

    monkeypatch.setattr(purge_reconcile, "build_matcher_for_repo", _boom)

    report = await purge_reconcile.compute_reconciliation(str(repository.id))
    assert report.degraded is True
    assert report.error
    assert report.match_count == 0
    assert report.excluded_paths == []


async def test_run_cleanup_normal_purges_and_reconcile_zeroes(repository: Any) -> None:
    """普通清理删净差异文件四面派生数据，写 CleanupRun，且对账归零（EXCL-04）。"""
    from asgiref.sync import sync_to_async

    from code_relations.models import ChunkRegistry
    from repositories.models import CleanupRun, FileIndex
    from services.exclusion import invalidate_matcher_cache
    from services.purge_reconcile import compute_reconciliation, run_cleanup

    await _seed_indexed_and_rule(repository)

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        report = await run_cleanup(str(repository.id), mode="normal")

    assert report.mode == "normal"
    assert report.purged_paths == ["src/b.py"]
    assert not report.failures
    assert report.sensitive is None

    # 删后无残留
    assert (
        await FileIndex.objects.filter(repository_id=repository.id, file_path="src/b.py").acount()
        == 0
    )
    assert (
        await ChunkRegistry.objects.filter(
            repository_id=repository.id, file_path="src/b.py"
        ).acount()
        == 0
    )

    # CleanupRun 持久化
    run = await CleanupRun.objects.filter(repository_id=repository.id).afirst()
    assert run is not None
    assert run.status == "completed"
    assert run.mode == "normal"
    assert run.match_count == 1
    assert run.completed_at is not None

    # 对账归零
    invalidate_matcher_cache(str(repository.id))
    report2 = await compute_reconciliation(str(repository.id))
    assert report2.match_count == 0


async def test_cleanup_emits_audit_events(repository: Any) -> None:
    """清理触发 purge.started / purge.completed 审计事件。"""
    import structlog

    from services.purge_reconcile import run_cleanup

    await _seed_indexed_and_rule(repository)

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        with structlog.testing.capture_logs() as caps:
            await run_cleanup(str(repository.id), mode="normal")

    events = {c["event"] for c in caps}
    assert "purge.started" in events
    assert "purge.completed" in events


async def test_run_cleanup_invalid_mode_raises(repository: Any) -> None:
    """非法 mode → ValueError。"""
    from services.purge_reconcile import run_cleanup

    with pytest.raises(ValueError):
        await run_cleanup(str(repository.id), mode="bogus")


async def test_sensitive_mode_missing_module_records_failure(
    repository: Any, monkeypatch: Any
) -> None:
    """mode=sensitive 但敏感模块未就绪 → failures + CleanupRun.error，普通清理结果不受损。"""
    import sys

    from asgiref.sync import sync_to_async

    from repositories.models import CleanupRun, FileIndex
    from services.purge_reconcile import run_cleanup

    await _seed_indexed_and_rule(repository)

    # 令 `from services.sensitive_purge import ...` 抛 ImportError（23-03 尚未提供）
    monkeypatch.setitem(sys.modules, "services.sensitive_purge", None)

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        report = await run_cleanup(str(repository.id), mode="sensitive")

    # 普通清理仍完成
    assert "src/b.py" in report.purged_paths
    assert (
        await FileIndex.objects.filter(repository_id=repository.id, file_path="src/b.py").acount()
        == 0
    )
    # 敏感分支失败被记录
    assert any("sensitive" in f for f in report.failures)

    run = await CleanupRun.objects.filter(repository_id=repository.id).afirst()
    assert run is not None
    assert run.error
    assert run.status == "failed"


# ============================================================================
# Task 2: REST API
# ============================================================================


class TestReconcileAPI:
    def test_get_returns_diff(self, authenticated_client: Any, repository: Any) -> None:
        from asgiref.sync import async_to_sync

        async_to_sync(_seed_indexed_and_rule)(repository)

        resp = authenticated_client.get(RECONCILE_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexed_count"] == 3
        assert data["excluded_paths"] == ["src/b.py"]
        assert data["match_count"] == 1
        assert data["degraded"] is False
        assert data["suggested_mode"] == "normal"

    def test_get_degraded_surfaces_error(self, authenticated_client: Any, repository: Any) -> None:
        from services import purge_reconcile

        async def _boom(_repo_id: str) -> Any:
            raise RuntimeError("matcher boom")

        with patch.object(purge_reconcile, "build_matcher_for_repo", _boom):
            resp = authenticated_client.get(RECONCILE_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["degraded"] is True
        assert data["error"]
        assert data["match_count"] == 0

    def test_post_dispatches_background_with_run_id(
        self, authenticated_client: Any, repository: Any
    ) -> None:
        from asgiref.sync import async_to_sync

        from repositories.models import CleanupRun

        async_to_sync(_seed_indexed_and_rule)(repository)

        with patch("repositories.views.run_in_background") as bg:
            resp = authenticated_client.post(
                RECONCILE_URL.format(repo_id=repository.id),
                {"mode": "sensitive"},
                format="json",
            )
        assert resp.status_code == 202
        body = resp.json()
        assert body["mode"] == "sensitive"
        assert body["dispatched"] is True
        assert body["run_id"]
        assert body["match_count"] == 1

        # CleanupRun(status=running) 已落库供后台更新
        run = CleanupRun.objects.get(id=body["run_id"])
        assert run.status == "running"
        assert run.mode == "sensitive"
        # 后台派发被调用一次，且带 name（cleanup_run_id 由闭包透传）
        bg.assert_called_once()

    def test_post_invalid_mode_400(self, authenticated_client: Any, repository: Any) -> None:
        resp = authenticated_client.post(
            RECONCILE_URL.format(repo_id=repository.id),
            {"mode": "bogus"},
            format="json",
        )
        assert resp.status_code == 400

    def test_get_404_missing_repo(self, authenticated_client: Any) -> None:
        resp = authenticated_client.get(
            RECONCILE_URL.format(repo_id="00000000-0000-0000-0000-000000000001")
        )
        assert resp.status_code == 404

    def test_unauthenticated_blocked(self, api_client: Any, repository: Any) -> None:
        resp = api_client.get(RECONCILE_URL.format(repo_id=repository.id))
        assert resp.status_code in (401, 403)


class TestCleanupStatusAPI:
    def test_status_returns_latest_run_with_sensitive(
        self, authenticated_client: Any, repository: Any
    ) -> None:
        from repositories.models import CleanupRun

        CleanupRun.objects.create(
            repository=repository,
            mode="sensitive",
            status="completed",
            match_count=2,
            failures=[],
            sensitive={
                "scrubbed": {"audit_log": 3},
                "unscrubbed": ["external_siem"],
                "caveat": "外部 SIEM 留存需手动清理",
            },
        )

        resp = authenticated_client.get(STATUS_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "sensitive"
        assert data["status"] == "completed"
        assert data["match_count"] == 2
        # sensitive 的 unscrubbed/caveat 原样透传（W1/W2）
        assert data["sensitive"]["unscrubbed"] == ["external_siem"]
        assert data["sensitive"]["caveat"]

    def test_status_none_when_no_runs(self, authenticated_client: Any, repository: Any) -> None:
        resp = authenticated_client.get(STATUS_URL.format(repo_id=repository.id))
        assert resp.status_code == 200
        assert resp.json() == {"status": "none"}

    def test_status_404_missing_repo(self, authenticated_client: Any) -> None:
        resp = authenticated_client.get(
            STATUS_URL.format(repo_id="00000000-0000-0000-0000-000000000001")
        )
        assert resp.status_code == 404
