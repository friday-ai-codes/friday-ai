"""跨仓一跳的四条分支（覆盖 IMPACT-03）。

🚨 **全部靠合成数据**：生产库 ``CrossRepoApiCall`` / ``ApiCallSite`` / ``ApiWrapper`` 均为
**0 行**（上游产出器依赖 volar LSP，server 镜像无 Node，归 LSP-01 / Phase 127）。本文件的
绿测**不得**被表述成「跨仓能力已在真实数据上验证」（D-26）——Phase 127 补齐 LSP 后需回来
用真实样本复验。

造数走 conftest 的 ``cross_repo_call_factory``（``endpoint_repository`` 传另一个仓即造出真
跨仓行）。⚠️ 图里 ``kind == "cross_repo"`` 的边**从来不跨仓**（``loader`` 只在两端同为本仓
时才建边），所以跨仓穿越走 ORM 直查而不是沿图边走（D-25）。

Wave 0（Plan 122-01）只落骨架，用例由 122-06 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_cross_repo_success() -> None:
    """跨仓一跳：对端仓成功 → ``cross_repo: true`` + ``match_confidence`` 原值。

    （Req: IMPACT-03, 决策: D-13 / D-25）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_unauthorized_repo_redacted() -> None:
    """``GraphAccessDenied`` → 整仓折叠 ``REDACTED_REPOSITORY``，不泄漏仓名/路径/符号名（D-12）。

    折叠条目按 D-30 **不带** ``affected_count``：计数会泄漏一个调用方无权访问的仓库的内部
    规模，构成存在性预言机。

    （Req: IMPACT-03, 决策: D-12 / D-30）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_peer_unavailable_fail_soft() -> None:
    """``GraphNotIndexed`` / ``GraphBuildTimeout`` → ``unavailable_reason`` 条目，本仓结果
    照常返回（D-14）。

    fail-soft 但**必须显式声明**：静默丢弃会让 agent 以为影响面更小。

    （Req: IMPACT-03, 决策: D-14）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_hop_budget() -> None:
    """``max_cross_repo_hops=1`` 不递归（D-11）。

    （Req: IMPACT-03, 决策: D-11）
    """
    pytest.fail("Wave 0 桩")
