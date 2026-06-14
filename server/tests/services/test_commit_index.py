"""`index_commits` commit 历史摄取守护测试（IDX-01，per 25-03 PLAN Task 2）。

用真实临时 git 仓库驱动 git log / diff-tree 解析与增量边界逻辑，仅 mock embedding /
Qdrant upsert / hybrid 判定（避免外部服务）。覆盖：
- commit 文档构建含 message + author + 变更文件摘要，payload kind=commit。
- 被排除文件（.env / *.pem）不出现在变更摘要（fail-closed，T-25-08）。
- 增量：boundary..HEAD 只取新 commit；二次同 HEAD 索引 0 条、不再 upsert（T-25-09）。
- 确定性 uuid5 point id（同 repo+sha 不重复，T-25-10）。
- 大变更摘要经 truncate_diff_lines 截断。
- upsert 失败不推进边界（绝不丢 commit）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import commit_index
from services.commit_index import _commit_point_id, index_commits

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def _git(repo: Path, *args: str) -> str:
    """在临时仓库执行 git 命令（带固定 author/committer 身份）。"""
    env = {
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _patch_externals(recorder: list):
    """patch embedding / hybrid / qdrant upsert，把 upsert 的 points 收进 recorder。返回上下文管理器组。"""

    def _capture(repository_id, points):  # noqa: ARG001
        recorder.extend(points)
        return True

    return [
        patch.object(
            commit_index.EmbeddingService,
            "generate_embeddings_batch",
            new=AsyncMock(side_effect=lambda texts, **kw: [[0.1, 0.2, 0.3, 0.4] for _ in texts]),
        ),
        patch.object(commit_index, "_collection_is_hybrid", new=AsyncMock(return_value=False)),
        patch.object(
            commit_index.QdrantService,
            "upsert_vectors",
            new=MagicMock(side_effect=_capture),
        ),
    ]


async def _boundary(repository) -> str | None:
    from repositories.models import Repository

    return (
        await Repository.objects.filter(id=repository.id)
        .values_list("commit_index_boundary_sha", flat=True)
        .afirst()
    )


async def _run(repository, repo: Path, points: list) -> dict:
    ctxs = _patch_externals(points)
    with ctxs[0], ctxs[1], ctxs[2]:
        return await index_commits(str(repository.id), str(repo))


async def test_commit_doc_built(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    head = _commit(repo, {"src/app.py": "print('hi')\n"}, "FIX login bug in auth")

    points: list = []
    result = await _run(repository, repo, points)

    assert result["indexed"] == 1
    assert result["head"] == head
    payload = points[0]["payload"]
    assert payload["kind"] == "commit"
    assert payload["commit_sha"] == head
    assert payload["author_name"] == "Test Author"
    assert payload["author_email"] == "author@example.com"
    assert payload["committed_at"]
    assert payload["file_path"] == f".friday/commits/{head}"
    assert payload["chunk_index"] == 0
    assert "src/app.py" in payload["changed_files"]
    # 文档内容含 message + author + 变更文件路径
    assert "FIX login bug in auth" in payload["content"]
    assert "author@example.com" in payload["content"]
    assert "src/app.py" in payload["content"]
    # 边界推进到 HEAD
    assert await _boundary(repository) == head


async def test_excluded_file_not_in_summary(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        {"src/app.py": "x=1\n", ".env": "SECRET=topsecret\n", "certs/server.pem": "KEY\n"},
        "add config",
    )

    points: list = []
    result = await _run(repository, repo, points)

    assert result["indexed"] == 1
    payload = points[0]["payload"]
    # 被排除文件不入摘要 / changed_files / content（fail-closed，T-25-08）
    assert ".env" not in payload["changed_files"]
    assert "certs/server.pem" not in payload["changed_files"]
    assert ".env" not in payload["content"]
    assert "server.pem" not in payload["content"]
    assert "SECRET" not in payload["content"]
    assert "topsecret" not in payload["content"]
    # 未被排除文件仍在
    assert "src/app.py" in payload["changed_files"]


async def test_incremental_only_new_commits(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, {"a.py": "1\n"}, "first")
    head1 = _commit(repo, {"b.py": "2\n"}, "second")

    points1: list = []
    r1 = await _run(repository, repo, points1)
    assert r1["indexed"] == 2
    assert await _boundary(repository) == head1

    # 二次同 HEAD：boundary..HEAD 空 → 0 条、不再 upsert
    points2: list = []
    r2 = await _run(repository, repo, points2)
    assert r2["indexed"] == 0
    assert points2 == []
    assert await _boundary(repository) == head1

    # 新增 commit → 只索引新增 1 条
    head2 = _commit(repo, {"c.py": "3\n"}, "third")
    points3: list = []
    r3 = await _run(repository, repo, points3)
    assert r3["indexed"] == 1
    assert points3[0]["payload"]["commit_sha"] == head2
    assert await _boundary(repository) == head2


async def test_deterministic_point_id_dedup(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    head = _commit(repo, {"a.py": "1\n"}, "only")

    points1: list = []
    await _run(repository, repo, points1)
    first_id = points1[0]["id"]

    # 重置边界后重索引同一 commit → 命中同一确定性 point id（不产生重复 point）
    from repositories.models import Repository

    await Repository.objects.filter(id=repository.id).aupdate(commit_index_boundary_sha=None)
    points2: list = []
    await _run(repository, repo, points2)

    assert points2[0]["id"] == first_id
    assert first_id == _commit_point_id(str(repository.id), head)


async def test_large_summary_truncated(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    files = {
        f"dir/file_{i}.py": f"v{i}\n"
        for i in range(commit_index.COMMIT_INDEX_MAX_SUMMARY_LINES + 50)
    }
    _commit(repo, files, "huge commit")

    points: list = []
    result = await _run(repository, repo, points)

    assert result["indexed"] == 1
    content = points[0]["payload"]["content"]
    assert "[diff truncated]" in content


async def test_upsert_failure_keeps_boundary(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)
    _commit(repo, {"a.py": "1\n"}, "only")

    ctxs = [
        patch.object(
            commit_index.EmbeddingService,
            "generate_embeddings_batch",
            new=AsyncMock(side_effect=lambda texts, **kw: [[0.1, 0.2] for _ in texts]),
        ),
        patch.object(commit_index, "_collection_is_hybrid", new=AsyncMock(return_value=False)),
        patch.object(
            commit_index.QdrantService,
            "upsert_vectors",
            new=MagicMock(return_value=False),
        ),
    ]
    with ctxs[0], ctxs[1], ctxs[2]:
        result = await index_commits(str(repository.id), str(repo))

    assert result["indexed"] == 0
    # upsert 失败绝不推进边界（下次重试）
    assert await _boundary(repository) is None


async def test_empty_repo_returns_zero(repository, tmp_path) -> None:
    repo = _init_repo(tmp_path)  # 无任何 commit

    points: list = []
    result = await _run(repository, repo, points)

    assert result["indexed"] == 0
    assert result["head"] is None
    assert points == []
