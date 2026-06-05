"""TS / TSX 语言 extractor 测试 —— 验证 symbol / import / call 抽取 + JSX 大小写过滤。

覆盖 initial implementation..work item：
- work item：TSExtractor / TSXExtractor 注册（巩固由 test_registry.py 测）
- work item：interface / type_alias / class / function / method / 命名 arrow 符号抽取
- work item：import named / namespace / default / type-only / 重导出
- work item：member call + DIRECT call
- work item：TSX 独立 grammar（tsx grammar 0 ERROR，ts grammar 报 ERROR）
- work item：JSX 大写组件 → call_type='JSX'，小写 HTML 元素不抽
关联 fixture：tests/fixtures/ts_module.ts + tests/fixtures/tsx_component.tsx。
"""

from __future__ import annotations

import os

import pytest

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor


@pytest.fixture
def ts_source():
    """加载 TS fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fixtures_dir, "ts_module.ts"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def tsx_source():
    """加载 TSX fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fixtures_dir, "tsx_component.tsx"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def ts_parser():
    """返回预配置的 tree-sitter TypeScript Parser。"""
    import tree_sitter_typescript
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_typescript.language_typescript()))


@pytest.fixture
def tsx_parser():
    """返回预配置的 tree-sitter TSX Parser。"""
    import tree_sitter_typescript
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_typescript.language_tsx()))


class TestTSExtractor:
    """TypeScript (.ts) extractor 端到端测试 —— 覆盖 work item..work item。"""

    def test_ts_parser_available(self, ts_parser):
        """tree-sitter-typescript language_typescript 可用 + Parser 实例化成功。"""
        assert ts_parser is not None

    def test_ts_symbols(self, ts_parser, ts_source):
        """TS 符号抽取：interface / type / class / method / function / 命名 arrow。"""
        tree = ts_parser.parse(ts_source.encode("utf-8"))
        ctx = FileContext(file_path="ts_module.ts", language="typescript", repository_id="r1")
        backend = TreeSitterBackend("typescript")

        symbols = backend.extract_symbols(tree, ts_source, ctx)

        by_name = {s.name: s.symbol_type for s in symbols}
        # work item interface / type → CLASS
        assert by_name.get("ServiceConfig") == "CLASS", by_name
        assert by_name.get("StatusCode") == "CLASS", by_name
        # class_declaration → CLASS
        assert by_name.get("UserService") == "CLASS", by_name
        # work item method_definition → METHOD
        assert by_name.get("fetchUser") == "METHOD", by_name
        # function_declaration → FUNCTION
        assert by_name.get("createService") == "FUNCTION", by_name
        # work item 命名 arrow → FUNCTION
        assert by_name.get("buildUrl") == "FUNCTION", by_name

    def test_ts_method_symbols(self, ts_parser, ts_source):
        """METHOD 类符号至少含 fetchUser（work item 守护）。"""
        tree = ts_parser.parse(ts_source.encode("utf-8"))
        ctx = FileContext(file_path="ts_module.ts", language="typescript", repository_id="r1")
        backend = TreeSitterBackend("typescript")

        symbols = backend.extract_symbols(tree, ts_source, ctx)

        method_names = {s.name for s in symbols if s.symbol_type == "METHOD"}
        assert "fetchUser" in method_names, method_names

    def test_ts_imports(self, ts_parser, ts_source):
        """TS import 抽取：'vue' / './types' / './utils' 三模块命中。"""
        tree = ts_parser.parse(ts_source.encode("utf-8"))
        ctx = FileContext(file_path="ts_module.ts", language="typescript", repository_id="r1")
        backend = TreeSitterBackend("typescript")

        imports = backend.extract_imports(tree, ctx)

        modules = [imp.target_module for imp in imports]
        assert "vue" in modules, modules
        assert "./types" in modules, modules
        assert "./utils" in modules, modules

    def test_ts_reexport_imports(self, ts_parser, ts_source):
        """work item 重导出：./types 至少出现 1 次且 imported_names 含 'User'。"""
        tree = ts_parser.parse(ts_source.encode("utf-8"))
        ctx = FileContext(file_path="ts_module.ts", language="typescript", repository_id="r1")
        backend = TreeSitterBackend("typescript")

        imports = backend.extract_imports(tree, ctx)

        types_imports = [imp for imp in imports if imp.target_module == "./types"]
        assert len(types_imports) >= 1, types_imports
        all_names: set[str] = set()
        for imp in types_imports:
            all_names.update(imp.imported_names)
        assert "User" in all_names, all_names

    def test_ts_calls(self, ts_parser, ts_source):
        """TS 调用抽取：utils.request / utils.join 等 member call → METHOD。"""
        tree = ts_parser.parse(ts_source.encode("utf-8"))
        ctx = FileContext(file_path="ts_module.ts", language="typescript", repository_id="r1")
        backend = TreeSitterBackend("typescript")

        calls = backend.extract_calls(tree, ctx)

        callee_names = {c.callee_name for c in calls}
        # member call utils.request / utils.join 至少一个命中
        assert "request" in callee_names or "join" in callee_names, callee_names
        method_call_types = {c.call_type for c in calls if c.call_type == "METHOD"}
        assert "METHOD" in method_call_types, [c.call_type for c in calls]


