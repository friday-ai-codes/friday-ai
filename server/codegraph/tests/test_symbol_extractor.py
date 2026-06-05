"""Tests for Symbol extractor (work item)."""

import pytest


class TestSymbolExtractorHappyPath:
    """正常路径：basic_module.py 符号提取。"""

    def test_extracts_all_symbols(self, parse_fixture, make_file_context):
        """验证 basic_module.py 中所有符号被提取。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, file_path = parse_fixture("basic_module.py")
        ctx = make_file_context(file_path=file_path)
        symbols = extract_symbols(tree, source, ctx)

        names = {s.name for s in symbols}
        expected = {"helper_function", "async_main", "main", "DataProcessor",
                    "__init__", "process", "_clean", "async_fetch"}
        missing = expected - names
        assert not missing, f"Missing symbols: {missing}"

    def test_top_level_functions_have_correct_type(self, parse_fixture, make_file_context):
        """顶层函数 symbol_type 为 FUNCTION。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        top_funcs = [s for s in symbols if s.name in {"helper_function", "async_main", "main"}]
        assert len(top_funcs) == 3, f"Expected 3 top-level functions, got {len(top_funcs)}: {[s.name for s in top_funcs]}"
        for s in top_funcs:
            assert s.symbol_type == "FUNCTION", \
                f"{s.name}: expected FUNCTION, got {s.symbol_type}"

    def test_class_has_correct_type(self, parse_fixture, make_file_context):
        """类 symbol_type 为 CLASS。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        classes = [s for s in symbols if s.symbol_type == "CLASS"]
        class_names = {s.name for s in classes}
        assert "DataProcessor" in class_names, f"Expected DataProcessor, got {class_names}"

    def test_methods_have_correct_type(self, parse_fixture, make_file_context):
        """类内方法 symbol_type 为 METHOD。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        methods = [s for s in symbols if s.symbol_type == "METHOD"]
        method_names = {s.name for s in methods}
        expected = {"__init__", "process", "_clean", "async_fetch"}
        missing = expected - method_names
        assert not missing, f"Missing methods: {missing}"

    def test_async_detection(self, parse_fixture, make_file_context):
        """async 函数 is_async == True。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        for s in symbols:
            if s.name in {"async_main", "async_fetch"}:
                assert s.is_async is True, f"{s.name}: expected is_async=True"
            elif s.name in {"helper_function", "main"}:
                assert s.is_async is False, f"{s.name}: expected is_async=False"

    def test_line_numbers_valid(self, parse_fixture, make_file_context):
        """所有符号的 start_line/end_line 值有效。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        assert len(symbols) > 0, "No symbols extracted"
        for s in symbols:
            assert s.start_line > 0, f"{s.name}: start_line={s.start_line}"
            assert s.end_line >= s.start_line, \
                f"{s.name}: end_line={s.end_line} < start_line={s.start_line}"

    def test_file_path_in_output(self, parse_fixture, make_file_context):
        """所有 SymbolData 的 file_path 等于 ctx.file_path。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, file_path = parse_fixture("basic_module.py")
        ctx = make_file_context(file_path=file_path)
        symbols = extract_symbols(tree, source, ctx)

        for s in symbols:
            assert s.file_path == file_path, \
                f"{s.name}: expected file_path={file_path}, got {s.file_path}"

    def test_signature_contains_def_or_class(self, parse_fixture, make_file_context):
        """每个 SymbolData 的 signature 包含 def 或 class。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("basic_module.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        for s in symbols:
            assert ("def " in s.signature or "class " in s.signature), \
                f"{s.name}: signature lacks def/class: {s.signature}"


class TestSymbolExtractorEdgeCases:
    """边界条件测试。"""

    def test_empty_source_returns_empty(self, parse_source, make_file_context):
        """空文件返回空列表。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source = parse_source("")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)
        assert symbols == [], f"Expected empty, got {len(symbols)} symbols"

    def test_nested_classes(self, parse_fixture, make_file_context):
        """嵌套类均被提取。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        class_names = {s.name for s in symbols if s.symbol_type == "CLASS"}
        assert "OuterClass" in class_names, "Missing OuterClass"
        assert "InnerClass" in class_names, "Missing InnerClass"

    def test_lambda_not_symbol(self, parse_fixture, make_file_context):
        """lambda 表达式不被提取为 Symbol。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        # lambda 赋值可能产生 VARIABLE 类型的 Symbol，但 implementation 不提取 VARIABLE
        for s in symbols:
            assert s.name != "sort_key" or s.symbol_type != "FUNCTION", \
                "lambda should not be extracted as FUNCTION"

    def test_syntax_error_graceful(self, parse_source, make_file_context):
        """语法错误文件不抛异常，返回空或部分结果。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source = parse_source("def broken(:\n    pass\n")
        ctx = make_file_context()

        try:
            symbols = extract_symbols(tree, source, ctx)
            # tree-sitter 仍会尝试解析，返回 ERROR 节点
            # 抽取器应跳过无法处理的节点，不崩溃
            assert isinstance(symbols, list), "should return list even on syntax error"
        except Exception as e:
            pytest.fail(f"extract_symbols raised exception on syntax error: {e}")

    def test_decorator_chain(self, parse_fixture, make_file_context):
        """装饰器链中的函数被提取。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        names = {s.name for s in symbols}
        assert "chained_decorated" in names, "Missing chained_decorated"

    def test_single_line_function(self, parse_fixture, make_file_context):
        """单行函数被提取。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        names = {s.name for s in symbols}
        assert "one_liner" in names, "Missing one_liner"

    def test_complex_signature(self, parse_fixture, make_file_context):
        """多行签名函数被提取，signature 非空。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        cs = [s for s in symbols if s.name == "complex_signature"]
        assert len(cs) == 1, f"Expected 1 complex_signature, got {len(cs)}"
        assert len(cs[0].signature) > 0, "signature should not be empty"
        assert "def " in cs[0].signature, "signature should contain def"

    def test_nonexistent_language_returns_empty(self, parse_source, make_file_context):
        """不支持的语言返回空列表。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source = parse_source("def foo(): pass\n")
        ctx = make_file_context(language="css")
        symbols = extract_symbols(tree, source, ctx)
        assert symbols == [], f"Expected empty for unsupported language, got {len(symbols)}"

    def test_empty_function_handled(self, parse_fixture, make_file_context):
        """空函数体不导致崩溃。"""
        from codegraph.extractors.symbol import extract_symbols

        tree, source, _ = parse_fixture("edge_cases.py")
        ctx = make_file_context()
        symbols = extract_symbols(tree, source, ctx)

        names = {s.name for s in symbols}
        # empty_function 应该存在（我们保留而非跳过）或至少不崩溃
        assert "empty_function" in names, "empty_function should be extracted"
