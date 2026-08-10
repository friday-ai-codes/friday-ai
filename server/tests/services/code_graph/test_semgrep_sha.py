"""挂点两端 commit sha 解析（Phase 127 / TAINT-01 / CR-01；D-01..D-04）。

覆盖优先级：已知 sha → 平台 client → 本地镜像；全失败返回空串（不抛）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.code_graph.semgrep_sha import (
    normalize_sha,
    resolve_branch_sha,
    resolve_scan_shas,
)

pytestmark = [pytest.mark.asyncio]

_SHA_A = "a" * 40
_SHA_B = "b" * 40


async def test_normalize_sha_rejects_partial_and_dirty_values() -> None:
    """仅接受 40 位 hex；短 sha / 分支名 / None 一律空串。

    （Req: TAINT-01）
    """
    assert normalize_sha(f"  {_SHA_A.upper()}  ") == _SHA_A
    assert normalize_sha("abc1234") == ""
    assert normalize_sha("main") == ""
    assert normalize_sha(None) == ""


async def test_known_sha_short_circuits_client_and_mirror() -> None:
    """已有完整 sha 时不再问平台（省一次 API 调用）。

    （Req: TAINT-01, 决策: D-04）
    """
    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(return_value=_SHA_B)

    sha = await resolve_branch_sha(
        repository_id="repo-1",
        branch="feat/x",
        client=client,
        known_sha=_SHA_A,
    )
    assert sha == _SHA_A
    client.resolve_branch_sha.assert_not_awaited()


async def test_client_resolution_wins_over_mirror(monkeypatch) -> None:
    """client 能解析时不落到镜像。

    （Req: TAINT-01, 决策: D-02）
    """
    mirror = AsyncMock(side_effect=AssertionError("镜像不应被调用"))
    monkeypatch.setattr("services.repo_mirror.ensure_mirror_commit", mirror)

    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(return_value=_SHA_B)

    sha = await resolve_branch_sha(repository_id="repo-1", branch="main", client=client)
    assert sha == _SHA_B


async def test_client_failure_falls_back_to_mirror(monkeypatch) -> None:
    """client 抛异常时降级镜像，不上抛。

    （Req: TAINT-01；威胁: T-127-02）
    """

    class _Snapshot:
        commit_sha = _SHA_A

    async def _fake_mirror(repository_id, branch=None):
        return _Snapshot()

    monkeypatch.setattr("services.repo_mirror.ensure_mirror_commit", _fake_mirror)

    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(side_effect=RuntimeError("platform 502"))

    sha = await resolve_branch_sha(repository_id="repo-1", branch="main", client=client)
    assert sha == _SHA_A


async def test_all_sources_failing_returns_empty_pair(monkeypatch) -> None:
    """两端都解析不到时返回空串对（调用方据此跳过入队）。

    （Req: TAINT-01, 决策: D-04）
    """
    monkeypatch.setattr(
        "services.repo_mirror.ensure_mirror_commit",
        AsyncMock(side_effect=RuntimeError("mirror down")),
    )
    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(return_value="")

    source, target = await resolve_scan_shas(
        repository_id="repo-1",
        source_branch="feat/x",
        target_branch="main",
        client=client,
    )
    assert (source, target) == ("", "")


async def test_resolve_scan_shas_mixes_known_and_client(monkeypatch) -> None:
    """source 用已知 commit_sha、target 经 client 解析（mr_service 形态）。

    （Req: TAINT-01, 决策: D-04）
    """
    client = AsyncMock()
    client.resolve_branch_sha = AsyncMock(
        side_effect=lambda branch: _SHA_B if branch == "develop" else ""
    )

    source, target = await resolve_scan_shas(
        repository_id="repo-1",
        source_branch="friday/task-2",
        target_branch="develop",
        client=client,
        source_sha=_SHA_A,
    )
    assert source == _SHA_A
    assert target == _SHA_B
