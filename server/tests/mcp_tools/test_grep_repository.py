"""grep_repository / get_repository_file 镜像路径的端到端测试。

用 tmp_path 下的本地 git 仓库做 origin（file:// 协议，零网络），
验证：精确全量检索（ripgrep / git grep 双引擎同结果）、正则 / 大小写 /
glob 过滤、输出模式（content / files_only / count）、token 预算与截断、
跨仓分组、镜像读文件、分支名校验与镜像禁用时的行为。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from rest_framework.test import APIClient

from repositories.models import IndexStatus, Repository
from services.repo_mirror import reset_mirror_state

pytestmark = pytest.mark.django_db


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _single_repo_entry(body: dict[str, Any]) -> dict[str, Any]:
    assert len(body["repositories"]) == 1
    return body["repositories"][0]


@pytest.fixture
def origin_repo(tmp_path: Path) -> tuple[Path, str]:
    """本地 origin：3 个文件、若干 browserJump 跳转点 + 一个批量匹配文件。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    _git("config", "user.email", "test@friday.local", cwd=origin)
    _git("config", "user.name", "Friday Test", cwd=origin)

    (origin / "apps" / "home").mkdir(parents=True)
    (origin / "apps" / "tab").mkdir(parents=True)
    (origin / "apps" / "home" / "index.ts").write_text(
        "export function goProblem() {\n  browserJump('/problem-app/scene1?id=1')\n}\n",
        encoding="utf-8",
    )
    (origin / "apps" / "tab" / "jump.ts").write_text(
        "const a = browserJump('/problem-app/scene2?from=tab')\n"
        "const b = browserJump('/problem-app/scene3')\n"
        "const other = BROWSERJUMP_PLACEHOLDER\n",
        encoding="utf-8",
    )
    (origin / "bulk.txt").write_text(
        "".join(f"BULKMATCH line {i} {'x' * 60}\n" for i in range(100)),
        encoding="utf-8",
    )
    (origin / "README.md").write_text("study app demo\n", encoding="utf-8")
    _git("add", "-A", cwd=origin)
    _git("commit", "-m", "init", cwd=origin)
    sha = _git("rev-parse", "HEAD", cwd=origin)
    return origin, sha


@pytest.fixture
def mirror_repository(
    settings: Any,
    tmp_path: Path,
    indexed_repository: Any,
    origin_repo: tuple[Path, str],
) -> tuple[Any, str]:
    """启用镜像并把 fixture 仓库指向本地 origin。"""
    origin, sha = origin_repo
    settings.REPO_MIRROR_ENABLED = True
    settings.REPO_CLONE_DIR = tmp_path / "mirrors"
    indexed_repository.git_url = f"file://{origin}"
    indexed_repository.default_branch = "main"
    indexed_repository.last_indexed_commit_sha = sha
    indexed_repository.save(update_fields=["git_url", "default_branch", "last_indexed_commit_sha"])
    reset_mirror_state()
    yield indexed_repository, sha
    reset_mirror_state()


@pytest.fixture(params=["ripgrep", "git-grep"])
def grep_engine(request: Any, settings: Any) -> str:
    """双引擎参数化：同一断言两个引擎都必须通过（结果一致性）。"""
    if request.param == "ripgrep" and shutil.which("rg") is None:
        pytest.skip("ripgrep 未安装")
    settings.REPO_MIRROR_USE_RIPGREP = request.param == "ripgrep"
    return request.param


