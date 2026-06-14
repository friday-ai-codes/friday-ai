"""Phase 24（EXCL-03）敏感检测触发时机守护测试 —— BL-01/HI-01 修复后重写。

历史背景：早前实现把 ``detect_sensitive_files`` 经 ``run_in_background`` 在
``run_full_index`` 末尾后台派发，而 ``clone_and_index_repository`` 在 ``finally`` 里
``shutil.rmtree(temp_dir)`` —— 二者竞态，后台遍历几乎必然撞上已删除目录 → 静默漏报全部
密钥。旧守护测试用固定字符串 ``repo_path`` + mock ``detect_sensitive_files``，恰好绕开了
这条真实交互，给了虚假信心。

本测试改为**真实交互**：实际把 ``.env`` / ``id_rsa`` 落到临时目录，跑生产
``_run_sensitive_detection`` + ``finally`` 删除时序，断言建议确实入库且目录已删除。

覆盖：
- **Section A 源码 guard**：检测须在 ``clone_and_index_repository`` 删除 temp_dir **之前**
  同步触发；``run_full_index`` 不再后台派发检测（防回退到竞态实现）。
- **Section B 真实集成（BL-01）**：真实文件 + rmtree-in-finally 时序，建议入库 + 目录删除。
- **Section C 漏报回归（BL-01）**：先删目录再检测 → 0 候选（复现竞态失败态，证明顺序的必要性）。
- **Section D 增量范围（HI-01）**：``_detection_only_paths`` + ``only_paths`` 仅扫本次变更文件。
"""

from __future__ import annotations

import inspect
import os
import shutil
import tempfile
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from services.background_runner import run_in_background

pytestmark = pytest.mark.django_db(transaction=True)

AWS_SECRET_VALUE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
PRIVATE_KEY_BODY = "b3BlbnNzaC1rZXktdjEAAAFAKEPRIVATEKEYBODYDONOTLOGabcdef0123456789"


async def _make_repo() -> Any:
    from repositories.models import Repository

    return await sync_to_async(Repository.objects.create)(
        name="Sensitive Trigger Repo",
        git_url="https://example.com/sec/repo.git",
        git_platform="github",
        default_branch="main",
    )


async def _suggestions(repo_id: Any) -> list[Any]:
    from repositories.models import SensitiveFileSuggestion

    return await sync_to_async(
        lambda: list(SensitiveFileSuggestion.objects.filter(repository_id=repo_id))
    )()


def _seed_repo_dir(root: str) -> None:
    """在仓库目录落真实敏感文件：含 AWS key 的 .env + 私钥块 id_rsa。"""
    with open(os.path.join(root, ".env"), "w", encoding="utf-8") as fh:
        fh.write(f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_VALUE}\n")
    secrets_dir = os.path.join(root, "secrets")
    os.makedirs(secrets_dir, exist_ok=True)
    with open(os.path.join(secrets_dir, "id_rsa"), "w", encoding="utf-8") as fh:
        fh.write(
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            f"{PRIVATE_KEY_BODY}\n"
            "-----END OPENSSH PRIVATE KEY-----\n"
        )


# ---------------------------------------------------------------------------
# Section A：源码 guard —— 检测须在 rmtree 之前同步触发，且不再后台派发
# ---------------------------------------------------------------------------


def test_detection_runs_before_rmtree_in_clone_and_index() -> None:
    """``clone_and_index_repository`` 必须在 ``shutil.rmtree(temp_dir)`` 之前触发检测。"""
    from services.indexer import clone_and_index_repository

    src = inspect.getsource(clone_and_index_repository)
    detect_idx = src.find("_run_sensitive_detection(")
    rmtree_idx = src.find("shutil.rmtree(temp_dir")

    assert detect_idx >= 0, "clone_and_index_repository 缺少 _run_sensitive_detection 触发"
    assert rmtree_idx >= 0, "clone_and_index_repository 缺少 shutil.rmtree(temp_dir)"
    assert detect_idx < rmtree_idx, (
        "敏感检测必须在 rmtree(temp_dir) 之前触发（否则遍历已删除目录 → 静默漏报，BL-01）"
    )


def test_run_full_index_no_longer_background_dispatches_detection() -> None:
    """``run_full_index`` 不得再后台派发检测（防回退到与 rmtree 竞态的实现，BL-01）。"""
    from services.indexer import IndexerService

    src = inspect.getsource(IndexerService.run_full_index)
    assert "detect_sensitive_files" not in src, (
        "run_full_index 不应再直接派发 detect_sensitive_files —— 已上移至 "
        "clone_and_index_repository 在 rmtree 前同步触发（BL-01）"
    )


def test_detection_helper_is_awaited_not_fire_and_forget() -> None:
    """``_run_sensitive_detection`` 调用须被 ``await``（同步收敛于 rmtree 之前）。"""
    from services.indexer import clone_and_index_repository

    src = inspect.getsource(clone_and_index_repository)
    assert "await _run_sensitive_detection(" in src, (
        "_run_sensitive_detection 必须被 await（不能 fire-and-forget，否则重蹈 BL-01 竞态）"
    )


# ---------------------------------------------------------------------------
# Section B：真实集成 —— 真实文件 + rmtree-in-finally 时序（BL-01）
# ---------------------------------------------------------------------------


