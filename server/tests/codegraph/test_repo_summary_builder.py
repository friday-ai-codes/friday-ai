"""RepoSummaryBuilder 单元测试 —— per contract/contract/contract。"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from codegraph.models import CallEdge, Endpoint, Symbol
from codegraph.services.repo_summary_builder import RepoSummaryBuilder
from repositories.models import AISummaryStatus, FileIndex, Repository
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_primary_symbols_top30():
    """验证 primary_symbols 提取 Top-30 按 outgoing_calls count 降序排列。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="test-summary-repo",
        git_url="https://example.com/test-summary.git",
        default_branch="main",
        ai_summary="Test AI summary for primary symbols",
    )
    # 创建 35 个 symbols（超过 Top-30 限制）
    for i in range(35):
        await sync_to_async(Symbol.objects.create)(
            repository=repo,
            name=f"func_{i:02d}",
            symbol_type="FUNCTION",
            file_path=f"src/module_{i // 5}.py",
            start_line=i * 10,
            end_line=i * 10 + 5,
        )

    # 为 func_00 创建 5 条出边，使其 outgoing_calls count 最高
    sym_func0 = await sync_to_async(Symbol.objects.get)(repository=repo, name="func_00")
    for i in range(5):
        await sync_to_async(CallEdge.objects.create)(
            repository=repo,
            caller_symbol=sym_func0,
            callee_name=f"external_func_{i}",
            call_type="DIRECT",
            line_number=i + 1,
        )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        point = call_args[0][1][0]
        payload = point["payload"]

        symbols_list = json.loads(payload["primary_symbols"])
        assert len(symbols_list) == 30
        # func_00 有最多的 outgoing_calls，应排第一
        assert symbols_list[0] == "func_00"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_api_domains_clustering():
    """验证 api_domains 为 URL 前缀聚类（取 '/' 分割的第一段有效路径）。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="api-domains-repo",
        git_url="https://example.com/api-domains.git",
        default_branch="main",
        ai_summary="API domains test summary",
    )
    endpoints_data = [
        ("GET", "/api/users/", "get_users", "FUNCTION_VIEW", "src/views.py", 10),
        ("POST", "/api/users/", "create_user", "FUNCTION_VIEW", "src/views.py", 25),
        ("GET", "/api/tasks/", "get_tasks", "FUNCTION_VIEW", "src/tasks.py", 15),
        ("GET", "/admin/health/", "health_check", "FUNCTION_VIEW", "src/admin.py", 5),
    ]
    for method, path, handler, vtype, fpath, line in endpoints_data:
        await sync_to_async(Endpoint.objects.create)(
            repository=repo,
            http_method=method,
            url_path=path,
            handler_name=handler,
            view_type=vtype,
            file_path=fpath,
            line_number=line,
        )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        domains = json.loads(payload["api_domains"])
        # api 出现 3 次 (api/users x2 + api/tasks x1)，admin 出现 1 次
        assert domains[0] == "api"
        assert "admin" in domains


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_tech_stack_from_file_index():
    """验证 tech_stack 从 FileIndex 扩展名分布提取百分比。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="tech-stack-repo",
        git_url="https://example.com/tech-stack.git",
        default_branch="main",
        ai_summary="Tech stack test summary",
    )
    files = [
        "src/module_0.py",
        "src/module_1.py",
        "src/module_2.py",
        "src/utils.js",
        "src/types.ts",
        "src/styles.css",
    ]
    import hashlib

    for fp in files:
        await sync_to_async(FileIndex.objects.create)(
            repository=repo,
            file_path=fp,
            file_hash=hashlib.sha256(fp.encode()).hexdigest(),
        )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        tech_stack = json.loads(payload["tech_stack"])
        # 3 py / 6 files = 50%
        assert tech_stack["py"] == 50.0
        # 1 each of js, ts, css = 16.7%
        assert tech_stack["js"] == pytest.approx(16.7, abs=0.1)
        assert tech_stack["ts"] == pytest.approx(16.7, abs=0.1)
        assert tech_stack["css"] == pytest.approx(16.7, abs=0.1)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_description_reuses_ai_summary():
    """验证 ai_summary 非空时复用为 description。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="desc-repo",
        git_url="https://example.com/desc.git",
        default_branch="main",
        ai_summary="This is an AI-generated summary of the repository.",
        ai_summary_status=AISummaryStatus.COMPLETED,
    )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        assert payload["description"] == "This is an AI-generated summary of the repository."


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_description_fallback():
    """验证 ai_summary 为空时使用 name + git_url 作为最小描述。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="fallback-repo",
        git_url="https://example.com/fallback.git",
        default_branch="main",
        ai_summary=None,
    )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        assert payload["description"] == "fallback-repo - https://example.com/fallback.git"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_vectors_in_point():
    """验证 point 包含 dense 和 sparse 向量。"""
    repo = await sync_to_async(Repository.objects.create)(
        name="vectors-repo",
        git_url="https://example.com/vectors.git",
        default_branch="main",
        ai_summary="Vectors test summary",
    )

    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        # 验证 dense vector
        assert "dense" in point["vector"]
        assert len(point["vector"]["dense"]) == 1024
        # 验证 sparse vector
        assert "sparse" in point["vector"]
        assert point["vector"]["sparse"] == {"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_is_classmethod_async_service():
    """验证 RepoSummaryBuilder 为纯 @classmethod async 服务类。"""
    cls = RepoSummaryBuilder
    # 验证 build 是 classmethod
    assert isinstance(cls.__dict__["build"], classmethod)
    # 验证没有实例方法（排除 dunder 和 classmethod/staticmethod）
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = type.__getattribute__(cls, name)
        if callable(attr) and not isinstance(attr, (classmethod, staticmethod)):
            # 检查是否在实例 dict 中（实例方法）还是类 dict 中
            if name in cls.__dict__:
                obj = cls.__dict__[name]
                if not isinstance(obj, (classmethod, staticmethod)):
                    pytest.fail(f"RepoSummaryBuilder 包含非 classmethod 方法: {name}")


# --- 使用 conftest fixtures 的集成测试 (Task 2) ---


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_with_fixtures_primary_symbols_top30(
    repo_for_summary, repo_symbols,
):
    """使用 conftest fixtures 验证 primary_symbols 提取 Top-30。"""
    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo_for_summary.id))

        assert result is True
        mock_upsert.assert_called_once()
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        symbols_list = json.loads(payload["primary_symbols"])
        assert len(symbols_list) == 30


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_with_fixtures_api_domains(
    repo_for_summary, repo_endpoints,
):
    """使用 conftest fixtures 验证 api_domains URL 前缀聚类。"""
    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo_for_summary.id))

        assert result is True
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        domains = json.loads(payload["api_domains"])
        assert domains[0] == "api"
        assert "admin" in domains


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_with_fixtures_tech_stack(
    repo_for_summary, repo_file_indexes,
):
    """使用 conftest fixtures 验证 tech_stack 扩展名百分比。"""
    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo_for_summary.id))

        assert result is True
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        tech_stack = json.loads(payload["tech_stack"])
        assert tech_stack["py"] == 50.0
        assert tech_stack["js"] == pytest.approx(16.7, abs=0.1)
        assert tech_stack["ts"] == pytest.approx(16.7, abs=0.1)
        assert tech_stack["css"] == pytest.approx(16.7, abs=0.1)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_with_fixtures_description_reuses_ai_summary(
    repo_for_summary,
):
    """使用 conftest fixture 验证 ai_summary 复用为 description。"""
    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo_for_summary.id))

        assert result is True
        point = mock_upsert.call_args[0][1][0]
        payload = point["payload"]
        assert payload["description"] == "Test AI summary for repo"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_build_with_fixtures_e2e_upsert(
    repo_for_summary, repo_symbols, repo_endpoints, repo_file_indexes,
):
    """E2E 测试：使用全部 fixtures 验证 build 流程调用了 Qdrant upsert。"""
    with (
        patch.object(EmbeddingService, "generate_embedding", new_callable=AsyncMock) as mock_emb,
        patch.object(SparseEncoderService, "encode", return_value={"indices": [1, 2, 3], "values": [0.1, 0.2, 0.3]}),
        patch.object(QdrantService, "ensure_repo_summaries_collection", return_value=True),
        patch.object(QdrantService, "upsert_vectors_by_name", return_value=True) as mock_upsert,
    ):
        mock_emb.return_value = [0.1] * 1024

        result = await RepoSummaryBuilder.build(str(repo_for_summary.id))

        assert result is True
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        # 验证 collection 名称
        assert call_args[0][0] == "repo_summaries"
        point = call_args[0][1][0]
        # 验证 point 包含 dense + sparse vector
        assert "dense" in point["vector"]
        assert "sparse" in point["vector"]
        assert len(point["vector"]["dense"]) == 1024
        # 验证 payload 包含所有必要字段
        payload = point["payload"]
        assert payload["repository_id"] == str(repo_for_summary.id)
        assert "repo_name" in payload
        assert "description" in payload
        assert "tech_stack" in payload
        assert "api_domains" in payload
        assert "primary_symbols" in payload
        assert "built_at" in payload
