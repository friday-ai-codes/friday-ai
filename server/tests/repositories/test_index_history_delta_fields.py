"""initial implementation plan（work item）：IndexHistory per-run delta + 行级 diff 模型字段测试。

测试覆盖：
1. test_delta_fields_default_zero：5 个 per-run delta 字段 default=0（本次新增非累计）
2. test_line_diff_fields_default_none：2 个行级 diff 字段 default=None（Pitfall 6 三态默认态）
3. test_delta_fields_writable：delta 真实值 + 行级 diff 真实值/显式 None 读回一致
4. test_backward_compat_existing_row：存量行只读新字段不报错（default / null 向后兼容）

注：本 plan 仅落字段 + migration + serializer + 前端类型，不承担回填逻辑（checkpoint）。
"""

from __future__ import annotations

import pytest

from repositories.models import (
    IndexHistory,
    Repository,
    TriggerType,
)


@pytest.fixture
def repo(db) -> Repository:
    """供测试关联的 Repository 实例。"""
    return Repository.objects.create(
        name="delta-fields-repo",
        git_url="https://github.com/org/delta-fields-repo.git",
        git_platform="github",
        default_branch="main",
    )


@pytest.mark.django_db
def test_delta_fields_default_zero(repo: Repository) -> None:
    """work item：新建 IndexHistory 行 5 个 per-run delta 字段应取 default=0。"""
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
    )

    assert history.symbols_added == 0
    assert history.imports_added == 0
    assert history.calls_added == 0
    assert history.endpoints_added == 0
    assert history.chunk_edges_added == 0


@pytest.mark.django_db
def test_line_diff_fields_default_none(repo: Repository) -> None:
    """work item（Pitfall 6）：行级 diff 字段 default=None，区别于真实 0。"""
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
    )

    assert history.lines_added is None
    assert history.lines_deleted is None


@pytest.mark.django_db
def test_delta_fields_writable(repo: Repository) -> None:
    """work item：写入 delta 真实值 + 行级 diff 真实值/显式 None，重查读回一致。"""
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.WEBHOOK,
        symbols_added=42,
        imports_added=7,
        calls_added=13,
        endpoints_added=3,
        chunk_edges_added=21,
        lines_added=10,
        lines_deleted=None,
    )

    refreshed = IndexHistory.objects.get(id=history.id)
    assert refreshed.symbols_added == 42
    assert refreshed.imports_added == 7
    assert refreshed.calls_added == 13
    assert refreshed.endpoints_added == 3
    assert refreshed.chunk_edges_added == 21
    # 行级 diff：真实值与显式 None 都能存（null 可存证明 nullable 生效）
    assert refreshed.lines_added == 10
    assert refreshed.lines_deleted is None


@pytest.mark.django_db
def test_backward_compat_existing_row(repo: Repository) -> None:
    """work item：存量行（仅必填字段）只读新字段不报错（向后兼容）。"""
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
    )

    # 模拟存量行读取新字段：delta 取 default=0，行级 diff 取 None，均不抛异常
    assert history.symbols_added == 0
    assert history.chunk_edges_added == 0
    assert history.lines_added is None
    assert history.lines_deleted is None
