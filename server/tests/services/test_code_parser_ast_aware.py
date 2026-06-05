"""``CodeParser`` ast_aware 多语言精细切片测试（implementation 重写后）。

固化重写后的行为并防回归（对照重写前的三处翻车）：
- class 不被揉进相邻小函数的合并组（Python / Go）；
- TS ``interface`` / ``type`` / ``export`` 包裹符号被正确抽取（重写前退化为 0）；
- Vue ``<script>`` 精细切片且行号映射回 SFC 真实行；
- ``.tsx`` 用 tsx grammar 解析 JSX；
- 大符号按行切分不丢尾（无 ``... (truncated)`` 标记）。

底层走纯 tree-sitter（``TreeSitterBackend``），不依赖 gopls / volar LSP 进程。
"""

from __future__ import annotations

import pytest

from services.code_parser import CodeParser


@pytest.fixture
def parser() -> CodeParser:
    return CodeParser()


def _symbol_names(chunks: list) -> set[str]:
    return {c.parent_symbol for c in chunks if c.parent_symbol}


def test_python_class_not_merged_into_functions(parser: CodeParser) -> None:
    src = (
        "import os\n"
        "GLOBAL = 1\n"
        "def small(): return 1\n"
        "def helper(x): return x + 1\n"
        "class Service:\n"
        "    def run(self): return helper(GLOBAL)\n"
    )
    chunks = parser._ast_aware_chunk(src, "demo.py", "h" * 64, "python")

    cls = [c for c in chunks if c.node_type == "class" and c.parent_symbol == "Service"]
    assert len(cls) == 1, "class Service 必须独立成块"

    merged = [c for c in chunks if c.node_type == "merged_group"]
    assert len(merged) == 1, "small/helper 两个小函数应合并为一组"
    assert "Service" not in (merged[0].parent_symbol or ""), "class 不得被卷入合并组"


def test_go_separates_func_type_method(parser: CodeParser) -> None:
    src = (
        "package main\n"
        'import "fmt"\n'
        'func Hello(n string) string { return fmt.Sprintf("hi %s", n) }\n'
        "type User struct { Name string }\n"
        "func (u *User) Greet() string { return Hello(u.Name) }\n"
    )
    chunks = parser._ast_aware_chunk(src, "demo.go", "h" * 64, "go")
    names = _symbol_names(chunks)
    assert {"Hello", "User", "Greet"} <= names


def test_typescript_extracts_interface_and_type(parser: CodeParser) -> None:
    # 重写前：整文件退化成单个 module 块（interface/type/export 全丢）。
    src = (
        'import { ref } from "vue"\n'
        "export interface User { id: number }\n"
        "export type ID = string | number\n"
        "export function add(a: number, b: number): number { return a + b }\n"
        "export class Repo { find(id: ID): User | null { return null } }\n"
        "export const handler = (e: Event) => { console.log(e) }\n"
    )
    chunks = parser._ast_aware_chunk(src, "demo.ts", "h" * 64, "typescript")
    names = _symbol_names(chunks)
    assert {"User", "ID", "add", "Repo", "handler"} <= names


def test_vue_script_fine_grained_with_line_offset(parser: CodeParser) -> None:
    src = (
        '<script setup lang="ts">\n'   # line 1
        'import { ref } from "vue"\n'  # line 2
        "const count = ref(0)\n"       # line 3
        "function inc() {\n"           # line 4
        "  count.value++\n"            # line 5
        "}\n"                          # line 6
        "</script>\n"                  # line 7
        '<template><button @click="inc">{{ count }}</button></template>\n'
    )
    chunks = parser._parse_vue(src, "Demo.vue", "h" * 64)
    inc = [c for c in chunks if c.parent_symbol == "inc"]
    assert len(inc) == 1
    assert inc[0].start_line == 4, "function inc 必须映射到 SFC 真实行号（第 4 行）"
    assert all(c.language == "vue" for c in chunks)


