"""索引扫描面排除守护测试（Phase 22 Plan 02，fail-closed，EXCL-02）。

覆盖两块：
- ``scan_directory`` 新增可选相对路径排除回调（PF-04 修正后），向后兼容 + 命中跳过
  + 判定异常 fail-closed。
- ``indexer.run_full_index`` / ``run_incremental_index`` 经 ``build_matcher_for_repo``
  把被排除文件挡在 ``files_to_process`` / diff 之外（含 builtin 开箱即用与 per-repo 规则）。
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.code_parser import CodeChunk, scan_directory


def test_scan_directory_backward_compatible_without_callback(tmp_path) -> None:
    """不传排除回调时，输出与改动前一致（仅扩展名白名单过滤）。"""
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "note.md").write_text("# hi\n")
    (tmp_path / "data.bin").write_text("not a source file\n")  # 未知扩展名

    result = scan_directory(str(tmp_path))
    rel = {os.path.relpath(p, str(tmp_path)).replace(os.sep, "/") for p in result}

    assert rel == {"app.py", "note.md"}


def test_scan_directory_excludes_via_callback(tmp_path) -> None:
    """命中 ``.env`` / ``secrets/`` 的回调时，对应文件不出现在返回列表。"""
    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "leak.py").write_text("token = 1\n")

    def excl(rel: str) -> bool:
        return rel == ".env" or rel == "secrets" or rel.startswith("secrets/")

    result = scan_directory(str(tmp_path), is_excluded_rel=excl)
    rel = {os.path.relpath(p, str(tmp_path)).replace(os.sep, "/") for p in result}

    assert rel == {"app.py"}
    assert "secrets/leak.py" not in rel


def test_scan_directory_failclosed_on_callback_error(tmp_path) -> None:
    """扫描期判定异常 → fail-closed（跳过该文件，不索引），不向上抛断整轮扫描。"""
    (tmp_path / "app.py").write_text("x = 1\n")

    def boom(rel: str) -> bool:
        raise RuntimeError("matcher exploded")

    result = scan_directory(str(tmp_path), is_excluded_rel=boom)

    assert result == []


# ============================================================================
# indexer full + incremental 扫描挂接排除过滤（fail-closed，EXCL-02）
# ============================================================================

# 异步测试由 pytest-asyncio AUTO 模式自动收集；DB 访问标记按测试函数施加，
# 避免污染上面三个同步 scan_directory 测试。
_db = pytest.mark.django_db(transaction=True)


def _mk_chunk(file_path: str) -> list[CodeChunk]:
    return [
        CodeChunk(
            content=f"chunk of {file_path}",
            file_path=file_path,
            file_hash=f"hash-{file_path}",
            language="python",
            start_line=1,
            end_line=5,
            node_type="function",
            context_header=f"# {file_path}",
        )
    ]


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """stub Qdrant / embedding / graph 的重型副作用，让扫描+过滤逻辑可单测。"""
    from services import indexer as ix

    monkeypatch.setattr(ix, "qdrant_create_collection", AsyncMock(return_value=True))
    monkeypatch.setattr(ix, "qdrant_delete_by_file_path", AsyncMock(return_value=True))
    monkeypatch.setattr(ix, "qdrant_update_file_path", AsyncMock(return_value=True))
    monkeypatch.setattr(ix, "qdrant_upsert_vectors", AsyncMock(return_value=True))
    monkeypatch.setattr(ix, "get_files_last_commit", AsyncMock(return_value={}))
    monkeypatch.setattr(ix, "FILE_BATCH_CHUNK_THRESHOLD", 1)
    monkeypatch.setattr(
        ix.EmbeddingService,
        "generate_embeddings_batch",
        AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    )

    async def _noop(self: object, *a: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(ix.IndexerService, "_ensure_collection", _noop)
    monkeypatch.setattr(ix.IndexerService, "_extract_and_write_graph", _noop)
    monkeypatch.setattr(ix.IndexerService, "_update_branch_index_record", _noop)


def _write_repo_tree(root: str) -> None:
    """造含正常文件 + builtin/per-repo 应排除文件的临时仓库树。"""
    with open(os.path.join(root, "app.py"), "w") as f:
        f.write("def main():\n    return 1\n")
    with open(os.path.join(root, "data.json"), "w") as f:
        f.write('{"k": 1}\n')
    # builtin glob: *secret*.json
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    with open(os.path.join(root, "config", "secret.json"), "w") as f:
        f.write('{"token": "leak"}\n')
    # builtin dir: secrets/
    os.makedirs(os.path.join(root, "secrets"), exist_ok=True)
    with open(os.path.join(root, "secrets", "leak.py"), "w") as f:
        f.write("API_KEY = 'leak'\n")
    # per-repo glob: *.private.js
    with open(os.path.join(root, "app.private.js"), "w") as f:
        f.write("const k = 1;\n")
    # 扩展名外（builtin .env glob 兜底，但扩展名白名单本就不收）
    with open(os.path.join(root, ".env"), "w") as f:
        f.write("SECRET=1\n")


async def _seed_per_repo_rule(repository: Any) -> None:
    from asgiref.sync import sync_to_async

    from repositories.models import RepoExclusionRule

    await sync_to_async(RepoExclusionRule.objects.create)(
        repository=repository,
        pattern="*.private.js",
        rule_type="glob",
        source="user",
    )


async def _indexed_paths(repository_id: str) -> set[str]:
    from repositories.models import FileIndex

    return {
        fp
        async for fp in FileIndex.objects.filter(repository_id=repository_id).values_list(
            "file_path", flat=True
        )
    }


@_db
async def test_full_index_skips_excluded_files(repository) -> None:
    """run_full_index：builtin + per-repo 命中的文件不写入 FileIndex；正常文件写入。"""
    from services.exclusion import invalidate_matcher_cache
    from services.indexer import IndexerService

    await _seed_per_repo_rule(repository)
    invalidate_matcher_cache(str(repository.id))

    with tempfile.TemporaryDirectory() as tmp:
        _write_repo_tree(tmp)
        indexer = IndexerService(str(repository.id))
        with patch.object(
            indexer.parser,
            "parse_file_dual",
            side_effect=lambda full, base_path, repository_id="": (
                _mk_chunk(os.path.relpath(full, base_path).replace(os.sep, "/")),
                None,
            ),
        ):
            result = await indexer.run_full_index(tmp)

    assert result["status"] == "success"
    indexed = await _indexed_paths(str(repository.id))
    assert "app.py" in indexed
    assert "data.json" in indexed
    # builtin / per-repo 排除文件均不得进入 FileIndex
    assert "config/secret.json" not in indexed
    assert "secrets/leak.py" not in indexed
    assert "app.private.js" not in indexed
    assert ".env" not in indexed


@_db
async def test_full_index_auto_excludes_large_files_before_parse(repository) -> None:
    """run_full_index：超过 2MB 的文件在 parser 前跳过，并自动落排除规则。"""
    from repositories.models import RepoExclusionRule
    from services.exclusion import invalidate_matcher_cache
    from services.indexer import MAX_PARSE_FILE_BYTES, IndexerService

    invalidate_matcher_cache(str(repository.id))

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "app.py"), "w") as f:
            f.write("def main():\n    return 1\n")
        with open(os.path.join(tmp, "huge.json"), "w") as f:
            f.write('{"payload":"')
            f.write("x" * (MAX_PARSE_FILE_BYTES + 1))
            f.write('"}\n')

        indexer = IndexerService(str(repository.id))

        def _parse(full: str, base_path: str, repository_id: str = ""):
            rel = os.path.relpath(full, base_path).replace(os.sep, "/")
            assert rel != "huge.json"
            return _mk_chunk(rel), None

        with patch.object(indexer.parser, "parse_file_dual", side_effect=_parse) as parse_mock:
            result = await indexer.run_full_index(tmp)

        parsed = {
            os.path.relpath(call.args[0], tmp).replace(os.sep, "/")
            for call in parse_mock.call_args_list
        }

    assert result["status"] == "success"
    assert parsed == {"app.py"}
    indexed = await _indexed_paths(str(repository.id))
    assert "app.py" in indexed
    assert "huge.json" not in indexed

    rule = await RepoExclusionRule.objects.filter(
        repository=repository,
        rule_type=RepoExclusionRule.RuleType.REGEX,
        pattern=re.escape("huge.json"),
        source=RepoExclusionRule.Source.AI_SUGGESTED,
    ).afirst()
    assert rule is not None
    assert rule.enabled is True


@_db
async def test_full_index_builtin_default_excludes_without_per_repo_rule(
    repository,
) -> None:
    """无任何 per-repo 规则时，builtin 全局默认即足以挡住 secret/secrets（开箱即用）。"""
    from services.exclusion import invalidate_matcher_cache
    from services.indexer import IndexerService

    invalidate_matcher_cache(str(repository.id))

    with tempfile.TemporaryDirectory() as tmp:
        _write_repo_tree(tmp)
        indexer = IndexerService(str(repository.id))
        with patch.object(
            indexer.parser,
            "parse_file_dual",
            side_effect=lambda full, base_path, repository_id="": (
                _mk_chunk(os.path.relpath(full, base_path).replace(os.sep, "/")),
                None,
            ),
        ):
            await indexer.run_full_index(tmp)

    indexed = await _indexed_paths(str(repository.id))
    assert "app.py" in indexed
    assert "config/secret.json" not in indexed
    assert "secrets/leak.py" not in indexed


@_db
async def test_incremental_index_skips_excluded_files(repository) -> None:
    """run_incremental_index：被排除文件不进入 diff 的 added/modified（FileIndex 见证）。"""
    from services.exclusion import invalidate_matcher_cache
    from services.indexer import IndexerService

    await _seed_per_repo_rule(repository)
    invalidate_matcher_cache(str(repository.id))

    with tempfile.TemporaryDirectory() as tmp:
        _write_repo_tree(tmp)
        indexer = IndexerService(str(repository.id))
        with patch.object(
            indexer.parser,
            "parse_file_dual",
            side_effect=lambda full, base_path, repository_id="": (
                _mk_chunk(os.path.relpath(full, base_path).replace(os.sep, "/")),
                None,
            ),
        ):
            result = await indexer.run_incremental_index(tmp)

    assert result["status"] == "success"
    indexed = await _indexed_paths(str(repository.id))
    assert "app.py" in indexed
    assert "config/secret.json" not in indexed
    assert "secrets/leak.py" not in indexed
    assert "app.private.js" not in indexed
