"""GraphWriter 单元测试 —— 验证写入/删除/重新索引/空 bundle 处理。

覆盖 Nyquist 维度 5（数据完整性）+ 维度 7（错误恢复）。
"""

import os

import pytest
import pytest_asyncio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")


@pytest_asyncio.fixture
async def test_repository():
    """创建测试用 Repository 实例。"""
    import uuid

    from repositories.models import Repository

    repo = await Repository.objects.acreate(
        id=uuid.uuid4(),
        name="test-graph-writer-repo",
        git_url="https://github.com/test/repo.git",
        default_branch="main",
    )
    yield repo
    # 清理
    await Repository.objects.filter(id=repo.id).adelete()


@pytest_asyncio.fixture
async def graph_writer():
    """返回 GraphWriter 实例。"""
    from codegraph.services.graph_writer import GraphWriter
    return GraphWriter()


def make_test_bundle(file_path="test.py"):
    """构造一个包含所有 4 维数据的 ExtractionBundle。"""
    from codegraph.extractors.base import (
        CallData,
        EndpointData,
        ExtractionBundle,
        ImportData,
        SymbolData,
    )

    return ExtractionBundle(
        file_path=file_path,
        language="python",
        symbols=[
            SymbolData(name="hello", symbol_type="FUNCTION", file_path=file_path,
                       start_line=3, end_line=5, signature="def hello():", is_async=False),
            SymbolData(name="MyClass", symbol_type="CLASS", file_path=file_path,
                       start_line=7, end_line=20, signature="class MyClass:"),
            SymbolData(name="method_a", symbol_type="METHOD", file_path=file_path,
                       start_line=9, end_line=11, signature="def method_a(self):"),
        ],
        imports=[
            ImportData(source_file=file_path, target_module="os",
                       imported_names=["os"], is_relative=False),
            ImportData(source_file=file_path, target_module="typing",
                       imported_names=["Optional", "List"], is_relative=False),
        ],
        calls=[
            CallData(caller_key=(file_path, "hello", 3), callee_name="print",
                     call_type="DIRECT", line_number=4),
            CallData(caller_key=(file_path, "method_a", 9), callee_name="len",
                     call_type="DIRECT", line_number=10),
            # 模块级调用（caller_key 不在 symbols 中）
            CallData(caller_key=(file_path, "__module__", 1), callee_name="super",
                     call_type="DIRECT", line_number=1),
        ],
        endpoints=[
            EndpointData(http_method="GET", url_path="/api/users/",
                         handler_name="views.user_list", view_type="FUNCTION_VIEW",
                         file_path="views.py", line_number=10),
        ],
    )


