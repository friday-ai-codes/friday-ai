"""`repo_group_scope.aresolve_grouping_repo_ids` 单测（D-2 宽口径并集，107-07 Task 1）。

覆盖：并集语义 / 去重 / 无 Project 退化 / `None` 与空集的语义分离 / 两个入口
（work_item_id / space_id）/ verified 半边失败降级 / 返回值类型归一 / 双参优先级。

transaction=True：async 用例经 `sync_to_async` 桥接在独立线程连接建数据，普通
`django_db`（rollback）无法回滚跨线程连接的提交。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from codegraph.services.repo_group_scope import aresolve_grouping_repo_ids

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# 建数据 helper（同步 ORM 经 sync_to_async）
# ---------------------------------------------------------------------------


@sync_to_async
def _make_space(*, repo_count: int = 0) -> tuple[str, list[str]]:
    """建 Space + N 个已关联仓，返回 (space_id, [repo_id...])。"""
    from projects.models import Space
    from repositories.models import Repository

    space = Space.objects.create(
        name=f"grp-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    repo_ids: list[str] = []
    for i in range(repo_count):
        repo = Repository.objects.create(
            name=f"repo-{i}-{uuid.uuid4().hex[:4]}",
            git_url=f"https://example.com/{uuid.uuid4().hex[:8]}.git",
        )
        space.repositories.add(repo)
        repo_ids.append(str(repo.id))
    return str(space.id), repo_ids


@sync_to_async
def _make_work_item(space_id: str | None) -> str:
    """建 WorkItem（space 可为 None），返回 work_item 主键字符串。"""
    from delivery.models import WorkItem, WorkItemOrigin
    from projects.models import Space

    space = Space.objects.get(id=space_id) if space_id else None
    wi = WorkItem.objects.create(
        feishu_project_key=f"pk-{uuid.uuid4().hex[:6]}",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 1_000_000),
        origin=WorkItemOrigin.MANUAL,
        space=space,
        title="t",
    )
    return str(wi.id)


@sync_to_async
def _make_verified_association(space_id: str, *, repo_id: str | None = None) -> str:
    """在 space 下建 Project + 一条 verified 关联，返回被关联仓 id。

    `repo_id` 为 None 时新建一个「不在 Space.repositories 里」的仓（跨半边样本）。
    """
    from initiatives.models import Project, RepoAssociation, RepoAssociationStatus
    from projects.models import Space
    from repositories.models import Repository

    space = Space.objects.get(id=space_id)
    project = Project.objects.create(space=space, name=f"proj-{uuid.uuid4().hex[:6]}")
    if repo_id is None:
        repo = Repository.objects.create(
            name=f"outside-{uuid.uuid4().hex[:4]}",
            git_url=f"https://example.com/{uuid.uuid4().hex[:8]}.git",
        )
    else:
        repo = Repository.objects.get(id=repo_id)
    RepoAssociation.objects.create(
        project=project,
        repository=repo,
        status=RepoAssociationStatus.VERIFIED,
    )
    return str(repo.id)


# ---------------------------------------------------------------------------
# 并集语义
# ---------------------------------------------------------------------------


async def test_work_item_returns_union_of_space_and_verified() -> None:
    """space 2 仓 + 该 space 下 Project 1 条 verified（第 3 个仓）→ 并集 3 个 id。"""
    space_id, space_repos = await _make_space(repo_count=2)
    verified_repo = await _make_verified_association(space_id)
    work_item_id = await _make_work_item(space_id)

    result = await aresolve_grouping_repo_ids(work_item_id=work_item_id)

    assert result == frozenset({*space_repos, verified_repo})
    assert len(result) == 3


async def test_union_deduplicates_repo_present_in_both_halves() -> None:
    """同一个仓既在 Space.repositories 又在 verified 关联中 → 并集去重为 1 个 id。"""
    space_id, space_repos = await _make_space(repo_count=1)
    verified_repo = await _make_verified_association(space_id, repo_id=space_repos[0])
    work_item_id = await _make_work_item(space_id)

    result = await aresolve_grouping_repo_ids(work_item_id=work_item_id)

    assert verified_repo == space_repos[0]
    assert result == frozenset({space_repos[0]})
    assert len(result) == 1


async def test_space_without_project_returns_space_repositories() -> None:
    """space 存在但无 Project → 返回 Space.repositories（不抛）。"""
    space_id, space_repos = await _make_space(repo_count=2)
    work_item_id = await _make_work_item(space_id)

    result = await aresolve_grouping_repo_ids(work_item_id=work_item_id)

    assert result == frozenset(space_repos)


# ---------------------------------------------------------------------------
# None（无项目上下文）与空集（有上下文零关联仓）语义分离
# ---------------------------------------------------------------------------


async def test_missing_work_item_returns_none() -> None:
    """work_item_id 不存在 → None（= 无项目上下文，调用方据此跳过分组）。"""
    result = await aresolve_grouping_repo_ids(work_item_id=str(uuid.uuid4()))

    assert result is None


async def test_work_item_without_space_returns_none() -> None:
    """WorkItem 无 space → None。"""
    work_item_id = await _make_work_item(None)

    result = await aresolve_grouping_repo_ids(work_item_id=work_item_id)

    assert result is None


async def test_space_with_zero_repositories_returns_empty_frozenset() -> None:
    """有上下文但该项目零关联仓 → 空 frozenset（**不是** None，语义不同）。"""
    space_id, _ = await _make_space(repo_count=0)

    result = await aresolve_grouping_repo_ids(space_id=space_id)

    assert result is not None
    assert result == frozenset()


# ---------------------------------------------------------------------------
# space_id 入口
# ---------------------------------------------------------------------------


async def test_space_id_entry_returns_union() -> None:
    """space_id 入口：Project 存在时并集含 verified 半边。"""
    space_id, space_repos = await _make_space(repo_count=1)
    verified_repo = await _make_verified_association(space_id)

    result = await aresolve_grouping_repo_ids(space_id=space_id)

    assert result == frozenset({*space_repos, verified_repo})


async def test_missing_space_returns_none() -> None:
    """space_id 不存在 → None。"""
    result = await aresolve_grouping_repo_ids(space_id=str(uuid.uuid4()))

    assert result is None


# ---------------------------------------------------------------------------
# verified 半边失败降级 / 类型归一 / 双参优先级
# ---------------------------------------------------------------------------


async def test_verified_query_failure_degrades_to_space_half(monkeypatch) -> None:
    """RepoAssociation 查询抛异常 → 降级为只返回 Space.repositories，不抛。"""
    space_id, space_repos = await _make_space(repo_count=2)
    await _make_verified_association(space_id)

    from initiatives.services.repo_association_service import RepoAssociationService

    async def _boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(
        RepoAssociationService, "get_verified_associations", _boom, raising=True
    )

    result = await aresolve_grouping_repo_ids(space_id=space_id)

    assert result == frozenset(space_repos)


async def test_result_is_frozenset_of_str_ids() -> None:
    """返回值为 frozenset[str]（与 RepoRouteCandidateV2.repo_id 类型一致）。"""
    space_id, space_repos = await _make_space(repo_count=1)

    result = await aresolve_grouping_repo_ids(space_id=space_id)

    assert isinstance(result, frozenset)
    assert all(isinstance(r, str) for r in result)
    assert result == frozenset(space_repos)


async def test_work_item_id_takes_precedence_over_space_id() -> None:
    """同时传两个参数 → 以 work_item_id 为准（另一个 space 的仓不进结果）。"""
    wi_space_id, wi_repos = await _make_space(repo_count=1)
    other_space_id, other_repos = await _make_space(repo_count=1)
    work_item_id = await _make_work_item(wi_space_id)

    result = await aresolve_grouping_repo_ids(
        work_item_id=work_item_id, space_id=other_space_id
    )

    assert result == frozenset(wi_repos)
    assert frozenset(other_repos).isdisjoint(result)
