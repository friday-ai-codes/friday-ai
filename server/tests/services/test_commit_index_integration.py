"""commit 历史索引 → 入库与代码 RAG 边界守护测试（IDX-01，per 25-04 PLAN）。

把 25-03 的 ``index_commits`` 挂接进索引流程后，验证 commit 文档落主 collection，
且**默认不进入代码 RAG 召回**（``BranchAwareSearchService`` 排除 ``kind=commit``——
提交摘要是自然语言，会系统性挤占源码召回窗口）。覆盖：

- dispatch：``_run_commit_index`` best-effort —— ``index_commits`` 抛异常不冒泡（仅 warning，
  绝不阻断索引 success，T-25-12）；正常路径在 rmtree 之前 await 完成（读真实克隆）。
- 代码 RAG：含特定 message 的 commit 索引后，经 ``search_rag`` **不**返回 kind=commit。
- 入库内容：commit 改动含被排除文件（.env / *.pem）+ 普通文件时，入库摘要含普通文件、
  **不含**被排除文件路径（fail-closed，T-25-13）。
- 增量：同 HEAD 第二次 ``index_commits`` 0 条；新增 commit 后只 +1（T-25-14）。

真实临时 git 仓库驱动 git log / diff-tree；mock embedding / sparse / qdrant upsert /
BranchAwareSearchService.search（避免真实模型与向量库）。mock search 模拟生产默认
排除 ``kind=commit``。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import commit_index
from services.commit_index import index_commits
from services.indexer import _is_shallow_clone, _run_commit_index, _unshallow_repo
from services.retrieval.rag_search import search_rag

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ============================================================================
# 临时 git 仓库 helper（复用 25-03 test_commit_index.py 范式）
# ============================================================================


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Grace Hopper",
        "GIT_AUTHOR_EMAIL": "grace@navy.example",
        "GIT_COMMITTER_NAME": "Grace Hopper",
        "GIT_COMMITTER_EMAIL": "grace@navy.example",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ.get("PATH", ""),
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


def _init_repo_at(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    return path


def _shallow_clone(source: Path, dest: Path) -> None:
    """用 file:// URI 做真实 ``--depth 1`` 浅克隆（本地路径克隆会忽略 --depth）。

    复刻生产 ``clone_and_index_repository`` 的浅克隆形态，使测试真正经过浅克隆路径，
    而非在全历史本地仓库上直接调 ``index_commits``（那会绕过 BL-01）。
    """
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", source.as_uri(), str(dest)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _index_ctxs(recorder: list[dict[str, Any]]):
    """patch index_commits 的重型外部依赖，把 upsert 的 points 收进 recorder。"""

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


async def _run_index(repository, repo: Path, points: list[dict[str, Any]]) -> dict:
    """跑 index_commits，捕获 upsert 的 commit point 进 points。"""
    ctxs = _index_ctxs(points)
    with ctxs[0], ctxs[1], ctxs[2]:
        return await index_commits(str(repository.id), str(repo))


def _patch_search(points: list[dict[str, Any]]):
    """模拟 search_rag 召回面：mock embedding/sparse + BranchAwareSearchService.search。

    生产路径默认排除 ``kind=commit``；本 mock 同步该契约——即使 point 内容命中
    query，也不把 commit 文档返回给 search_rag。
    """
    captured: dict[str, str] = {}

    async def _embed(query: str) -> list[float]:
        captured["q"] = query
        return [0.1, 0.2, 0.3]

    async def _search(repo_id: str, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        q = captured.get("q", "").lower()
        out: list[dict[str, Any]] = []
        for i, p in enumerate(points):
            payload = p["payload"]
            if payload.get("kind") == "commit":
                continue
            if q and q in str(payload.get("content", "")).lower():
                out.append({"id": p["id"], "score": 0.9 - i * 0.01, "payload": payload})
        return out

    return [
        patch(
            "services.embedding.EmbeddingService.generate_embedding",
            new=AsyncMock(side_effect=_embed),
        ),
        patch(
            "services.sparse_encoder.SparseEncoderService.encode",
            new=MagicMock(return_value={"indices": [1], "values": [1.0]}),
        ),
        patch(
            "services.branch_search.BranchAwareSearchService.search",
            new=AsyncMock(side_effect=_search),
        ),
    ]


async def _search_rag(repository, query: str, points: list[dict[str, Any]]):
    ctxs = _patch_search(points)
    with ctxs[0], ctxs[1], ctxs[2]:
        return await search_rag(query, repo_ids=[str(repository.id)])


# ============================================================================
# dispatch：_run_commit_index best-effort，失败不冒泡（T-25-12）
# ============================================================================


async def test_dispatch_swallows_index_commits_failure(repository) -> None:
    """index_commits 抛异常 → _run_commit_index 不冒泡（返回 None，仅 warning）。"""
    with patch.object(
        commit_index,
        "index_commits",
        new=AsyncMock(side_effect=RuntimeError("qdrant down")),
    ):
        result = await _run_commit_index(str(repository.id), "/tmp/does-not-matter")

    assert result is None


async def test_dispatch_invokes_index_commits_before_rmtree(repository, tmp_path) -> None:
    """正常路径：_run_commit_index await index_commits 完成（调用时克隆目录仍存在）。"""
    repo = _init_repo(tmp_path)
    _commit(repo, {"a.py": "1\n"}, "init")

    seen: dict[str, Any] = {}

    async def _fake_index(repository_id: str, repo_path: str) -> dict[str, Any]:
        seen["exists"] = os.path.isdir(repo_path)
        return {"indexed": 1, "head": "abc", "boundary_from": None}

    # _run_commit_index 内部 `from services.commit_index import index_commits`，
    # 故 patch commit_index.index_commits 才生效。
    with patch.object(commit_index, "index_commits", new=AsyncMock(side_effect=_fake_index)):
        await _run_commit_index(str(repository.id), str(repo))

    assert seen.get("exists") is True


# ============================================================================
# 代码 RAG：默认不召回 commit 文档
# ============================================================================


async def test_search_rag_excludes_commit_by_keyword(repository, tmp_path) -> None:
    """commit 已入库且 content 命中关键字，search_rag 仍不返回 kind=commit。"""
    repo = _init_repo(tmp_path)
    head = _commit(repo, {"src/auth.py": "x=1\n"}, "fix zorptastic login regression")

    points: list[dict[str, Any]] = []
    idx = await _run_index(repository, repo, points)
    assert idx["indexed"] == 1
    assert points[0]["payload"]["commit_sha"] == head
    assert "zorptastic" in points[0]["payload"]["content"]

    snap = await _search_rag(repository, "zorptastic", points)

    assert snap.status == "ok"
    assert [it for it in snap.items if it["payload"].get("kind") == "commit"] == []


async def test_search_rag_excludes_commit_by_author(repository, tmp_path) -> None:
    """author 写入 commit 文档内容后，search_rag 也不因 author 召回 commit。"""
    repo = _init_repo(tmp_path)
    _commit(repo, {"src/app.py": "x=1\n"}, "routine change")

    points: list[dict[str, Any]] = []
    await _run_index(repository, repo, points)
    assert points[0]["payload"]["author_name"] == "Grace Hopper"

    snap = await _search_rag(repository, "Grace Hopper", points)

    assert [it for it in snap.items if it["payload"].get("kind") == "commit"] == []


# ============================================================================
# 入库内容：被排除文件不出现在 commit 文档摘要（fail-closed，T-25-13）
# ============================================================================


async def test_indexed_commit_excludes_sensitive_files(repository, tmp_path) -> None:
    """入库的 commit 文档 changed_files / content 含普通文件、不含被排除文件。"""
    repo = _init_repo(tmp_path)
    _commit(
        repo,
        {
            "src/app.py": "x=1\n",
            ".env": "SECRET=topsecretvalue\n",
            "certs/server.pem": "PRIVATEKEY\n",
        },
        "add app and config",
    )

    points: list[dict[str, Any]] = []
    await _run_index(repository, repo, points)

    assert len(points) == 1
    payload = points[0]["payload"]
    assert payload.get("kind") == "commit"
    # 普通文件保留
    assert "src/app.py" in payload["changed_files"]
    assert "src/app.py" in payload["content"]
    # 被排除文件全程不泄漏（摘要 / changed_files / content / 密钥内容）
    assert ".env" not in payload["changed_files"]
    assert "certs/server.pem" not in payload["changed_files"]
    assert ".env" not in payload["content"]
    assert "server.pem" not in payload["content"]
    assert "topsecretvalue" not in payload["content"]


# ============================================================================
# 增量：二次同 HEAD 0 条，新增 commit 只 +1（T-25-14）
# ============================================================================


async def test_incremental_only_indexes_new_commits(repository, tmp_path) -> None:
    """全量后二次同 HEAD 增量 0 条；新增 commit 后只 +1，且仍不进代码 RAG。"""
    repo = _init_repo(tmp_path)
    _commit(repo, {"a.py": "1\n"}, "first frobnicate")
    head1 = _commit(repo, {"b.py": "2\n"}, "second change")

    points1: list[dict[str, Any]] = []
    r1 = await _run_index(repository, repo, points1)
    assert r1["indexed"] == 2
    assert r1["head"] == head1

    # 二次同 HEAD：boundary..HEAD 空 → 0 条、不再 upsert
    points2: list[dict[str, Any]] = []
    r2 = await _run_index(repository, repo, points2)
    assert r2["indexed"] == 0
    assert points2 == []

    # 新增 commit → 只索引新增 1 条
    head3 = _commit(repo, {"c.py": "3\n"}, "third wibblesnew commit")
    points3: list[dict[str, Any]] = []
    r3 = await _run_index(repository, repo, points3)
    assert r3["indexed"] == 1
    assert points3[0]["payload"]["commit_sha"] == head3

    snap = await _search_rag(repository, "wibblesnew", points3)
    assert [it for it in snap.items if it["payload"].get("kind") == "commit"] == []


# ============================================================================
# BL-01：commit 历史索引必须经真实 `--depth 1` 浅克隆路径（unshallow 后才见全历史）
# ============================================================================


async def test_shallow_clone_without_unshallow_only_indexes_head(repository, tmp_path) -> None:
    """复现 BL-01 根因：在真实浅克隆上直接索引只能看到 HEAD 一个 commit。

    这是先前集成测试的盲点——它直接对全历史本地仓库调 index_commits，绕过浅克隆给出虚假信心。
    本用例用 file:// 真实浅克隆，证明不补齐历史时历史 commit 全部丢失。
    """
    source = _init_repo_at(tmp_path / "source")
    _commit(source, {"a.py": "1\n"}, "first alphacommit")
    _commit(source, {"b.py": "2\n"}, "second betacommit")
    head = _commit(source, {"c.py": "3\n"}, "third gammacommit")

    dest = tmp_path / "shallow"
    _shallow_clone(source, dest)
    assert await _is_shallow_clone(str(dest)) is True

    points: list[dict[str, Any]] = []
    result = await _run_index(repository, dest, points)

    # 浅克隆 git log 仅见 HEAD → 只索引 1 个 commit，历史 commit 丢失（BL-01）
    assert result["indexed"] == 1
    assert {p["payload"]["commit_sha"] for p in points} == {head}


async def test_shallow_clone_unshallow_indexes_full_history(repository, tmp_path) -> None:
    """BL-01 修复：浅克隆经 `_unshallow_repo` 补齐历史后，commit 历史索引覆盖全部 commit。"""
    source = _init_repo_at(tmp_path / "source")
    h1 = _commit(source, {"a.py": "1\n"}, "first alphacommit")
    h2 = _commit(source, {"b.py": "2\n"}, "second betacommit")
    h3 = _commit(source, {"c.py": "3\n"}, "third gammacommit")

    dest = tmp_path / "shallow"
    _shallow_clone(source, dest)
    assert await _is_shallow_clone(str(dest)) is True

    # 修复动作：commit 索引前补齐完整历史（生产路径在 _run_commit_index 之前执行同样动作）
    ok = await _unshallow_repo(str(dest))
    assert ok is True
    assert await _is_shallow_clone(str(dest)) is False

    points: list[dict[str, Any]] = []
    result = await _run_index(repository, dest, points)

    # 全历史可见 → 三个 commit 全部索引，无中段丢失
    assert result["indexed"] == 3
    assert {p["payload"]["commit_sha"] for p in points} == {h1, h2, h3}

    # 历史 commit 已入库（按 message 关键字可定位），但不进代码 RAG
    hist = [p for p in points if "alphacommit" in p["payload"].get("content", "")]
    assert len(hist) == 1
    assert hist[0]["payload"]["commit_sha"] == h1
    snap = await _search_rag(repository, "alphacommit", points)
    assert [it for it in snap.items if it["payload"].get("kind") == "commit"] == []
