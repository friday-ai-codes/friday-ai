"""``search_repository_code`` agent tool 输入/输出契约 —— per / / 。
字段冻结（frozen=True / extra="forbid" / strict=True 三重防漂移）：
- ``SearchRepositoryCodeInput``：``query`` / ``repository_ids`` / ``top_k`` /
 ``include_expansion``，与 Phase 灰度切换的"目标契约"对齐（**当前函数签名
 不一致**，per 注：本 phase 仅落 schema baseline，不动函数本身）。
- ``SearchRepositoryCodeOutput``：``final_context`` / ``tokens`` /
 ``source_layers`` / ``hit_count``，对齐 ``LayeredSearchResult`` /
 ``RagSearchResult`` 字段语义（per ）。
snapshot 守护：``tests/agents/test_tool_contracts.py`` 用 ``model_json_schema``
做字节级 diff，任何字段命名 / 类型 / 默认值 / 约束的变更都会让 contract 测试失败，
update fixture 是显式动作（防止下游 LLM tool spec 静默变化）。
"""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
class SearchRepositoryCodeInput(BaseModel):
 """Agent tool ``search_repository_code`` 输入契约（per ）。
 Phase 灰度切换时，``space_tools.py`` 的函数体会改用本模型解析 kwargs；
 本 phase 仅冻结字段定义，不动 ``search_repository_code`` 函数签名（per ）。
 """
 model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
 query: str = Field(
 ...,
 min_length=1,
 description="单一概念检索 query；非空字符串，由 LLM 调用方提供。",
 )
 repository_ids: list[str] | None = Field(
 default=None,
 description=(
 "目标仓库 UUID 列表。None 时由 HybridSearchService 内部走 L1 RepoRouter "
 "兜底；空列表代表显式跳过（GraphCapableProvider 路径下返回空 final_context）。"
 ),
 )
 top_k: int = Field(
 default=8,
 ge=1,
 le=50,
 description="返回的最大命中数量（默认 8，与 LLM tool 渲染上下文长度对齐）。",
 )
 include_expansion: bool = Field(
 default=True,
 description=(
 "是否启用 L4 图谱扩展（仅 GraphCapableProvider 路径生效；NullProvider "
 "路径自动忽略本字段）。"
 ),
 )
class SearchRepositoryCodeOutput(BaseModel):
 """Agent tool ``search_repository_code`` 输出契约（per ）。
 字段语义与 ``services.retrieval.types.RagSearchResult`` /
 ``codegraph.services.layered_search.LayeredSearchResult`` 对齐（包成 Pydantic
 模型供 LLM tool spec 渲染）。
 """
 model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
 final_context: str = Field(
 ...,
 description="L5 重组后的 markdown 上下文，作为 LLM 的 final tool result。",
 )
 tokens: int = Field(
 ...,
 ge=0,
 description="``final_context`` 的 tiktoken cl100k_base token 计数。",
 )
 source_layers: list[str] = Field(
 ...,
 description=(
 "实际产出数据的层标识列表（如 ['L2','L3','L4']）；NullProvider 路径下"
 "通常仅 ['L3'] 或 ['L3','L5']。"
 ),
 )
 hit_count: int = Field(
 ...,
 ge=0,
 description="跨层去重后的命中 chunk 数（与 LayeredSearchResult.total_chunks 等价）。",
 )
__all__ = [
 "SearchRepositoryCodeInput",
 "SearchRepositoryCodeOutput",
]
