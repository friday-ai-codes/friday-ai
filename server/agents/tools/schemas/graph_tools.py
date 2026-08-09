"""``impact_analysis`` / ``trace_call_path`` 对话工具输入契约（Phase 122 IMPACT-06）。

上下界必须与 MCP ``ImpactAnalysisRequestSerializer`` /
``TraceCallPathRequestSerializer`` **同表**——两面参数域一旦分叉，同一个查询在
两面就会得到不同结果，D-21 的「同源」就断在这一层。

⛔ 零 Django import：本模块需在 ``apps.ready()`` 之前可独立 import。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImpactAnalysisToolInput(BaseModel):
    """``impact_analysis`` 对话工具输入契约。

    字段与上下界对齐 ``mcp_tools.serializers.ImpactAnalysisRequestSerializer``。
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    repository_id: str = Field(description="目标仓库 UUID（必填）")
    branch: str | None = Field(
        default=None,
        description="查询分支；缺省 / 空 / 与 base 相同则走 base 图",
    )
    symbol_id: str | None = Field(
        default=None,
        description="符号 UUID；与 symbol 必须且只能提供其一",
    )
    symbol: str = Field(
        default="",
        description="符号名；与 symbol_id 必须且只能提供其一",
    )
    file_path: str = Field(
        default="",
        description="可选：文件路径，用于收窄同名符号",
    )
    symbol_type: str = Field(
        default="",
        description="可选：符号类型（如 function / class），用于收窄同名符号",
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=3,
        description="影响面遍历深度上界（1–3，与 MCP 同表）",
    )
    min_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="边置信度下限（0.0–1.0）",
    )
    include_low_confidence: bool = Field(
        default=False,
        description="是否纳入低置信度边",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=200,
        description="单次响应条数硬上限（1–200）",
    )
    max_cross_repo_hops: int = Field(
        default=1,
        ge=0,
        le=1,
        description="跨仓跳数上界（0–1，D-11 不递归）",
    )
    exclude_test_files: bool = Field(
        default=False,
        description="是否排除测试文件上的影响节点",
    )

    @model_validator(mode="after")
    def _require_symbol_xor(self) -> ImpactAnalysisToolInput:
        has_id = bool(self.symbol_id)
        has_name = bool((self.symbol or "").strip())
        if has_id == has_name:
            raise ValueError("必须且只能提供 symbol_id 或 symbol 之一")
        return self


class TraceCallPathToolInput(BaseModel):
    """``trace_call_path`` 对话工具输入契约。

    字段与上下界对齐 ``mcp_tools.serializers.TraceCallPathRequestSerializer``。
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    repository_id: str = Field(description="目标仓库 UUID（必填）")
    branch: str | None = Field(
        default=None,
        description="查询分支；缺省 / 空 / 与 base 相同则走 base 图",
    )
    source_symbol_id: str | None = Field(
        default=None,
        description="起点符号 UUID；与 source 必须且只能提供其一",
    )
    source: str = Field(
        default="",
        description="起点符号名；与 source_symbol_id 必须且只能提供其一",
    )
    source_file_path: str = Field(
        default="",
        description="可选：起点文件路径，用于收窄同名符号",
    )
    target_symbol_id: str | None = Field(
        default=None,
        description="终点符号 UUID；与 target 必须且只能提供其一",
    )
    target: str = Field(
        default="",
        description="终点符号名；与 target_symbol_id 必须且只能提供其一",
    )
    target_file_path: str = Field(
        default="",
        description="可选：终点文件路径，用于收窄同名符号",
    )
    min_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="边置信度下限（0.0–1.0）",
    )
    include_low_confidence: bool = Field(
        default=False,
        description="是否纳入低置信度边",
    )
    alt_path_cap: int = Field(
        default=10,
        ge=1,
        le=50,
        description="等长备选路径条数上限（1–50）",
    )

    @model_validator(mode="after")
    def _require_endpoints_xor(self) -> TraceCallPathToolInput:
        has_source_id = bool(self.source_symbol_id)
        has_source = bool((self.source or "").strip())
        if has_source_id == has_source:
            raise ValueError("必须且只能提供 source_symbol_id 或 source 之一")
        has_target_id = bool(self.target_symbol_id)
        has_target = bool((self.target or "").strip())
        if has_target_id == has_target:
            raise ValueError("必须且只能提供 target_symbol_id 或 target 之一")
        return self


__all__ = ["ImpactAnalysisToolInput", "TraceCallPathToolInput"]
