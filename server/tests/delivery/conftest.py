"""delivery 测试包共享 fixture（Phase 32-02 编排端到端摄取守护）。

复刻 ``tests/knowledge/conftest.py`` 的摄取 seam（conftest 作用域不跨目录树，
故此处独立复刻同款 monkeypatch）：

- ``mock_embedding``：dense + sparse 向量化注入（不触真实 embedding）；
- ``mock_qdrant_client``：``QdrantService.get_client`` MagicMock seam；
- ``mock_ensure``：``ensure_delivery_knowledge_collection`` AsyncMock（不触 Qdrant）；
- ``mock_upsert``：``QdrantService.upsert_vectors_by_name`` 计数 seam；
- ``fake_git_platform``：``knowledge.diff_archive.get_git_platform_client`` 可配置 fake。

pytest 全局 ``--disable-socket`` 是第二道保险，漏 mock 的真实调用直接被拦截。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_qdrant_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """``QdrantService.get_client`` 的 MagicMock seam（非 autouse）。"""
    client = MagicMock()
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: client))
    return client


@pytest.fixture
def mock_ensure(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """``ensure_delivery_knowledge_collection`` 的 AsyncMock seam（不触 Qdrant）。"""
    ensure = AsyncMock()
    monkeypatch.setattr(
        "knowledge.ingestion.ensure_delivery_knowledge_collection", ensure
    )
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """``QdrantService.upsert_vectors_by_name`` 计数 seam：记录每批 point id 列表并返回 True。"""
    from services.qdrant_service import QdrantService

    calls: list[list[str]] = []

    def _fake(cls, name, pts):
        calls.append([p["id"] for p in pts])
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    return calls


@pytest.fixture
def mock_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """dense + sparse 向量化的一行注入 seam（摄取测试用，非 autouse）。"""
    from services.embedding import EmbeddingService
    from services.sparse_encoder import SparseEncoderService

    monkeypatch.setattr(
        EmbeddingService,
        "generate_embeddings_batch",
        AsyncMock(side_effect=lambda texts, **kw: [[0.1] * 1024 for _ in texts]),
    )
    monkeypatch.setattr(
        SparseEncoderService,
        "encode_batch",
        classmethod(lambda cls, texts: [{"indices": [1], "values": [0.5]} for _ in texts]),
    )


@pytest.fixture
def fake_git_platform(monkeypatch: pytest.MonkeyPatch):
    """``knowledge.diff_archive.get_git_platform_client`` 的可配置 fake seam。

    返回的 fake client 记录调用参数并按用例预置的 ``mr_result`` / ``branch_result``
    应答；monkeypatch 目标为 diff_archive 模块属性（from-import 绑定符号即模块属性）。
    """
    from services.git_platform.models import MRDiffResult

    class FakeGitPlatformClient:
        def __init__(self) -> None:
            self.mr_diff_calls: list[dict] = []
            self.branch_diff_calls: list[dict] = []
            self.mr_result = MRDiffResult(success=True, files=[])
            self.branch_result = MRDiffResult(success=True, files=[])

        async def get_merge_request_diff(
            self, mr_id: str, max_files: int = 50, max_diff_lines: int = 500
        ) -> MRDiffResult:
            self.mr_diff_calls.append(
                {"mr_id": mr_id, "max_files": max_files, "max_diff_lines": max_diff_lines}
            )
            return self.mr_result

        async def get_branch_diff(
            self,
            source_branch: str,
            target_branch: str,
            max_files: int = 50,
            max_diff_lines: int = 500,
        ) -> MRDiffResult:
            self.branch_diff_calls.append(
                {
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "max_files": max_files,
                    "max_diff_lines": max_diff_lines,
                }
            )
            return self.branch_result

    fake = FakeGitPlatformClient()
    monkeypatch.setattr(
        "knowledge.diff_archive.get_git_platform_client", lambda repository, token: fake
    )
    return fake
