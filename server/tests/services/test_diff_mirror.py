"""``services.repo_mirror.diff_mirror`` / ``ensure_mirror_sha``（DIFF-02）。

优先临时 bare/worktree repo + 直接调 helper；``ensure_mirror_sha`` 用
monkeypatch 绕过 ORM 取参，仍走真实 ``git fetch`` pin 路径。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from services.repo_mirror import (
    DETECT_CHANGES_MAX_DIFF_BYTES,
    DiffMirrorResult,
    MirrorError,
    MirrorSnapshot,
    diff_mirror,
    ensure_mirror_sha,
    reset_mirror_state,
)


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "test@friday.local", cwd=path)
    _git("config", "user.name", "Friday Test", cwd=path)


@pytest.fixture(autouse=True)
def _clear_mirror_state() -> Any:
    reset_mirror_state()
    yield
    reset_mirror_state()


@pytest.mark.asyncio
async def test_diff_mirror_uses_find_renames(monkeypatch: pytest.MonkeyPatch) -> None:
    """diff argv 含 ``--find-renames`` 与 ``--unified=0``（D-06）。"""
    captured: dict[str, Any] = {}

    async def _fake_run_git(
        args: list[str],
        *,
        cwd: Path | None = None,
        proxy_url: str | None = None,
        timeout: float = 300.0,
        max_output_bytes: int | None = None,
    ) -> tuple[int, bytes, bytes]:
        captured["args"] = list(args)
        captured["max_output_bytes"] = max_output_bytes
        return 0, b"", b""

    monkeypatch.setattr("services.repo_mirror._run_git", _fake_run_git)
    base_sha = "a" * 40
    head_sha = "b" * 40
    repo_dir = Path("/tmp/mirror-fixture")
    base = MirrorSnapshot("repo-1", repo_dir, base_sha, "main", True)
    head = MirrorSnapshot("repo-1", repo_dir, head_sha, "feat", False)

    result = await diff_mirror(base, head)

    assert isinstance(result, DiffMirrorResult)
    assert captured["args"][:3] == ["diff", "--unified=0", "--find-renames"]
    assert captured["args"][3] == base_sha
    assert captured["args"][4] == head_sha
    assert captured["max_output_bytes"] == DETECT_CHANGES_MAX_DIFF_BYTES


@pytest.mark.asyncio
async def test_diff_mirror_two_dot_not_three_dot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """diff 使用两-dot 区间；argv 不得出现三-dot ``...``（D-01）。"""
    captured: dict[str, Any] = {}

    async def _fake_run_git(
        args: list[str],
        **_kwargs: Any,
    ) -> tuple[int, bytes, bytes]:
        captured["args"] = list(args)
        return 0, b"", b""

    monkeypatch.setattr("services.repo_mirror._run_git", _fake_run_git)
    base_sha = "c" * 40
    head_sha = "d" * 40
    repo_dir = Path("/tmp/mirror-fixture")
    await diff_mirror(
        MirrorSnapshot("repo-1", repo_dir, base_sha, "main", True),
        MirrorSnapshot("repo-1", repo_dir, head_sha, "feat", False),
    )

    joined = " ".join(captured["args"])
    assert "..." not in joined
    assert base_sha in captured["args"]
    assert head_sha in captured["args"]


@pytest.mark.asyncio
async def test_diff_mirror_rename_detected(tmp_path: Path) -> None:
    """纯 rename commit → unified 含 rename 头（DIFF-02）。"""
    repo = tmp_path / "rename-repo"
    _init_repo(repo)
    (repo / "old_name.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _git("add", "old_name.py", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)
    base_sha = _git("rev-parse", "HEAD", cwd=repo)

    _git("mv", "old_name.py", "new_name.py", cwd=repo)
    _git("commit", "-m", "rename", cwd=repo)
    head_sha = _git("rev-parse", "HEAD", cwd=repo)

    result = await diff_mirror(
        MirrorSnapshot("repo-1", repo, base_sha, "main", True),
        MirrorSnapshot("repo-1", repo, head_sha, "feat", False),
    )

    assert result.unified_diff
    lower = result.unified_diff.lower()
    assert "rename from" in lower or "similarity index" in lower
    assert "old_name.py" in result.unified_diff
    assert "new_name.py" in result.unified_diff


@pytest.mark.asyncio
async def test_ensure_mirror_sha_pins_object(
    tmp_path: Path,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """40 位 sha 可 fetch；不走 ``refs/heads/{sha}``（D-01）。"""
    origin = tmp_path / "origin"
    _init_repo(origin)
    (origin / "a.txt").write_text("hello\n", encoding="utf-8")
    _git("add", "a.txt", cwd=origin)
    _git("commit", "-m", "init", cwd=origin)
    sha = _git("rev-parse", "HEAD", cwd=origin)

    settings.REPO_MIRROR_ENABLED = True
    settings.REPO_CLONE_DIR = tmp_path / "mirrors"

    async def _fake_params(_repository_id: str) -> dict[str, Any]:
        return {
            "git_url": f"file://{origin}",
            "proxy_url": None,
            "token": None,
            "default_branch": "main",
            "base_branch": "main",
            "last_indexed_commit_sha": sha,
        }

    monkeypatch.setattr(
        "services.repo_mirror._fetch_repo_params",
        AsyncMock(side_effect=_fake_params),
    )

    captured_fetches: list[list[str]] = []
    real_run_git = __import__(
        "services.repo_mirror", fromlist=["_run_git"]
    )._run_git

    async def _wrap_run_git(args: list[str], **kwargs: Any) -> tuple[int, bytes, bytes]:
        if args and args[0] == "fetch":
            captured_fetches.append(list(args))
        return await real_run_git(args, **kwargs)

    monkeypatch.setattr("services.repo_mirror._run_git", _wrap_run_git)

    snap = await ensure_mirror_sha("repo-pin-1", sha)
    assert snap.commit_sha == sha
    assert snap.repository_id == "repo-pin-1"
    assert snap.matches_index is True

    assert captured_fetches, "应至少发起一次 sha pin fetch"
    fetch_argv = " ".join(captured_fetches[0])
    assert f"+{sha}:refs/friday/pin-" in fetch_argv
    assert f"refs/heads/{sha}" not in fetch_argv

    with pytest.raises(MirrorError) as exc_info:
        await ensure_mirror_sha("repo-pin-1", "not-a-valid-sha")
    assert exc_info.value.code == "invalid_params"


@pytest.mark.asyncio
async def test_diff_mirror_output_byte_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超 DETECT_CHANGES_MAX_DIFF_BYTES → MirrorError（T-123-DOS）。"""

    async def _fake_run_git(
        args: list[str],
        **kwargs: Any,
    ) -> tuple[int, bytes, bytes]:
        cap = kwargs.get("max_output_bytes") or DETECT_CHANGES_MAX_DIFF_BYTES
        return 0, b"x" * int(cap), b""

    monkeypatch.setattr("services.repo_mirror._run_git", _fake_run_git)
    repo_dir = Path("/tmp/mirror-fixture")
    with pytest.raises(MirrorError) as exc_info:
        await diff_mirror(
            MirrorSnapshot("repo-1", repo_dir, "e" * 40, "main", True),
            MirrorSnapshot("repo-1", repo_dir, "f" * 40, "feat", False),
        )
    assert exc_info.value.code in {"mirror_fetch_failed", "diff_too_large"}
