"""initial implementation: endpoint_rag_writer 单元测试。

测试 work item Markdown 模板生成 + work item Qdrant payload 字段。
全部为非 integration 测试，通过 mock 隔离外部服务。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.endpoint_rag_writer import build_api_endpoint_md, write_endpoint_rag_docs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeEndpointData:
    """最小化 EndpointData 替身，避免引入 codegraph 依赖。"""

    http_method: str
    url_path: str | None
    handler_name: str
    file_path: str
    line_number: int
    view_type: str = "FUNCTION_VIEW"
    metadata: dict[str, Any] | None = field(default=None)


def _make_ep(
    method: str = "GET",
    path: str | None = "/api/test",
    handler: str = "myPkg.HandleTest",
    file: str = "handlers/test.go",
    line: int = 42,
) -> _FakeEndpointData:
    return _FakeEndpointData(
        http_method=method,
        url_path=path,
        handler_name=handler,
        file_path=file,
        line_number=line,
    )


# ---------------------------------------------------------------------------
# TestBuildApiEndpointMd（work item）
# ---------------------------------------------------------------------------


class TestBuildApiEndpointMd:
    """build_api_endpoint_md 模板生成。"""

    def test_basic_fields_present(self) -> None:
        md = build_api_endpoint_md(
            http_method="POST",
            url_path="/api/users",
            handler_name="userHandler.CreateUser",
            file_path="handlers/users.go",
            line_number=10,
            repo_name="study-course",
        )
        assert "POST" in md
        assert "/api/users" in md
        assert "userHandler.CreateUser" in md
        assert "handlers/users.go" in md
        assert "study-course" in md
        assert "10" in md

    def test_method_uppercase(self) -> None:
        md = build_api_endpoint_md(
            http_method="get",
            url_path="/ping",
            handler_name="health.Ping",
            file_path="handlers/health.go",
            line_number=1,
            repo_name="backend",
        )
        assert "GET" in md

    def test_signature_fallback_to_handler_name(self) -> None:
        md = build_api_endpoint_md(
            http_method="GET",
            url_path="/api/topics",
            handler_name="topicHandler.List",
            file_path="handlers/topic.go",
            line_number=5,
            repo_name="backend",
            signature="",
        )
        # signature 为空 → fallback 为 handler_name
        assert "topicHandler.List" in md

    def test_signature_used_when_provided(self) -> None:
        sig = "func (h *TopicHandler) List(c *gin.Context)"
        md = build_api_endpoint_md(
            http_method="GET",
            url_path="/api/topics",
            handler_name="topicHandler.List",
            file_path="handlers/topic.go",
            line_number=5,
            repo_name="backend",
            signature=sig,
        )
        assert sig in md

    def test_null_url_path_replaced(self) -> None:
        md = build_api_endpoint_md(
            http_method="GET",
            url_path="",
            handler_name="unknown.Handler",
            file_path="handlers/x.go",
            line_number=1,
            repo_name="repo",
        )
        assert "(unknown)" in md

    def test_markdown_has_header_section(self) -> None:
        md = build_api_endpoint_md(
            http_method="DELETE",
            url_path="/api/resource",
            handler_name="resHandler.Delete",
            file_path="handlers/resource.go",
            line_number=20,
            repo_name="svc",
        )
        assert md.startswith("# API Endpoint:")
        assert "## Function Signature" in md


# ---------------------------------------------------------------------------
# TestWriteEndpointRagDocs（work item）
# ---------------------------------------------------------------------------


class TestWriteEndpointRagDocs:
    """write_endpoint_rag_docs Qdrant 写入逻辑。"""

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self) -> None:
        with patch("services.endpoint_rag_writer.EmbeddingService") as mock_emb:
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[],
                repository_id="repo-001",
                repo_name="test-repo",
            )
        assert result == 0
        mock_emb.generate_embeddings_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_null_url_endpoints(self) -> None:
        ep_no_url = _make_ep(path=None)
        with patch("services.endpoint_rag_writer.EmbeddingService") as mock_emb:
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep_no_url, "")],
                repository_id="repo-001",
                repo_name="test-repo",
            )
        assert result == 0
        mock_emb.generate_embeddings_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_null_url_returns_zero(self) -> None:
        eps = [(_make_ep(path=None), ""), (_make_ep(path=None), "")]
        with patch("services.endpoint_rag_writer.EmbeddingService"):
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=eps,
                repository_id="repo-001",
                repo_name="test-repo",
            )
        assert result == 0

    @pytest.mark.asyncio
    async def test_calls_embedding_and_upsert(self) -> None:
        ep = _make_ep(method="POST", path="/api/users", handler="user.Create")
        fake_embedding = [0.1] * 384

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[fake_embedding],
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_upsert,
        ):
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-123",
                repo_name="backend",
            )

        assert result == 1
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        points: list[dict] = call_args[0][1]  # positional arg
        assert len(points) == 1
        payload = points[0]["payload"]
        # work item: content_type 字段
        assert payload["content_type"] == "api_endpoint"
        # work item: 关键字段都在 payload
        assert payload["http_method"] == "POST"
        assert payload["url_path"] == "/api/users"
        assert payload["handler_name"] == "user.Create"
        assert "content" in payload
        assert "POST" in payload["content"]
        assert "/api/users" in payload["content"]

    @pytest.mark.asyncio
    async def test_upsert_failure_returns_zero(self) -> None:
        ep = _make_ep()

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[[0.1] * 384],
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-x",
                repo_name="repo",
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_none_embedding_skipped(self) -> None:
        ep1 = _make_ep(path="/api/a", handler="h.A")
        ep2 = _make_ep(path="/api/b", handler="h.B")

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[[0.1] * 384, None],  # 第 2 个 embedding 为 None
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_upsert,
        ):
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep1, ""), (ep2, "")],
                repository_id="repo-x",
                repo_name="repo",
            )

        assert result == 1
        points = mock_upsert.call_args[0][1]
        assert len(points) == 1

    @pytest.mark.asyncio
    async def test_point_id_is_deterministic(self) -> None:
        ep = _make_ep(method="GET", path="/api/test", handler="h.Test")

        ids_collected: list[str] = []

        async def _capture_upsert(repo_id: str, points: list[dict]) -> bool:
            ids_collected.extend(p["id"] for p in points)
            return True

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[[0.1] * 384],
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                side_effect=_capture_upsert,
            ),
        ):
            await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-123",
                repo_name="backend",
            )
            await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-123",
                repo_name="backend",
            )

        assert len(ids_collected) == 2
        assert ids_collected[0] == ids_collected[1], "点 ID 应该在重索引时保持一致（幂等）"

    @pytest.mark.asyncio
    async def test_hybrid_mode_builds_dict_vector(self) -> None:
        ep = _make_ep()
        fake_embedding = [0.1] * 384
        fake_sparse = {"indices": [1, 2, 3], "values": [0.5, 0.3, 0.2]}

        captured_points: list[dict] = []

        async def _capture_upsert(repo_id: str, points: list[dict]) -> bool:
            captured_points.extend(points)
            return True

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[fake_embedding],
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                side_effect=_capture_upsert,
            ),
            patch(
                "services.sparse_encoder.SparseEncoderService.encode_batch",
                return_value=[fake_sparse],
            ),
        ):
            result = await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-h",
                repo_name="repo",
                hybrid_enabled=True,
            )

        assert result == 1
        assert len(captured_points) == 1
        vector = captured_points[0]["vector"]
        # hybrid 模式：vector 应为 dict，含 "dense" 键
        assert isinstance(vector, dict)
        assert "dense" in vector
        assert vector["dense"] == fake_embedding

    @pytest.mark.asyncio
    async def test_payload_contains_node_type_api_endpoint(self) -> None:
        ep = _make_ep()

        captured_points: list[dict] = []

        async def _capture(repo_id: str, points: list[dict]) -> bool:
            captured_points.extend(points)
            return True

        with (
            patch(
                "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[[0.2] * 384],
            ),
            patch(
                "services.endpoint_rag_writer._qdrant_upsert_endpoint_vectors",
                side_effect=_capture,
            ),
        ):
            await write_endpoint_rag_docs(
                endpoints_with_sigs=[(ep, "")],
                repository_id="repo-y",
                repo_name="repo",
            )

        payload = captured_points[0]["payload"]
        assert payload["node_type"] == "api_endpoint"
        assert payload["content_type"] == "api_endpoint"
