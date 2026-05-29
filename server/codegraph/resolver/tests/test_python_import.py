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
 def test_third_party_package_both_candidates_miss(self) -> None:
 # 两候选（a/b.py + a/b/__init__.py）全 miss → None（真第三方）。
 resolver = _resolver_with_files("a/c.py")
 assert resolver.resolve_module("requests.sessions", False, "a/c.py") is None
class TestPackageInit:
 """``__init__.py`` 包候选：``a/b`` 是包时解析到 ``a/b/__init__.py``（Pitfall 5）。"""
 def test_package_resolves_to_init(self) -> None:
 # 仓内只有 a/b/__init__.py（无 a/b.py）→ 命中包 __init__.py。
 resolver = _resolver_with_files("a/b/__init__.py", "a/c.py")
 assert resolver.resolve_module("a.b", False, "a/c.py") == "a/b/__init__.py"
 def test_module_file_precedes_package_init(self) -> None:
 # 同时存在 a/b.py 与 a/b/__init__.py → 候选顺序固定先模块文件命中。
 resolver = _resolver_with_files("a/b.py", "a/b/__init__.py", "a/c.py")
 assert resolver.resolve_module("a.b", False, "a/c.py") == "a/b.py"
class TestAnchoredFallback:
 """``/`` + endswith 锚定兜底：含统一前缀路径仍命中且不误匹配相似后缀。"""
 def test_anchored_hit_with_prefix(self) -> None:
 # _files 带统一前缀 server/，精确等值 miss → 锚定兜底命中。
 resolver = _resolver_with_files("server/pkg/auth.py", "server/pkg/c.py")
 assert resolver.resolve_module("pkg.auth", False, "server/pkg/c.py") == "server/pkg/auth.py"
 def test_anchored_does_not_match_similar_suffix(self) -> None:
 # 锚定 ``/pkg/auth.py`` 不得误匹配 ``server/pkg/oauth.py``（防 auth→oauth）。
 resolver = _resolver_with_files("server/pkg/oauth.py", "server/pkg/c.py")
 assert resolver.resolve_module("pkg.auth", False, "server/pkg/c.py") is None
