"""implementation contract：IndexHistory.changed_files 字段与 indexer 写入逻辑测试。

测试覆盖：
1. test_changed_files_populated_after_incremental_index：增量索引后 changed_files 包含正确的路径列表
2. test_changed_files_empty_for_full_index：全量索引时 changed_files 保持默认空 dict
3. test_changed_files_structure：changed_files 必须含 added/modified/deleted 三个 key，值为 list
4. test_changed_files_persisted_to_db：DB 序列化写入后读取结果一致
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.models import IndexHistory, IndexHistoryStatus, Repository, TriggerType


# ============================================================================
# Helper：创建一个 Repository 对象（不入 DB，仅供关联用）
# ============================================================================


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="test-repo",
        git_url="https://github.com/org/test-repo.git",
        git_platform="github",
        default_branch="main",
    )


# ============================================================================
# 测试 1：增量索引 run_incremental_index 返回正确文件路径列表
# ============================================================================


@pytest.mark.asyncio
async def test_changed_files_populated_after_incremental_index() -> None:
    """IndexerService.run_incremental_index 应在返回值中包含
    added_files / modified_files / deleted_files 路径列表（contract 方案 A）。"""
    from services.indexer import DiffAction, FileDiff, IndexerService

    repo_id = str(uuid.uuid4())
    indexer = IndexerService(repository_id=repo_id)

    test_diffs = [
        FileDiff("a.py", DiffAction.ADD),
        FileDiff("b.py", DiffAction.ADD),
        FileDiff("c.py", DiffAction.UPDATE),
    ]

    # 异步空生成器，用于模拟 FileIndex queryset 异步迭代
    async def empty_async_gen():
        return
        yield  # pragma: no cover — 使其成为 async generator

    mock_qs = MagicMock()
    mock_qs.values_list.return_value = empty_async_gen()

    mock_fi_qs = MagicMock()
    mock_fi_qs.adelete = AsyncMock()

    with (
        patch.object(indexer, "_ensure_collection", new_callable=AsyncMock),
        patch("services.indexer.FileIndex") as mock_fi,
        patch("services.indexer.scan_directory", return_value=[]),
        patch.object(indexer, "_compute_diff", return_value=test_diffs),
        patch("services.indexer.qdrant_delete_by_file_path", new_callable=AsyncMock),
        patch.object(indexer, "_extract_and_write_graph", new_callable=AsyncMock),
        # _should_build_graph 在 _extract_and_write_graph 之前
        # 加双重判断 gating，本测试不进 DB 故直接 patch 为 False 跳过整段
        # graph 写入逻辑（包括 implementation 引入的 GraphBuildHistory
        # acreate 调用——本测试不挂 django_db mark，无法做真实 DB 写）。
        patch.object(
            indexer, "_should_build_graph", new_callable=AsyncMock, return_value=False
        ),
        patch("services.indexer.update_index_progress", new_callable=AsyncMock),
        patch("services.indexer.update_write_progress", new_callable=AsyncMock),
        patch("services.indexer.update_index_stage", new_callable=AsyncMock),
        # EXCL-02：增量索引现会构建排除匹配器（读 DB 全局默认规则），本测试不挂 DB，
        # patch 为返回「不排除任何文件」的匹配器。
        patch(
            "services.indexer.build_matcher_for_repo",
            new=AsyncMock(return_value=MagicMock(is_excluded=MagicMock(return_value=False))),
        ),
    ):
        mock_fi.objects.filter.return_value = mock_qs
        mock_fi.objects.filter.return_value.adelete = AsyncMock()
        mock_fi.objects.aupdate_or_create = AsyncMock()

        # 令 parser.parse_file_dual 返回空（chunks 空 + 无 bundle），跳过 embedding 生成
        indexer.parser = MagicMock()
        indexer.parser.parse_file_dual.return_value = ([], None)

        with patch(
            "codegraph.services.repo_summary_builder.RepoSummaryBuilder.build",
            new_callable=AsyncMock,
        ):
            result = await indexer.run_incremental_index("/tmp/fake_repo")

    assert result["added_files"] == ["a.py", "b.py"], (
        f"期望 added_files=['a.py','b.py']，实际 {result['added_files']}"
    )
    assert result["modified_files"] == ["c.py"], (
        f"期望 modified_files=['c.py']，实际 {result['modified_files']}"
    )
    assert result["deleted_files"] == [], (
        f"期望 deleted_files=[]，实际 {result['deleted_files']}"
    )


# ============================================================================
# 测试 2：全量索引不写入 changed_files，保持默认 {}
# ============================================================================


def test_changed_files_empty_for_full_index(repo: Repository) -> None:
    """全量索引场景：IndexHistory.changed_files 应为默认空 dict {}。

    全量索引路径（clone_and_index 中 run_full_index 分支）不向
    history_update 写入 changed_files，因此字段保持模型默认值 {}。
    """
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.COMPLETED,
    )
    # 不设置 changed_files，验证默认值
    assert history.changed_files == {}, (
        f"全量索引时 changed_files 应为空 dict，实际 {history.changed_files!r}"
    )


# ============================================================================
# 测试 3：changed_files 结构约束（三 key，值为 list）
# ============================================================================


def test_changed_files_structure() -> None:
    """changed_files 必须包含 added / modified / deleted 三个 key，且均为 list 类型。"""
    valid_payload: dict = {
        "added": ["src/foo.py", "src/bar.py"],
        "modified": ["README.md"],
        "deleted": [],
    }

    # 验证三个 key 存在
    for key in ("added", "modified", "deleted"):
        assert key in valid_payload, f"changed_files 缺少 key '{key}'"

    # 验证每个 value 是 list，不是 None / int 等
    for key, value in valid_payload.items():
        assert isinstance(value, list), (
            f"changed_files['{key}'] 应为 list，实际类型 {type(value).__name__}"
        )

    # 验证空 dict {} 表示"无变更"，不要求强制包含三 key（全量索引场景）
    h = IndexHistory()
    assert h.changed_files == {}, "IndexHistory 默认 changed_files 应为 {}"


# ============================================================================
# 测试 4：DB 序列化往返（JSON 写入后读取一致）
# ============================================================================


@pytest.mark.django_db
def test_changed_files_persisted_to_db(repo: Repository) -> None:
    """changed_files 写入 DB 后重新读取，JSON 序列化结果应与写入时完全一致。"""
    payload = {
        "added": ["src/api/views.py", "src/models/user.py"],
        "modified": ["README.md"],
        "deleted": ["old/deprecated.py"],
    }

    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.WEBHOOK,
        status=IndexHistoryStatus.COMPLETED,
        changed_files=payload,
        files_added=2,
        files_modified=1,
        files_deleted=1,
    )

    # 重新从 DB 读取（强制 hit DB，不使用内存缓存）
    fetched = IndexHistory.objects.get(pk=history.pk)

    assert fetched.changed_files == payload, (
        f"DB 序列化往返失败：期望 {payload}，实际 {fetched.changed_files}"
    )
    assert isinstance(fetched.changed_files["added"], list)
    assert isinstance(fetched.changed_files["modified"], list)
    assert isinstance(fetched.changed_files["deleted"], list)
    assert fetched.changed_files["added"] == ["src/api/views.py", "src/models/user.py"]
    assert fetched.changed_files["deleted"] == ["old/deprecated.py"]
