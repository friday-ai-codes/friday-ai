""" 单测 —— FrontendImportResolver 相对/alias/扩展名/index/第三方/锚定。
纯逻辑单测（同 ``test_python_import.py`` 风格，无 DB / 无 async）：手动构造
``SymbolIndex`` 后直接 ``idx._files.update({...})`` 塞已知文件集，再断言
``resolve_module`` 各分支；另覆盖 ``parse_tsconfig_aliases`` 纯函数解析。
"""
from __future__ import annotations
from codegraph.resolver.frontend_import import (
 FrontendImportResolver,
 parse_tsconfig_aliases,
)
from codegraph.resolver.symbol_index import SymbolIndex
_ALIAS = {"~/": "src/"}
def _resolver_with_files(*files: str) -> FrontendImportResolver:
 """构造一个 ``_files`` 含给定文件集、alias=~/→src/ 的 FrontendImportResolver。"""
 idx = SymbolIndex
 idx._files.update(files)
 return FrontendImportResolver(idx, _ALIAS)
class TestRelativeImport:
 """相对 import：按 source_file 目录回溯 + 扩展名补全。"""
 def test_same_dir_dot_slash(self) -> None:
 resolver = _resolver_with_files("src/views/Foo.vue", "src/views/Page.vue")
 assert (
 resolver.resolve_module("./Foo", True, "src/views/Page.vue")
 == "src/views/Foo.vue"
 )
 def test_parent_dir_dotdot(self) -> None:
 resolver = _resolver_with_files("src/utils/bar.ts", "src/views/Page.vue")
 assert (
 resolver.resolve_module("../utils/bar", True, "src/views/Page.vue")
 == "src/utils/bar.ts"
 )
 def test_extension_candidate_order_ts_before_vue(self) -> None:
 # 同 base 同时存在 .ts 与 .vue → 候选顺序固定先 .ts。
 resolver = _resolver_with_files(
 "src/views/Foo.ts", "src/views/Foo.vue", "src/views/Page.vue"
 )
 assert (
 resolver.resolve_module("./Foo", True, "src/views/Page.vue")
 == "src/views/Foo.ts"
 )
class TestAliasImport:
 """alias import：~/ → src/ 改写后解析。"""
 def test_alias_resolves(self) -> None:
 resolver = _resolver_with_files("src/components/Foo.vue", "src/views/Page.vue")
 assert (
 resolver.resolve_module("~/components/Foo", False, "src/views/Page.vue")
 == "src/components/Foo.vue"
 )
class TestIndexResolution:
 """目录 import：补 index.{ext}。"""
 def test_dir_resolves_to_index(self) -> None:
 resolver = _resolver_with_files(
 "src/views/widgets/index.ts", "src/views/Page.vue"
 )
 assert (
 resolver.resolve_module("./widgets", True, "src/views/Page.vue")
 == "src/views/widgets/index.ts"
 )
 def test_file_precedes_index(self) -> None:
 # 同时存在 widgets.ts 与 widgets/index.ts → 文件优先于 index。
 resolver = _resolver_with_files(
 "src/views/widgets.ts",
 "src/views/widgets/index.ts",
 "src/views/Page.vue",
 )
 assert (
 resolver.resolve_module("./widgets", True, "src/views/Page.vue")
 == "src/views/widgets.ts"
 )
class TestExplicitExtension:
 """显式扩展：只按该扩展精确匹，不枚举其它候选。"""
 def test_explicit_vue_only(self) -> None:
 # 仓内有 Foo.ts 但 import 写 ./Foo.vue → 不命中 Foo.ts，须命中 .vue。
 resolver = _resolver_with_files(
 "src/views/Foo.ts", "src/views/Foo.vue", "src/views/Page.vue"
 )
 assert (
 resolver.resolve_module("./Foo.vue", True, "src/views/Page.vue")
 == "src/views/Foo.vue"
 )
 def test_explicit_ext_miss_returns_none(self) -> None:
 resolver = _resolver_with_files("src/views/Foo.ts", "src/views/Page.vue")
 assert resolver.resolve_module("./Foo.vue", True, "src/views/Page.vue") is None
class TestThirdParty:
 """第三方裸模块（非相对、非 alias）→ None，不误连。"""
 def test_bare_module_returns_none(self) -> None:
 resolver = _resolver_with_files("src/views/Page.vue")
 assert resolver.resolve_module("vue", False, "src/views/Page.vue") is None
 def test_scoped_package_returns_none(self) -> None:
 resolver = _resolver_with_files("src/views/Page.vue")
 assert (
 resolver.resolve_module("@vueuse/core", False, "src/views/Page.vue") is None
 )
class TestAnchoredFallback:
 """``/`` + endswith 锚定兜底（避免 auth.ts 误匹 oauth.ts）。"""
 def test_anchored_hit_with_prefix(self) -> None:
 resolver = _resolver_with_files("web/src/utils/auth.ts", "web/src/views/Page.vue")
 # alias 改写得 src/utils/auth，精确 miss → 锚定兜底命中带 web/ 前缀路径。
 assert (
 resolver.resolve_module("~/utils/auth", False, "web/src/views/Page.vue")
 == "web/src/utils/auth.ts"
 )
 def test_anchored_does_not_match_similar_suffix(self) -> None:
 resolver = _resolver_with_files(
 "web/src/utils/oauth.ts", "web/src/views/Page.vue"
 )
 assert (
 resolver.resolve_module("~/utils/auth", False, "web/src/views/Page.vue")
 is None
 )
class TestParseTsconfigAliases:
 """tsconfig paths → alias_map 解析。"""
 def test_standard_paths(self) -> None:
 data = {"compilerOptions": {"baseUrl": ".", "paths": {"~/*": ["src/*"]}}}
 assert parse_tsconfig_aliases(data) == {"~/": "src/"}
 def test_base_url_non_dot(self) -> None:
 data = {"compilerOptions": {"baseUrl": "src", "paths": {"~/*": ["lib/*"]}}}
 assert parse_tsconfig_aliases(data) == {"~/": "src/lib/"}
 def test_missing_paths_returns_empty(self) -> None:
 assert parse_tsconfig_aliases({"compilerOptions": {}}) == {}
 def test_invalid_json_returns_empty(self) -> None:
 assert parse_tsconfig_aliases("{not valid json") == {}
 def test_json_text_input(self) -> None:
 text = '{"compilerOptions":{"paths":{"@/*":["src/*"]}}}'
 assert parse_tsconfig_aliases(text) == {"@/": "src/"}