class TestTSXExtractor:
    """TSX (.tsx) extractor 端到端测试 —— 覆盖 work item / work item + work item。"""

    def test_tsx_parser_available(self, tsx_parser):
        """tree-sitter-typescript language_tsx 可用 + Parser 实例化成功。"""
        assert tsx_parser is not None

    def test_tsx_parser_distinct_from_ts(self, tsx_parser, ts_parser, tsx_source):
        """work item 硬证据：tsx 源码用 tsx_parser 0 ERROR，用 ts_parser 必报 ERROR。"""
        tree_tsx = tsx_parser.parse(tsx_source.encode("utf-8"))
        tree_ts = ts_parser.parse(tsx_source.encode("utf-8"))
        assert not tree_tsx.root_node.has_error, "tsx grammar 应解析无错"
        assert tree_ts.root_node.has_error, "ts grammar 应在解析 tsx 源码时报错"

    def test_tsx_symbols(self, tsx_parser, tsx_source):
        """TSX 符号抽取：Props (CLASS) / UserCard (FUNCTION) / handleClick (FUNCTION)。"""
        tree = tsx_parser.parse(tsx_source.encode("utf-8"))
        ctx = FileContext(file_path="tsx_component.tsx", language="tsx", repository_id="r1")
        backend = TreeSitterBackend("tsx")

        symbols = backend.extract_symbols(tree, tsx_source, ctx)

        names = {s.name for s in symbols}
        assert "Props" in names, names
        assert "UserCard" in names, names
        assert "handleClick" in names, names

    def test_tsx_imports(self, tsx_parser, tsx_source):
        """TSX import 抽取：'react' / './Card' / './api' 三模块命中。"""
        tree = tsx_parser.parse(tsx_source.encode("utf-8"))
        ctx = FileContext(file_path="tsx_component.tsx", language="tsx", repository_id="r1")
        backend = TreeSitterBackend("tsx")

        imports = backend.extract_imports(tree, ctx)

        modules = {imp.target_module for imp in imports}
        assert "react" in modules, modules
        assert "./Card" in modules, modules
        assert "./api" in modules, modules

    def test_jsx_uppercase_component_as_call(self, tsx_parser, tsx_source):
        """work item / work item：大写 JSX 组件抽为 call_type='JSX'，至少含 Card 或 UserAvatar。"""
        tree = tsx_parser.parse(tsx_source.encode("utf-8"))
        ctx = FileContext(file_path="tsx_component.tsx", language="tsx", repository_id="r1")
        backend = TreeSitterBackend("tsx")

        calls = backend.extract_calls(tree, ctx)

        jsx_calls = {c.callee_name for c in calls if c.call_type == "JSX"}
        assert "Card" in jsx_calls or "UserAvatar" in jsx_calls, jsx_calls

    def test_jsx_lowercase_html_not_call(self, tsx_parser, tsx_source):
        """work item 守卫：小写 HTML 标签 div / span / button 不在 callee_name 列表。"""
        tree = tsx_parser.parse(tsx_source.encode("utf-8"))
        ctx = FileContext(file_path="tsx_component.tsx", language="tsx", repository_id="r1")
        backend = TreeSitterBackend("tsx")

        calls = backend.extract_calls(tree, ctx)

        callee_names = {c.callee_name for c in calls}
        assert "div" not in callee_names, callee_names
        assert "span" not in callee_names, callee_names
        assert "button" not in callee_names, callee_names

    def test_jsx_component_ref_caliber(self, tsx_parser, tsx_source):
        """work item 口径：TSX 大写组件标签抽成 JSX 边、callee_name 与组件名一致、不含小写 HTML。"""
        tree = tsx_parser.parse(tsx_source.encode("utf-8"))
        ctx = FileContext(file_path="tsx_component.tsx", language="tsx", repository_id="r1")
        backend = TreeSitterBackend("tsx")

        calls = backend.extract_calls(tree, ctx)

        jsx_calls = [c for c in calls if c.call_type == "JSX"]
        jsx_callees = {c.callee_name for c in jsx_calls}
        # 至少抽到大写组件 Card / UserAvatar，且每个 JSX callee 首字母大写（与组件名同口径）
        assert jsx_callees, "未抽到任何 JSX 组件引用边"
        assert {"Card", "UserAvatar"} & jsx_callees, jsx_callees
        for name in jsx_callees:
            assert name[:1].isupper(), f"JSX callee 应为大写组件名: {name}"
        # 小写 HTML 标签不应出现在 JSX 边中
        assert "div" not in jsx_callees, jsx_callees
        assert "span" not in jsx_callees, jsx_callees
        assert "button" not in jsx_callees, jsx_callees
