"""Phase: protocol helper 单元测试。"""
from __future__ import annotations
from pathlib import Path
import pytest
from codegraph.lsp.protocol import lsp, path_to_uri, uri_to_path
def test_path_to_uri_basic -> None:
 """基本 Linux/macOS 绝对路径转 file:// URI。"""
 assert path_to_uri(Path("/tmp/foo.txt")) == "file:///tmp/foo.txt"
def test_path_to_uri_rejects_relative -> None:
 """相对路径触发 ValueError，提示需要绝对路径。"""
 with pytest.raises(ValueError, match="绝对路径"):
 path_to_uri(Path("foo.txt"))
def test_uri_to_path_basic -> None:
 """基本 file:// URI 转 Path。"""
 assert uri_to_path("file:///tmp/foo.txt") == Path("/tmp/foo.txt")
def test_uri_to_path_rejects_non_file_scheme -> None:
 """http / git 等非 file scheme 一律拒绝，避免静默把 URL 当本地路径。"""
 with pytest.raises(ValueError, match="仅支持 file"):
 uri_to_path("http://x.com/foo.txt")
@pytest.mark.parametrize(
 "path_str",
 [
 "/tmp/foo.txt",
 "/Users/dev/project/src/main.py",
 "/tmp/中文目录/x.html",
 ],
)
def test_uri_path_roundtrip(path_str: str) -> None:
 """绝对路径 → URI → 绝对路径 的对称 roundtrip（含 percent-encoding 中文）。"""
 original = Path(path_str)
 encoded = path_to_uri(original)
 decoded = uri_to_path(encoded)
 assert decoded == original
def test_lsprotocol_types_reexport -> None:
 """lsprotocol 6 个核心 type 都可从 codegraph.lsp.protocol.lsp 访问。"""
 assert hasattr(lsp, "InitializeParams")
 assert hasattr(lsp, "WorkspaceSymbolParams")
 assert hasattr(lsp, "DocumentSymbolParams")
 assert hasattr(lsp, "ReferenceParams")
 assert hasattr(lsp, "DefinitionParams")
 assert hasattr(lsp, "ClientCapabilities")
