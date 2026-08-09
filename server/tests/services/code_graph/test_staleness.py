"""索引 staleness 声明的两条分支（覆盖 D-22）。

``Repository.behind_commits`` 是定时任务算好的库字段（⛔ 请求路径不跑 git），生产 258/258
全覆盖——所以降级分支基本用不上，但 ``_calculate_commit_distance`` 在本地无 clone 时确实
返回 ``None``，且刷新只覆盖 ``auto_index_enabled=True`` 的仓，``None`` 是真实可达的状态。

由 122-05 填实。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from services.code_graph_tools import staleness_payload

pytestmark = pytest.mark.django_db


def _make_repo(**overrides):
    """造一个带新鲜度字段的仓。默认形态是 ``stale``：本地水位与远端 HEAD 不同。"""
    from repositories.models import IndexStatus, Repository

    fields = {
        "name": "staleness-test-repo",
        "git_url": "https://example.com/staleness-test-repo.git",
        "default_branch": "main",
        "index_status": IndexStatus.INDEXED,
        "is_deleted": False,
        "last_indexed_commit_sha": "a" * 40,
        "remote_head_sha": "b" * 40,
        "remote_head_checked_at": timezone.now(),
    }
    fields.update(overrides)
    return Repository.objects.create(**fields)


@pytest.mark.django_db(transaction=True)
async def test_behind_commits_reported() -> None:
    """staleness：``behind_commits`` 有值 → 报数字。

    （Req: IMPACT-06, 决策: D-22）
    """
    repo = await sync_to_async(_make_repo)(
        behind_commits=7, behind_commits_calculated_at=timezone.now()
    )

    payload = await staleness_payload(repo)

    assert payload["behind_commits"] == 7
    assert payload["freshness"] == "stale"
    assert payload["as_of"] == "a" * 40
    assert "7" in payload["declaration"]
    # 计算时间必须一并透出：一个「落后 7」如果是三周前算的，它本身也已经过期了。
    assert isinstance(payload["behind_commits_calculated_at"], str)


@pytest.mark.django_db(transaction=True)
async def test_behind_commits_none_degrades_to_as_of() -> None:
    """staleness：``None`` → 降级只报 ``as_of <sha>``，⛔ 不编造（D-22）。

    ``None`` 不是理论分支：``_calculate_commit_distance`` 在本地无 clone 时返回 ``None``
    （``freshness_service.py:88-94``），而刷新任务只覆盖 ``auto_index_enabled=True`` 的仓。
    此时一个凭空的「落后 3 commits」会让 agent 以为索引只差一点点，而真相可能差三百个。

    （Req: IMPACT-06, 决策: D-22）
    """
    repo = await sync_to_async(_make_repo)(
        behind_commits=None, behind_commits_calculated_at=None
    )

    payload = await staleness_payload(repo)

    assert payload["behind_commits"] is None
    assert payload["behind_commits_calculated_at"] is None
    declaration = payload["declaration"]
    # 降级形态：报 as_of 的 sha 前 12 位。
    assert ("a" * 12) in declaration
    # ⛔ 没有编造出来的「落后 N」——提到「落后」时必须同时说明它未知。
    assert "落后" not in declaration or "未知" in declaration
    assert not any(ch.isdigit() for ch in declaration.replace("a" * 12, ""))

    # 三态的第三条：从没查过远端 ⇒ unknown，⛔ 不得误报 fresh。
    never_checked = await sync_to_async(_make_repo)(
        name="staleness-unknown-repo",
        git_url="https://example.com/staleness-unknown-repo.git",
        remote_head_checked_at=None,
    )
    assert (await staleness_payload(never_checked))["freshness"] == "unknown"
