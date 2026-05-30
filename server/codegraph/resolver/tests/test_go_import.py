""" 单测 —— GoImportResolver 包目录解析 + parse_go_module。
纯逻辑单测（同 ``test_python_import.py`` 风格，无 DB）：``idx._files.update`` 塞文件集，
断言 ``resolve_package_dir`` / ``resolve_module`` 各分支；另覆盖 ``parse_go_module``。
"""
from __future__ import annotations
from codegraph.resolver.go_import import GoImportResolver, parse_go_module
from codegraph.resolver.symbol_index import SymbolIndex
_MODULE = "github.com/org/repo"
def _resolver_with_files(*files: str) -> GoImportResolver:
 idx = SymbolIndex
 idx._files.update(files)
 return GoImportResolver(idx, _MODULE)
class TestParseGoModule:
 def test_reads_module_path(self) -> None:
 text = "module github.com/org/repo\n\ngo 1.22\n\nrequire (\n)\n"
 assert parse_go_module(text) == "github.com/org/repo"
 def test_missing_module_returns_none(self) -> None:
 assert parse_go_module("go 1.22\n") is None
class TestResolvePackageDir:
 def test_internal_package(self) -> None:
 resolver = _resolver_with_files("internal/svc/handler.go")
 assert (
 resolver.resolve_package_dir(f"{_MODULE}/internal/svc") == "internal/svc"
 )
 def test_module_root_package(self) -> None:
 resolver = _resolver_with_files("main.go")
 assert resolver.resolve_package_dir(_MODULE) == ""
 def test_stdlib_returns_none(self) -> None:
 resolver = _resolver_with_files("main.go")
 assert resolver.resolve_package_dir("fmt") is None
 def test_third_party_returns_none(self) -> None:
 resolver = _resolver_with_files("main.go")
 assert resolver.resolve_package_dir("github.com/gin-gonic/gin") is None
class TestResolveModule:
 def test_resolves_to_deterministic_go_file(self) -> None:
 # 同包多文件 → 取字典序最小（确定性代表文件）。
 resolver = _resolver_with_files(
 "internal/svc/zeta.go",
 "internal/svc/alpha.go",
 "internal/svc/handler.go",
 )
 assert (
 resolver.resolve_module(f"{_MODULE}/internal/svc", False, "main.go")
 == "internal/svc/alpha.go"
 )
 def test_stdlib_returns_none(self) -> None:
 resolver = _resolver_with_files("internal/svc/handler.go")
 assert resolver.resolve_module("fmt", False, "main.go") is None
 def test_package_dir_without_go_file_returns_none(self) -> None:
 # 目录存在非 .go 文件但无 .go → None（不误连）。
 resolver = _resolver_with_files("internal/svc/README.md")
 assert (
 resolver.resolve_module(f"{_MODULE}/internal/svc", False, "main.go") is None
 )
