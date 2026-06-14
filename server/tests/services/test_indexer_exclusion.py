"""索引扫描面排除守护测试（Phase 22 Plan 02，fail-closed，EXCL-02）。

覆盖两块：
- ``scan_directory`` 新增可选相对路径排除回调（PF-04 修正后），向后兼容 + 命中跳过
  + 判定异常 fail-closed。
- ``indexer.run_full_index`` / ``run_incremental_index`` 经 ``build_matcher_for_repo``
  把被排除文件挡在 ``files_to_process`` / diff 之外（含 builtin 开箱即用与 per-repo 规则）。
"""

from __future__ import annotations

import os
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
