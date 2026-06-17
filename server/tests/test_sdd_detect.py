"""SDD 仓库检测器守护测试（Phase 48 Plan 01，SDD-01）。

覆盖（CONTEXT D-48-2/D-48-3，best-effort 不变量 D-48-1）：
- 含 ``openspec/`` 目录 → 写 ``facets["methodology"]="SDD"``（asave 被调用，返回 True）。
- 不含 ``openspec/`` 且 methodology 为自动写入的 "SDD" → 清除键（防漂移，返回 True）。
- 不含 ``openspec/`` 且 methodology 为他值 → 不动、不 save（返回 False）。
- ``_pinned`` 含 methodology → 尊重人工 pin，跳过（返回 False）。
- 已为 "SDD" → 幂等 no-op，不 save、updated_at 不漂移（返回 False）。
- Repository 不存在 → 直接返回 False，不抛。
- ``openspec`` 为普通文件而非目录 → 视为不存在，不打标。
- 挂接 fail-safe：``_run_sdd_detect`` 吞检测异常为 warning，绝不阻断索引 success。
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from asgiref.sync import sync_to_async

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo(facets: dict[str, Any] | None = None) -> Any:
    from repositories.models import Repository

    return await sync_to_async(Repository.objects.create)(
        name="SDD Detect Repo",
        git_url="https://example.com/sdd/repo.git",
        git_platform="github",
        default_branch="main",
        facets=facets or {},
    )


async def _refresh(repo_id: Any) -> Any:
    from repositories.models import Repository

    return await Repository.objects.aget(id=repo_id)


def _mkdir_openspec(root: Any) -> str:
    os.makedirs(os.path.join(str(root), "openspec"), exist_ok=True)
    return str(root)


# ---------------------------------------------------------------------------
# 检测器行为
# ---------------------------------------------------------------------------


async def test_openspec_present_tags_sdd(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo()
    repo_path = _mkdir_openspec(tmp_path)

    changed = await detect_and_tag_sdd(str(repo.id), repo_path)

    assert changed is True
    refreshed = await _refresh(repo.id)
    assert refreshed.facets.get("methodology") == "SDD"


async def test_openspec_absent_clears_auto_sdd_tag(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo({"methodology": "SDD"})

    changed = await detect_and_tag_sdd(str(repo.id), str(tmp_path))

    assert changed is True
    refreshed = await _refresh(repo.id)
    assert "methodology" not in refreshed.facets


async def test_openspec_absent_keeps_other_methodology_value(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo({"methodology": "自研流程"})

    changed = await detect_and_tag_sdd(str(repo.id), str(tmp_path))

    assert changed is False
    refreshed = await _refresh(repo.id)
    assert refreshed.facets.get("methodology") == "自研流程"


async def test_pinned_methodology_skips_detection(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo({"methodology": "自研流程", "_pinned": ["methodology"]})
    repo_path = _mkdir_openspec(tmp_path)

    changed = await detect_and_tag_sdd(str(repo.id), repo_path)

    assert changed is False
    refreshed = await _refresh(repo.id)
    # 人工 pin 值不被自动检测覆盖。
    assert refreshed.facets.get("methodology") == "自研流程"


async def test_idempotent_no_save_when_already_sdd(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo()
    repo_path = _mkdir_openspec(tmp_path)

    first = await detect_and_tag_sdd(str(repo.id), repo_path)
    assert first is True
    after_first = await _refresh(repo.id)
    first_updated_at = after_first.updated_at

    # 二次检测：facets 未变 → 不 save、updated_at 不漂移。
    second = await detect_and_tag_sdd(str(repo.id), repo_path)
    assert second is False
    after_second = await _refresh(repo.id)
    assert after_second.updated_at == first_updated_at


async def test_missing_repository_returns_false(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo_path = _mkdir_openspec(tmp_path)

    changed = await detect_and_tag_sdd("00000000-0000-0000-0000-000000000000", repo_path)

    assert changed is False


async def test_openspec_as_file_is_not_tagged(tmp_path: Any) -> None:
    from services.sdd_detect import detect_and_tag_sdd

    repo = await _make_repo()
    # openspec 是普通文件而非目录 → os.path.isdir 为假 → 不打标。
    (tmp_path / "openspec").write_text("not a dir", encoding="utf-8")

    changed = await detect_and_tag_sdd(str(repo.id), str(tmp_path))

    assert changed is False
    refreshed = await _refresh(repo.id)
    assert "methodology" not in refreshed.facets


# ---------------------------------------------------------------------------
# 挂接 fail-safe：检测异常不阻断索引 success（D-48-1，best-effort 不变量）
# ---------------------------------------------------------------------------


def test_dispatch_hook_runs_before_rmtree_in_clone_and_index() -> None:
    """``_run_sdd_detect`` 必须在 ``shutil.rmtree(temp_dir)`` 之前被 await（探测真实目录）。"""
    import inspect

    from services.indexer import clone_and_index_repository

    src = inspect.getsource(clone_and_index_repository)
    detect_idx = src.find("_run_sdd_detect(repository_id, temp_dir)")
    rmtree_idx = src.find("shutil.rmtree(temp_dir")

    assert detect_idx >= 0, "clone_and_index_repository 缺少 _run_sdd_detect 触发"
    assert rmtree_idx >= 0, "clone_and_index_repository 缺少 shutil.rmtree(temp_dir)"
    assert detect_idx < rmtree_idx, "SDD 检测必须在 rmtree(temp_dir) 之前触发（否则探测已删除目录）"
    assert "await _run_sdd_detect(" in src, "_run_sdd_detect 必须被 await（不能 fire-and-forget）"


async def test_dispatch_swallows_detector_exception(monkeypatch: Any) -> None:
    """检测内部抛异常时，``_run_sdd_detect`` 不冒泡（best-effort，绝不阻断索引 success）。"""
    from services import indexer

    async def _boom(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("sdd detector exploded")

    monkeypatch.setattr("services.sdd_detect.detect_and_tag_sdd", _boom, raising=True)

    # 不抛即通过（异常被 helper 内 try/except 吞掉并记 sdd_detect_dispatch_failed warning）。
    await indexer._run_sdd_detect("rid", "/tmp/does-not-matter")