async def test_detection_persists_before_temp_dir_removed() -> None:
    """复刻 clone_and_index_repository 的「检测 → finally rmtree」时序（生产 helper）。

    用真实临时目录 + 真实 .env/id_rsa + 生产 ``_run_sensitive_detection``（内部 await
    真实 ``detect_sensitive_files``）。断言：建议在目录删除前确已入库，且目录已删除。
    """
    from services.indexer import _run_sensitive_detection

    repo = await _make_repo()
    temp_dir = tempfile.mkdtemp(prefix="friday_index_test_")
    _seed_repo_dir(temp_dir)

    # 全量索引语义：index_result 不带 added_files → only_paths=None → 整仓扫描。
    index_result = {"status": "success", "files_processed": 2, "added": 2}
    try:
        await _run_sensitive_detection(str(repo.id), temp_dir, index_result)
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    # 目录确已删除（复刻生产 finally 行为）。
    assert not os.path.exists(temp_dir)

    rows = await _suggestions(repo.id)
    paths = {r.path for r in rows}
    # 检测在 rmtree 之前跑完 → 真实密钥被发现（修复前后台派发几乎必然漏报）。
    assert ".env" in paths, "检测应在删除前发现 .env（BL-01 竞态修复）"
    assert "secrets/id_rsa" in paths, "检测应在删除前发现 secrets/id_rsa（BL-01 竞态修复）"

    env_row = next(r for r in rows if r.path == ".env")
    assert env_row.severity == "real_secret"
    # 脱敏不变量：密钥本体绝不入 reason。
    assert AWS_SECRET_VALUE not in env_row.reason


async def test_detection_failure_does_not_propagate(monkeypatch) -> None:
    """检测内部抛异常时，``_run_sensitive_detection`` 不冒泡（best-effort，T-24-05）。"""
    from services import indexer

    async def _boom(*_a, **_k):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr("services.sensitive_detect.detect_sensitive_files", _boom, raising=True)

    # 不抛即通过（异常被 helper 内 try/except 吞掉并记 warning）。
    await indexer._run_sensitive_detection("repo-x", "/tmp/does-not-matter", {"added": 1})


# ---------------------------------------------------------------------------
# Section C：漏报回归 —— 先删目录再检测应得 0 候选（复现竞态失败态）
# ---------------------------------------------------------------------------


async def test_detection_after_dir_deleted_finds_nothing() -> None:
    """显式复现 BL-01 失败态：目录已删除后再检测 → 0 候选（证明顺序的必要性）。"""
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    temp_dir = tempfile.mkdtemp(prefix="friday_index_race_")
    _seed_repo_dir(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)  # 模拟 rmtree 抢先

    count = await detect_sensitive_files(str(repo.id), temp_dir)
    assert count == 0
    assert await _suggestions(repo.id) == []


# ---------------------------------------------------------------------------
# Section D：增量范围（HI-01）
# ---------------------------------------------------------------------------


def test_detection_only_paths_full_vs_incremental() -> None:
    """``_detection_only_paths``：全量 → None（整仓）；增量/diff → 仅 added+modified。"""
    from services.indexer import _detection_only_paths

    # 全量索引结果不带文件列表 → None（整仓扫描）。
    assert _detection_only_paths({"status": "success", "added": 3}) is None

    # 增量/diff 结果 → 仅本次新增 + 修改（删除不扫）。
    only = _detection_only_paths(
        {
            "added_files": ["a/.env"],
            "modified_files": ["b/config.yaml"],
            "deleted_files": ["c/old.txt"],
        }
    )
    assert only is not None
    assert set(only) == {"a/.env", "b/config.yaml"}


async def test_incremental_detection_scoped_to_changed_files() -> None:
    """``only_paths`` 仅检测本次变更文件——未变更的密钥文件不被重扫（HI-01）。"""
    from services.sensitive_detect import detect_sensitive_files

    repo = await _make_repo()
    temp_dir = tempfile.mkdtemp(prefix="friday_index_incr_")
    try:
        # 两个密钥文件，但本次只「变更」了 changed.env。
        with open(os.path.join(temp_dir, "changed.env"), "w", encoding="utf-8") as fh:
            fh.write(f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_VALUE}\n")
        with open(os.path.join(temp_dir, "untouched.env"), "w", encoding="utf-8") as fh:
            fh.write(f"AWS_SECRET_ACCESS_KEY={AWS_SECRET_VALUE}\n")

        await detect_sensitive_files(str(repo.id), temp_dir, only_paths=["changed.env"])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    paths = {r.path for r in await _suggestions(repo.id)}
    assert "changed.env" in paths
    assert "untouched.env" not in paths, "增量检测不应扫描未变更文件（HI-01 范围约束）"


# ---------------------------------------------------------------------------
# sanity：run_in_background 接收无参 factory（非 coroutine 本体）
# ---------------------------------------------------------------------------


def test_run_in_background_accepts_factory_not_coroutine() -> None:
    from services import background_runner

    background_runner._reset_for_tests()
    try:
        called: list[int] = []

        async def _coro() -> int:
            called.append(1)
            return 42

        fut = run_in_background(lambda: _coro(), name="sanity-check")
        assert fut.result(timeout=10.0) == 42
        assert called == [1]
    finally:
        background_runner._reset_for_tests()
