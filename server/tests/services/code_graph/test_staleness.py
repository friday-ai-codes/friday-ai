"""索引 staleness 声明的两条分支（覆盖 D-22）。

``Repository.behind_commits`` 是定时任务算好的库字段（⛔ 请求路径不跑 git），生产 258/258
全覆盖——所以降级分支基本用不上，但 ``_calculate_commit_distance`` 在本地无 clone 时确实
返回 ``None``，且刷新只覆盖 ``auto_index_enabled=True`` 的仓，``None`` 是真实可达的状态。

Wave 0（Plan 122-01）只落骨架，用例由 122-05 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(reason="Wave 0 桩：由 122-05 落地")
def test_behind_commits_reported() -> None:
    """staleness：``behind_commits`` 有值 → 报数字。

    （Req: IMPACT-06, 决策: D-22）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-05 落地")
def test_behind_commits_none_degrades_to_as_of() -> None:
    """staleness：``None`` → 降级只报 ``as_of <sha>``，⛔ 不编造（D-22）。

    （Req: IMPACT-06, 决策: D-22）
    """
    pytest.fail("Wave 0 桩")