def test_large_function_not_truncated(parser: CodeParser) -> None:
    body = "\n".join(
        f"    x{i} = compute_{i}() + something_long_helper_call({i})" for i in range(60)
    )
    src = f"def big():\n{body}\n"
    chunks = parser._ast_aware_chunk(src, "big.py", "h" * 64, "python")

    assert all("truncated" not in c.content for c in chunks), "不得出现旧实现的截断丢尾标记"
    big_parts = [c for c in chunks if c.parent_symbol == "big"]
    assert big_parts, "大函数应产出至少一个 chunk"
    assert max(c.end_line for c in big_parts) >= 60, "切分必须覆盖到函数尾行"


def test_tsx_grammar_used_for_tsx_files(parser: CodeParser) -> None:
    src = (
        "export function App() {\n"
        '  return <div className="x">hi</div>\n'
        "}\n"
    )
    # .tsx 文件应使用 tsx grammar 正确解析 JSX（typescript grammar 会把 JSX 当语法错误）
    chunks = parser._ast_aware_chunk(src, "App.tsx", "h" * 64, "typescript")
    assert any(c.parent_symbol == "App" for c in chunks)


def test_unsupported_language_falls_back_gracefully(parser: CodeParser) -> None:
    # json 不在 codegraph SYMBOL_TYPES → 不抛异常，由 symbol_chunker 兜底（module 整切）。
    src = '{"a": 1, "b": [1, 2, 3], "c": {"nested": true, "deep": "value here"}}\n' * 3
    chunks = parser._ast_aware_chunk(src, "data.json", "h" * 64, "json")
    assert isinstance(chunks, list)


def test_empty_content_returns_no_chunks(parser: CodeParser) -> None:
    chunks = parser._ast_aware_chunk("", "empty.py", "h" * 64, "python")
    assert chunks == []


# ---------------------------------------------------------------------------
# parse_file_dual：一次解析双供（implementation single-parse）
# ---------------------------------------------------------------------------


def test_parse_file_dual_python_returns_chunks_and_bundle(parser: CodeParser, tmp_path) -> None:
    f = tmp_path / "m.py"
    f.write_text("import os\ndef foo():\n    return 1\nclass Bar:\n    def m(self):\n        return foo()\n")
    parser.chunking_mode = "ast_aware"
    chunks, bundle = parser.parse_file_dual(str(f), base_path=str(tmp_path), repository_id="r")

    assert bundle is not None, "图谱支持语言应返回 ExtractionBundle"
    assert {"foo", "Bar"} <= {s.name for s in bundle.symbols}
    assert "foo" in {c.parent_symbol for c in chunks if c.parent_symbol}
    # chunk 与 bundle.symbols 同源：绑定 chunk 的 symbol_key 都在 symbols 里
    sym_keys = {(s.file_path, s.name, s.start_line) for s in bundle.symbols}
    for c in chunks:
        if c.symbol_key is not None:
            assert c.symbol_key in sym_keys


def test_parse_file_dual_markdown_has_no_bundle(parser: CodeParser, tmp_path) -> None:
    f = tmp_path / "r.md"
    f.write_text("# Title\n\nsome reasonably long markdown body content here for chunking\n")
    parser.chunking_mode = "ast_aware"
    chunks, bundle = parser.parse_file_dual(str(f), base_path=str(tmp_path))

    assert bundle is None, "Markdown 不走图谱双供，bundle 必为 None"
    assert isinstance(chunks, list)


def test_parse_file_dual_fixed_mode_has_no_bundle(parser: CodeParser, tmp_path) -> None:
    f = tmp_path / "m.py"
    f.write_text("def foo():\n    return 1\n")
    parser.chunking_mode = "fixed"
    chunks, bundle = parser.parse_file_dual(str(f), base_path=str(tmp_path))

    assert bundle is None, "fixed 模式退回 parse_file，无 bundle"
    assert isinstance(chunks, list)