class TestGraphWriterWriteBundle:
    """write_bundle 正常路径测试。"""

    @pytest.mark.django_db(transaction=True)
    async def test_extract_and_write_graph_writes_in_isolated_thread_pool(
        self, test_repository, tmp_path
    ):
        """graph 写库必须跑在 thread_sensitive=False 的独立线程上：

        Django ORM async (aget/abulk_create/adelete) 默认 thread_sensitive=True，
        整个 ASGI 进程的所有 sync_to_async 调用共享一根线程串行执行。
        graph 阶段 4000+ 文件 × 多次 ORM 写入会把这根线程占满，HTTP 接口
        的 ORM 调用排队到 graph 完成才能拿到结果 → 用户体验"接口都待处理"。

        修复后 graph 阶段的实际写入由 GraphWriter.write_bundle_sync 承担，
        并通过独立线程池（thread_sensitive=False）调度，不抢 ASGI 请求线程。
        """
        import threading

        from codegraph.services.graph_writer import GraphWriter

        # repo 里放一个真实文件让抽取链跑通
        repo_root = tmp_path / "repo_root"
        rel_path = "pkg/sample.py"
        sample = repo_root / rel_path
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text("def fn():\n    return 1\n")

        outer_thread = threading.get_ident()
        graph_writer_threads: list[int] = []

        original_sync = GraphWriter.write_bundle_sync

        def _spy_sync(self, repository_id, bundle, *, branch_name=""):
            graph_writer_threads.append(threading.get_ident())
            return original_sync(self, repository_id, bundle, branch_name=branch_name)

        from services.indexer import IndexerService

        # 用 monkeypatch 替代：直接 setattr 到类
        GraphWriter.write_bundle_sync = _spy_sync  # type: ignore[assignment]
        try:
            indexer = IndexerService(str(test_repository.id))
            await indexer._extract_and_write_graph(
                repo_path=str(repo_root),
                file_paths=[rel_path],
                repository_id=str(test_repository.id),
            )
        finally:
            GraphWriter.write_bundle_sync = original_sync  # type: ignore[assignment]

        assert graph_writer_threads, "write_bundle_sync 必须被调用"
        for tid in graph_writer_threads:
            assert tid != outer_thread, (
                f"graph 写入必须跑在独立线程，实际 tid={tid} 与 ASGI 主线程"
                f" {outer_thread} 相同 → 仍会卡住 HTTP 接口"
            )

    @pytest.mark.django_db(transaction=True)
    async def test_extract_and_write_graph_normalizes_absolute_paths(
        self, test_repository, tmp_path
    ):
        """_extract_and_write_graph 收到绝对路径（位于 repo_path 之下）时
        必须 normalize 为相对路径再入库，避免 DB 里出现
        /var/folders/.../friday_index_xxx/packages/... 这种 tmp 路径泄漏。
        """
        from codegraph.models import Symbol
        from services.indexer import IndexerService

        # 准备一个临时 "repo" 目录，里面放一个 python 文件
        repo_root = tmp_path / "repo_root"
        rel_path = "packages/foo/bar.py"
        sample = repo_root / rel_path
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text("def hello():\n    return 1\n")

        indexer = IndexerService(str(test_repository.id))
        # 故意传入绝对路径，模拟 run_full_index 直接把 scan_directory 结果传过来的 bug
        await indexer._extract_and_write_graph(
            repo_path=str(repo_root),
            file_paths=[str(sample)],
            repository_id=str(test_repository.id),
        )

        symbols = [
            s
            async for s in Symbol.objects.filter(repository=test_repository)
        ]
        assert symbols, "至少要写入 1 个 Symbol（hello 函数）"
        for sym in symbols:
            assert not sym.file_path.startswith("/"), (
                f"file_path 必须是相对路径，实际：{sym.file_path}"
            )
            assert sym.file_path == rel_path, (
                f"file_path 期望 {rel_path}，实际 {sym.file_path}"
            )

    @pytest.mark.django_db(transaction=True)
    async def test_write_bundle_resolves_caller_when_start_line_is_zero(
        self, test_repository, graph_writer
    ):
        """calls extractor 写 caller_key=(file, name, 0) 表示 'unknown line'，
        writer 必须 fallback 到 (file_path, name) 匹配 caller，不能因 start_line
        不一致就把所有 call 当模块级调用 skip 掉（线上实测：4911 文件 → calls=0）。
        """
        from codegraph.extractors.base import (
            CallData,
            ExtractionBundle,
            SymbolData,
        )
        from codegraph.models import CallEdge

        file_path = "src/sample.py"
        bundle = ExtractionBundle(
            file_path=file_path,
            language="python",
            symbols=[
                SymbolData(
                    name="real_caller",
                    symbol_type="FUNCTION",
                    file_path=file_path,
                    start_line=12,
                    end_line=20,
                    signature="def real_caller():",
                ),
            ],
            calls=[
                CallData(
                    caller_key=(file_path, "real_caller", 0),
                    callee_name="print",
                    call_type="DIRECT",
                    line_number=15,
                ),
            ],
        )
        stats = await graph_writer.write_bundle(str(test_repository.id), bundle)

        assert stats["calls"] == 1, (
            "caller_key start_line=0 必须能通过 (file_path, name) 兜底匹配到"
            f" Symbol，实际 stats={stats}"
        )
        edges = [
            e
            async for e in CallEdge.objects.filter(repository=test_repository)
        ]
        assert len(edges) == 1
        assert edges[0].callee_name == "print"

    @pytest.mark.django_db(transaction=True)
    async def test_write_bundle_creates_all_entities(self, test_repository, graph_writer):
        """验证 write_bundle 写入后，四个模型均有记录。"""
        from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol

        bundle = make_test_bundle()
        file_path = bundle.file_path
        stats = await graph_writer.write_bundle(str(test_repository.id), bundle)

        assert stats["symbols"] == 3, f"Expected 3 symbols, got {stats}"
        assert stats["imports"] == 2
        # work item：3 条边全部落库（hello/method_a 函数内边 + 模块级 super 边），
        # 模块级调用不再被跳过。
        assert stats["calls"] == 3, f"Expected 3 calls (含模块级边), got {stats}"
        assert stats["endpoints"] == 1

        # 验证 DB 记录数
        sym_count = await Symbol.objects.filter(repository=test_repository).acount()
        assert sym_count == 3, f"DB symbol count: {sym_count}"

        imp_count = await ImportEdge.objects.filter(repository=test_repository).acount()
        assert imp_count == 2

        call_count = await CallEdge.objects.filter(repository=test_repository).acount()
        assert call_count == 3

        ep_count = await Endpoint.objects.filter(repository=test_repository).acount()
        assert ep_count == 1

        # work item 闭合：函数内边（caller_symbol_id is not None）的 caller_file
        # 也被同步填充为 caller 所在文件（非仅模块级边填 caller_file）。
        internal_edge = await CallEdge.objects.filter(
            repository=test_repository, caller_symbol_id__isnull=False
        ).afirst()
        assert internal_edge is not None, "应存在至少一条函数内 CallEdge"
        assert internal_edge.caller_file == file_path, (
            f"函数内边 caller_file 期望 {file_path}，实际 {internal_edge.caller_file!r}"
        )

    @pytest.mark.django_db(transaction=True)
    async def test_write_bundle_symbol_fields_correct(self, test_repository, graph_writer):
        """验证 Symbol 字段正确写入。"""
        from codegraph.models import Symbol

        bundle = make_test_bundle()
        await graph_writer.write_bundle(str(test_repository.id), bundle)

        sym = await Symbol.objects.filter(
            repository=test_repository, name="hello"
        ).afirst()
        assert sym is not None, "Symbol 'hello' not found"
        assert sym.symbol_type == "FUNCTION"
        assert sym.start_line == 3
        assert sym.end_line == 5
        assert sym.signature == "def hello():"
        assert sym.is_async is False

    @pytest.mark.django_db(transaction=True)
    async def test_write_bundle_calledge_fk_resolved(self, test_repository, graph_writer):
        """验证 CallEdge 的 caller_symbol FK 正确关联到 Symbol。"""
        from codegraph.models import CallEdge

        bundle = make_test_bundle()
        await graph_writer.write_bundle(str(test_repository.id), bundle)

        call = await CallEdge.objects.filter(
            repository=test_repository, callee_name="print"
        ).select_related("caller_symbol").afirst()
        assert call is not None, "CallEdge 'print' not found"
        assert call.caller_symbol is not None, "caller_symbol FK should be set"
        assert call.caller_symbol.name == "hello", \
            f"Expected caller 'hello', got '{call.caller_symbol.name}'"
        assert call.call_type == "DIRECT"
        assert call.line_number == 4

    @pytest.mark.django_db(transaction=True)
    async def test_module_level_call_written(self, test_repository, graph_writer):
        """模块级调用（caller_key 不在 symbol_id_map 中）写成 caller_symbol=NULL 的边。

        work item / Pitfall 3：make_test_bundle 含一条 caller_key=(file,"__module__",1)
        callee="super" 的模块级 CallData，改造后应落库为 caller_symbol_id is None +
        caller_file == file_path 的边（而非被 skip）。
        """
        from codegraph.models import CallEdge

        bundle = make_test_bundle()
        file_path = bundle.file_path
        stats = await graph_writer.write_bundle(str(test_repository.id), bundle)

        # 3 条边全部落库（含模块级 super 边）
        assert stats["calls"] == 3, \
            f"Module-level call should be written, got {stats['calls']} calls"

        module_edge = await CallEdge.objects.filter(
            repository=test_repository, callee_name="super"
        ).afirst()
        assert module_edge is not None, "模块级边（callee=super）应落库"
        assert module_edge.caller_symbol_id is None, (
            "模块级边 caller_symbol_id 应为 None，实际"
            f" {module_edge.caller_symbol_id}"
        )
        assert module_edge.caller_file == file_path, (
            f"模块级边 caller_file 期望 {file_path}，实际 {module_edge.caller_file!r}"
        )

    @pytest.mark.django_db(transaction=True)
    async def test_reindex_module_level_edge_not_duplicated(
        self, test_repository, graph_writer
    ):
        """同一 file_path 连续 write_bundle 两次，模块级边不翻倍（Pitfall 2）。

        模块级边 caller_symbol=NULL 不被 Symbol delete 的 CASCADE 清理，依赖第一步
        新增的 by-caller_file 显式删除保证幂等。二次写入后 caller_symbol__isnull=True
        的边数量须保持不变（=1），证明 by-caller_file 删除生效。
        """
        from codegraph.models import CallEdge

        bundle = make_test_bundle()

        await graph_writer.write_bundle(str(test_repository.id), bundle)
        first_module_count = await CallEdge.objects.filter(
            repository=test_repository, caller_symbol__isnull=True
        ).acount()
        assert first_module_count == 1, (
            f"首次写入应有 1 条模块级边，实际 {first_module_count}"
        )

        # 第二次写入同一文件（模拟重新索引）
        await graph_writer.write_bundle(str(test_repository.id), bundle)
        second_module_count = await CallEdge.objects.filter(
            repository=test_repository, caller_symbol__isnull=True
        ).acount()
        assert second_module_count == 1, (
            "重新索引后模块级边不应翻倍（by-caller_file 删除幂等），"
            f"实际 {second_module_count}"
        )


