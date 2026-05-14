"""``find_related_code`` agent tool 函数体行为单测 —— per Phase Plan Task 1。
测试目标（plan must_haves ≥ 9 条）：
1. ``test_chunk_id_path_passes_through_directly`` —— chunk_id 路径 start_chunk_id 直传
2. ``test_file_path_resolves_to_first_chunk`` —— file_path 路径走 ChunkRegistry.afirst
3. ``test_symbol_name_resolves_via_provider`` —— symbol_name 路径走 provider.lookup_symbols
4. ``test_missing_repository_id_returns_error`` —— repository_id is None
5. ``test_pydantic_validation_error_returns_toolresult`` —— 0 起点 → ToolResult.error
6. ``test_empty_neighbors_returns_message`` —— 空邻居 message="无关联代码"
7. ``test_reason_field_passes_through_non_empty`` —— reason 透传 Phase _explain_neighbor
8. ``test_neighbor_output_field_order_aligned`` —— NeighborOutput vs NeighborMetadata 字段顺序
9. ``test_hybrid_search_call_args_passthrough`` —— hops/direction/relation_types/limit 透传
10. ``test_symbol_name_no_match_returns_error`` —— lookup_symbols 空 → 结构化 error
11. ``test_file_path_not_found_returns_error`` —— ChunkRegistry afirst=None → 结构化 error
12. ``test_symbol_name_null_provider_returns_error`` —— NullProvider (无 lookup_symbols) → 结构化 error
per work-item （reason 透传不重写）+ PLAN must_haves（mock HybridSearchService /
ChunkRegistry / Provider，不依赖真实 Qdrant / DB）。
"""
from __future__ import annotations
import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.retrieval.types import NeighborMetadata
# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_neighbor(
 chunk_id: str = "11111111-1111-1111-1111-111111111111",
 file_path: str = "src/auth.py",
 line_start: int | None = 10,
 line_end: int | None = 20,
 edge_type: str = "CALL",
 weight: float = 0.8,
 reason: str = "caller of foo via direct call",
 hop: int = 1,
) -> NeighborMetadata:
 """构造 NeighborMetadata 测试夹具，默认字段非空便于透传断言。"""
 return NeighborMetadata(
 chunk_id=chunk_id,
 file_path=file_path,
 line_start=line_start,
 line_end=line_end,
 edge_type=edge_type,
 weight=weight,
 reason=reason,
 hop=hop,
 )
def _patch_chunk_registry_afirst(monkeypatch: pytest.MonkeyPatch, return_value: Any) -> MagicMock:
 """patch ``ChunkRegistry.objects.filter(...).order_by(...).afirst`` 链。
 返回最末端 ``afirst`` 的 AsyncMock，方便断言 ``filter`` 参数链路。
 """
 afirst_mock = AsyncMock(return_value=return_value)
 order_by_mock = MagicMock
 order_by_mock.afirst = afirst_mock
 filter_mock = MagicMock
 filter_mock.order_by = MagicMock(return_value=order_by_mock)
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(return_value=filter_mock)
 from code_relations import models as cr_models
 monkeypatch.setattr(cr_models.ChunkRegistry, "objects", objects_mock)
 return afirst_mock
# ---------------------------------------------------------------------------
# Section 1: chunk_id 起点路径
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chunk_id_path_passes_through_directly -> None:
 """chunk_id 提供 → start_chunk_id 直传给 HybridSearchService.find_related。"""
 from agents.tools.find_related_code import find_related_code
 chunk_id = "abcdef00-0000-0000-0000-000000000000"
 fake_find_related = AsyncMock(return_value=[_make_neighbor(chunk_id="neighbor-1")])
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 result = await find_related_code(chunk_id=chunk_id, repository_id="repo-1")
 assert result.success is True
 fake_find_related.assert_awaited_once
 assert fake_find_related.await_args is not None
 call_kwargs = fake_find_related.await_args.kwargs
 call_args = fake_find_related.await_args.args
 # 第一个位置参数应为 start_chunk_id
 assert call_args[0] == chunk_id
 assert call_kwargs["repo_ids"] == ["repo-1"]
 assert result.metadata.get("resolved_via") == "chunk_id"