def test_grep_finds_all_occurrences_pinned_to_index(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(repo.id), "pattern": "/problem-app/"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output_mode"] == "content"
    assert body["total_matches"] == 3
    assert body["truncated"] is False
    entry = _single_repo_entry(body)
    assert entry["commit_sha"] == sha
    assert entry["matches_index"] is True
    assert entry["engine"] == grep_engine
    assert entry["total_matches"] == 3
    assert entry["files_with_matches"] == 2
    locations = {(m["file_path"], m["line"]) for m in entry["matches"]}
    assert locations == {
        ("apps/home/index.ts", 2),
        ("apps/tab/jump.ts", 1),
        ("apps/tab/jump.ts", 2),
    }
    assert all(m["kind"] == "match" for m in entry["matches"])


def test_grep_regex_and_case_insensitive(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "browserjump\\('/problem-app/scene[0-9]",
            "regex": True,
            "case_sensitive": False,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["total_matches"] == 3


def test_grep_glob_filters_and_truncation(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "/problem-app/",
            "exclude_globs": ["apps/home/**"],
            "max_matches": 1,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    entry = _single_repo_entry(body)
    # total_matches 是真实全量计数（2 处都在 jump.ts），matches 被 max_matches 截到 1
    assert entry["total_matches"] == 2
    assert entry["truncated"] is True
    assert len([m for m in entry["matches"] if m["kind"] == "match"]) == 1
    assert entry["matches"][0]["file_path"] == "apps/tab/jump.ts"


def test_grep_paths_filter_with_context(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "scene1",
            "paths": ["apps/home"],
            "context_lines": 1,
        },
        format="json",
    )

    assert response.status_code == 200
    entry = _single_repo_entry(response.json())
    assert entry["total_matches"] == 1
    kinds = {m["kind"] for m in entry["matches"]}
    assert kinds == {"match", "context"}
    assert {m["file_path"] for m in entry["matches"]} == {"apps/home/index.ts"}


def test_grep_output_mode_files_only(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "/problem-app/",
            "output_mode": "files_only",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["output_mode"] == "files_only"
    entry = _single_repo_entry(body)
    assert "matches" not in entry
    assert entry["files"] == [
        {"file_path": "apps/home/index.ts", "match_count": 1},
        {"file_path": "apps/tab/jump.ts", "match_count": 2},
    ]


def test_grep_output_mode_count(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "/problem-app/",
            "output_mode": "count",
        },
        format="json",
    )

    assert response.status_code == 200
    entry = _single_repo_entry(response.json())
    assert "matches" not in entry
    assert "files" not in entry
    assert entry["total_matches"] == 3
    assert entry["files_with_matches"] == 2


def test_grep_max_tokens_budget_truncates_content(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    grep_engine: str,
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "BULKMATCH",
            "max_matches": 500,
            "max_tokens": 256,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    entry = _single_repo_entry(body)
    assert entry["total_matches"] == 100  # 真实全量计数不受预算影响
    assert entry["truncated"] is True
    assert body["truncated"] is True
    assert 0 < len(entry["matches"]) < 100


def test_grep_multi_repo_grouped_results(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
    settings: Any,
    grep_engine: str,
) -> None:
    """跨仓显式 opt-in：repository_ids 多仓时按仓库分组返回，总数为求和。"""
    client, _ = mcp_client
    repo, sha = mirror_repository
    second = Repository.objects.create(
        name="Second Repo",
        git_url=repo.git_url,
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        last_indexed_commit_sha=sha,
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_ids": [str(repo.id), str(second.id)],
            "pattern": "/problem-app/",
            "output_mode": "files_only",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_matches"] == 6
    assert [entry["repository_id"] for entry in body["repositories"]] == [
        str(repo.id),
        str(second.id),
    ]
    assert all(entry["total_matches"] == 3 for entry in body["repositories"])


def test_grep_multi_repo_branch_param_rejected(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_ids": [str(repo.id), "00000000-0000-0000-0000-000000000001"],
            "pattern": "x",
            "branch": "main",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_grep_requires_target_scope(
    mcp_client: tuple[APIClient, str],
) -> None:
    client, _ = mcp_client

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"pattern": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_grep_rejects_illegal_branch(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {
            "repository_id": str(repo.id),
            "pattern": "x",
            "branch": "--upload-pack=evil",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_grep_mirror_disabled_returns_error(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
) -> None:
    """autouse fixture 默认禁用镜像 → 单仓 grep 直接报 mirror_disabled。"""
    client, _ = mcp_client

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "mirror_disabled"


def test_get_repository_file_reads_full_content_from_mirror(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
) -> None:
    client, _ = mcp_client
    repo, sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(repo.id), "file_path": "apps/tab/jump.ts"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "git"
    assert body["commit_sha"] == sha
    assert body["total_lines"] == 3
    assert "scene2" in body["content"]
    assert "BROWSERJUMP_PLACEHOLDER" in body["content"]
    assert body["truncated"] is False


def test_get_repository_file_mirror_suffix_resolution_and_slicing(
    mcp_client: tuple[APIClient, str],
    mirror_repository: tuple[Any, str],
) -> None:
    client, _ = mcp_client
    repo, _sha = mirror_repository

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {
            "repository_id": str(repo.id),
            "file_path": "tab/jump.ts",
            "start_line": 2,
            "end_line": 3,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["file_path"] == "apps/tab/jump.ts"
    assert body["requested_file_path"] == "tab/jump.ts"
    assert body["returned_lines"] == 2
    assert body["content"].splitlines()[0].startswith("const b")
