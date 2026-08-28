"""Phase 145 双宿主 session Capture hook 的真实子进程 fixtures。"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_HOOKS = REPO_ROOT / "skills" / "hooks"
FAKE_TOKEN = "friday-test-pat-never-print"
FAKE_BASE_URL = "http://127.0.0.1:9"


@pytest.fixture
def hook_paths() -> dict[str, Path]:
    return {
        "claude_prompt": SKILLS_HOOKS / "user-prompt-submit",
        "claude_stop": SKILLS_HOOKS / "stop",
        "cursor_before": SKILLS_HOOKS / "cursor" / "before-submit-prompt",
        "cursor_after": SKILLS_HOOKS / "cursor" / "after-agent-response",
    }


@pytest.fixture
def git_workspaces(tmp_path: Path) -> dict[str, Path]:
    def initialize(name: str, *, dirty: bool) -> Path:
        workspace = tmp_path / name
        workspace.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "config", "user.email", "hooks@example.invalid"], cwd=workspace, check=True
        )
        subprocess.run(["git", "config", "user.name", "Hook Tests"], cwd=workspace, check=True)
        tracked = workspace / "tracked.txt"
        tracked.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=workspace, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=workspace, check=True)
        if dirty:
            tracked.write_text("base\ndirty\n", encoding="utf-8")
        return workspace

    no_git = tmp_path / "no-git"
    no_git.mkdir()
    return {
        "clean": initialize("clean", dirty=False),
        "dirty": initialize("dirty", dirty=True),
        "no_git": no_git,
    }


@pytest.fixture
def http_record(tmp_path: Path) -> Path:
    return tmp_path / "capture-http.jsonl"


@pytest.fixture
def run_hook(
    tmp_path: Path,
    http_record: Path,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    cache_home = tmp_path / "cache"
    home = tmp_path / "home"
    home.mkdir()

    def run(
        script_path: Path,
        event: dict[str, Any],
        *,
        cwd: Path,
        extra_env: dict[str, str | None] | None = None,
        record_http: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "XDG_CACHE_HOME": str(cache_home),
                "FRIDAY_BASE_URL": FAKE_BASE_URL,
                "FRIDAY_ACCESS_TOKEN": FAKE_TOKEN,
            }
        )
        if record_http:
            env["FRIDAY_CAPTURE_HTTP_RECORD"] = str(http_record)
        for key, value in (extra_env or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["bash", str(script_path)],
            input=json.dumps(event),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

    return run


@pytest.fixture
def read_http_records(http_record: Path) -> Callable[[], list[dict[str, Any]]]:
    def read() -> list[dict[str, Any]]:
        if not http_record.exists():
            return []
        return [
            json.loads(line)
            for line in http_record.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    return read


@pytest.fixture
def pending_files(tmp_path: Path) -> Callable[[], list[Path]]:
    def files() -> list[Path]:
        pair_dir = tmp_path / "cache" / "friday-skills" / "pairs"
        return sorted(pair_dir.glob("pending-*.json")) if pair_dir.exists() else []

    return files