# ---------------------------------------------------------------------------
# Section 2: file_path 起点路径
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_file_path_resolves_to_first_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
 """file_path 提供 → ChunkRegistry.afirst 命中 → start_chunk_id = 该 chunk_id。"""
 from agents.tools.find_related_code import find_related_code
 resolved_chunk_id = "reguuid0-0000-0000-0000-000000000000"
 fake_reg = MagicMock
 fake_reg.chunk_id = resolved_chunk_id
 afirst_mock = _patch_chunk_registry_afirst(monkeypatch, fake_reg)
 fake_find_related = AsyncMock(return_value=[_make_neighbor])
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 result = await find_related_code(file_path="src/auth.py", repository_id="repo-1")
 assert result.success is True
 afirst_mock.assert_awaited_once
 assert fake_find_related.await_args is not None
 assert fake_find_related.await_args.args[0] == resolved_chunk_id
 assert result.metadata.get("resolved_via") == "file_path"
@pytest.mark.asyncio
async def test_file_path_not_found_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
 """file_path 提供但 ChunkRegistry.afirst 返回 None → 结构化 error。"""
 from agents.tools.find_related_code import find_related_code
 _patch_chunk_registry_afirst(monkeypatch, None)
 fake_find_related = AsyncMock
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 result = await find_related_code(
 file_path="src/missing.py", repository_id="repo-1"
 )
 assert result.success is False
 assert result.error is not None
 assert "no chunk found for file_path" in result.error
 fake_find_related.assert_not_awaited
# ---------------------------------------------------------------------------
# Section 3: symbol_name 起点路径
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_symbol_name_resolves_via_provider(monkeypatch: pytest.MonkeyPatch) -> None:
 """symbol_name 提供 → provider.lookup_symbols 命中 → ChunkRegistry 取包含 line 的 chunk。"""
 from agents.tools.find_related_code import find_related_code
 fake_reg = MagicMock
 fake_reg.chunk_id = "sym-chunk-uuid-0000-0000-0000-00000000"
 afirst_mock = _patch_chunk_registry_afirst(monkeypatch, fake_reg)
 provider = MagicMock
 provider.capabilities = frozenset({"symbol_lookup"})
 provider.lookup_symbols = AsyncMock(
 return_value=[
 {
 "symbol_id": "sym-1",
 "name": "MyClass",
 "symbol_type": "class",
 "file_path": "src/auth.py",
 "start_line": 12,
 "end_line": 30,
 }
 ]
 )
 fake_find_related = AsyncMock(return_value=[_make_neighbor])
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch(
 "agents.tools.find_related_code.get_provider", return_value=provider
 ),
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 result = await find_related_code(symbol_name="MyClass", repository_id="repo-1")
 assert result.success is True
 provider.lookup_symbols.assert_awaited_once
 afirst_mock.assert_awaited
 assert fake_find_related.await_args is not None
 assert fake_find_related.await_args.args[0] == fake_reg.chunk_id
 assert result.metadata.get("resolved_via") == "symbol_name"
@pytest.mark.asyncio
async def test_symbol_name_no_match_returns_error -> None:
 """symbol_name 提供但 lookup_symbols 返回空列表 → 结构化 error。"""
 from agents.tools.find_related_code import find_related_code
 provider = MagicMock
 provider.capabilities = frozenset({"symbol_lookup"})
 provider.lookup_symbols = AsyncMock(return_value=)
 fake_find_related = AsyncMock
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider", return_value=provider),
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 result = await find_related_code(
 symbol_name="DoesNotExist", repository_id="repo-1"
 )
 assert result.success is False
 assert result.error is not None
 assert "no symbol matched" in result.error
 fake_find_related.assert_not_awaited
@pytest.mark.asyncio
async def test_symbol_name_null_provider_returns_error -> None:
 """provider 不具备 lookup_symbols capability（NullProvider）→ 结构化 error 不抛 AttributeError。"""
 from agents.tools.find_related_code import find_related_code
 # NullProvider 风格：只有 health_check，没有 lookup_symbols
 provider = MagicMock(spec=["capabilities", "health_check"])
 provider.capabilities = frozenset
 fake_find_related = AsyncMock
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider", return_value=provider),
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 result = await find_related_code(
 symbol_name="MyClass", repository_id="repo-1"
 )
 assert result.success is False
 assert result.error is not None
 assert "SymbolCapableProvider" in result.error or "symbol lookup" in result.error
 fake_find_related.assert_not_awaited
