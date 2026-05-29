""" 单测 —— PythonImportResolver 绝对/相对/归一化/第三方/__init__ 包/锚定。
纯逻辑单测（参考 ``api_resolver/tests/test_detector.py`` 风格，无需 DB / 无 async）：
手动构造 ``SymbolIndex`` 实例后直接 ``idx._files.update({...})`` 塞入已知文件集，
再断言 ``resolve_module`` 各分支行为。
"""
from __future__ import annotations
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import SymbolIndex
def _resolver_with_files(*files: str) -> PythonImportResolver:
 """构造一个 ``_files`` 含给定文件集的 ``PythonImportResolver``。"""
 idx = SymbolIndex
 idx._files.update(files)
 return PythonImportResolver(idx)
class TestAbsoluteImport:
 """绝对 import：``from a.b import foo`` → ``a/b.py``。"""
 def test_absolute_resolves_to_module_file(self) -> None:
 resolver = _resolver_with_files("a/b.py", "a/c.py")
 assert resolver.resolve_module("a.b", False, "a/c.py") == "a/b.py"
 def test_absolute_deeper_dotted_module(self) -> None:
 resolver = _resolver_with_files("a/b/d.py", "a/c.py")
 assert resolver.resolve_module("a.b.d", False, "a/c.py") == "a/b/d.py"
class TestRelativeImport:
 """相对 import：按 caller 目录解析（PEP 328 层级 / ）。"""
 def test_relative_same_package_one_dot(self) -> None:
 # 1 点 = 同包，up_levels=0
 resolver = _resolver_with_files("pkg/x.py", "pkg/c.py")
 assert resolver.resolve_module(".x", True, "pkg/c.py") == "pkg/x.py"
 def test_relative_parent_package_two_dots(self) -> None:
 # 2 点 = 父包，up_levels=1，从 pkg/sub 回溯到 pkg
 resolver = _resolver_with_files("pkg/util.py", "pkg/sub/c.py")
 assert resolver.resolve_module("..util", True, "pkg/sub/c.py") == "pkg/util.py"
class TestNormalization:
 """归一化：折叠后命中的路径无双斜杠 / 无前导斜杠。"""
 def test_no_double_or_leading_slash(self) -> None:
 resolver = _resolver_with_files("pkg/x.py")
 result = resolver.resolve_module(".x", True, "pkg/c.py")
 assert result == "pkg/x.py"
 assert result is not None
 assert "//" not in result
 assert not result.startswith("/")
class TestThirdParty:
 """第三方/仓外 import：返回 None，不误连。"""
 def test_third_party_returns_none(self) -> None:
 resolver = _resolver_with_files("a/c.py")
 assert resolver.resolve_module("django.http", False, "a/c.py") is None