class TestGraphWriterReindex:
    """重新索引幂等性测试（per H.4）。"""

    @pytest.mark.django_db(transaction=True)
    async def test_reindex_replaces_old_records(self, test_repository, graph_writer):
        """同一文件重新索引时，旧记录被清除，新记录替换。"""
        from codegraph.models import Symbol

        bundle = make_test_bundle()
        await graph_writer.write_bundle(str(test_repository.id), bundle)
        first_count = await Symbol.objects.filter(repository=test_repository).acount()
        assert first_count == 3

        # 第二次写入同一个 file_path（模拟重新索引）
        await graph_writer.write_bundle(str(test_repository.id), bundle)
        second_count = await Symbol.objects.filter(repository=test_repository).acount()
        assert second_count == 3, \
            f"Expected 3 after reindex, got {second_count}（旧记录未被清理）"

    @pytest.mark.django_db(transaction=True)
    async def test_reindex_different_file_does_not_affect_other(self, test_repository, graph_writer):
        """不同文件的重新索引互不影响。"""
        from codegraph.models import Symbol

        bundle_a = make_test_bundle("a.py")
        bundle_b = make_test_bundle("b.py")

        await graph_writer.write_bundle(str(test_repository.id), bundle_a)
        await graph_writer.write_bundle(str(test_repository.id), bundle_b)

        count_a = await Symbol.objects.filter(
            repository=test_repository, file_path="a.py"
        ).acount()
        count_b = await Symbol.objects.filter(
            repository=test_repository, file_path="b.py"
        ).acount()
        assert count_a == 3, f"a.py should have 3 symbols, got {count_a}"
        assert count_b == 3, f"b.py should have 3 symbols, got {count_b}"


class TestGraphWriterEmptyBundle:
    """空 bundle / 空文件测试。"""

    @pytest.mark.django_db(transaction=True)
    async def test_empty_bundle_no_error(self, test_repository, graph_writer):
        """空 bundle（所有 list 为空）不抛异常。"""
        from codegraph.extractors.base import ExtractionBundle

        bundle = ExtractionBundle(file_path="empty.py", language="python")
        stats = await graph_writer.write_bundle(str(test_repository.id), bundle)

        assert stats["symbols"] == 0
        assert stats["imports"] == 0
        assert stats["calls"] == 0
        assert stats["endpoints"] == 0