# ---------------------------------------------------------------------------
# Section 4: repository_id 缺失 / Pydantic 校验失败
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_repository_id_returns_error -> None:
 """仅 chunk_id 但 repository_id=None → ToolResult.error 含 'repository_id is required'。"""
 from agents.tools.find_related_code import find_related_code
 result = await find_related_code(
 chunk_id="abcdef00-0000-0000-0000-000000000000",
 repository_id=None,
 )
 assert result.success is False
 assert result.error is not None
 assert "repository_id is required" in result.error
@pytest.mark.asyncio
async def test_pydantic_validation_error_returns_toolresult -> None:
 """0 起点（全 None）→ Pydantic ValidationError 走 ToolResult.error 不冒泡。"""
 from agents.tools.find_related_code import find_related_code
 result = await find_related_code(
 file_path=None, chunk_id=None, symbol_name=None, repository_id="repo-1"
 )
 assert result.success is False
 assert result.error is not None
 assert "exactly one" in result.error.lower
# ---------------------------------------------------------------------------
# Section 5: 输出装配 —— 空邻居 / reason 透传 / 字段顺序对齐
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_neighbors_returns_message -> None:
 """find_related 返 → ToolResult.output.data.message == '无关联代码'，neighbors=。"""
 from agents.tools.find_related_code import find_related_code
 fake_find_related = AsyncMock(return_value=)
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 result = await find_related_code(
 chunk_id="abcdef00-0000-0000-0000-000000000000",
 repository_id="repo-1",
 )
 assert result.success is True
 data = result.output["data"]
 assert data["neighbors"] ==
 assert data["message"] == "无关联代码"
 assert result.metadata["total_neighbors"] == 0
@pytest.mark.asyncio
async def test_reason_field_passes_through_non_empty -> None:
 """Phase _explain_neighbor 模板输出的 reason 必须原样透传，**禁止重写**。"""
 from agents.tools.find_related_code import find_related_code
 custom_reason = "caller of login_user via direct call"
 fake_find_related = AsyncMock(
 return_value=[_make_neighbor(reason=custom_reason)]
 )
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 result = await find_related_code(
 chunk_id="abcdef00-0000-0000-0000-000000000000",
 repository_id="repo-1",
 )
 assert result.success is True
 neighbors_out = result.output["data"]["neighbors"]
 assert len(neighbors_out) == 1
 assert neighbors_out[0]["reason"] == custom_reason
def test_neighbor_output_field_order_aligned -> None:
 """NeighborOutput 字段顺序与 NeighborMetadata dataclass 完全一致（list equality）。"""
 from agents.tools.schemas.find_related_code import NeighborOutput
 dataclass_fields = [f.name for f in dataclasses.fields(NeighborMetadata)]
 pydantic_fields = list(NeighborOutput.model_fields.keys)
 assert pydantic_fields == dataclass_fields, (
 f"NeighborOutput pydantic fields {pydantic_fields} 与 "
 f"NeighborMetadata dataclass fields {dataclass_fields} 顺序漂移；"
 "Plan 装配 NeighborOutput(**asdict(neighbor)) 依赖同序约定。"
 )
# ---------------------------------------------------------------------------
# Section 6: HybridSearchService 参数透传契约
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hybrid_search_call_args_passthrough -> None:
 """hops/direction/relation_types/limit 必须完全透传给 HybridSearchService.find_related。"""
 from agents.tools.find_related_code import find_related_code
 fake_find_related = AsyncMock(return_value=)
 with (
 patch("agents.tools.find_related_code.HybridSearchService") as mock_hss_cls,
 patch("agents.tools.find_related_code.get_provider") as mock_get_provider,
 ):
 mock_hss_cls.return_value.find_related = fake_find_related
 mock_get_provider.return_value = MagicMock
 await find_related_code(
 chunk_id="abcdef00-0000-0000-0000-000000000000",
 repository_id="repo-1",
 hops=2,
 direction="upstream",
 relation_types=["CALL"],
 limit=5,
 )
 fake_find_related.assert_awaited_once
 assert fake_find_related.await_args is not None
 kwargs = fake_find_related.await_args.kwargs
 assert kwargs["hops"] == 2
 assert kwargs["direction"] == "upstream"
 assert kwargs["relation_types"] == ["CALL"]
 assert kwargs["limit"] == 5
 assert kwargs["repo_ids"] == ["repo-1"]
