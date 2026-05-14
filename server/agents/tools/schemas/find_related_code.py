"""``find_related_code`` agent tool 输入/输出契约 —— per Phase Plan / ROADMAP -#3。
字段冻结（frozen=True / extra='forbid' / strict=True 三重防漂移），与 Phase Plan
``search_repository_code`` 同包风格。
- ``FindRelatedCodeInput``：三选一起点（``file_path`` / ``chunk_id`` / ``symbol_name``）+
 ``repository_id`` + ``relation_types`` + ``hops≤2`` + ``direction`` + ``limit``；
 ``@model_validator(mode='after')`` 守住"恰好一个起点"硬约束（per ROADMAP ）。
- ``NeighborOutput``：字段名顺序与 ``services.retrieval.types.NeighborMetadata`` 一致，
 ``reason`` ``min_length=1`` 静态保证非空（per ROADMAP ）。
- ``FindRelatedCodeOutput``：``neighbors`` + ``message``；空 ``neighbors`` 时用
 ``message`` 解释（"无关联代码" / "tool unavailable"），让 Agent 区分"查到了无邻居"
 与"工具失败"。
**Literal 字面值不 import** ``code_relations.models.EdgeType``：schemas 模块需在 Django
``apps.ready`` 之前可独立 import，避免 app loading 顺序耦合（per -PLAN
``key_links`` 注）。6 类边名手抄保持与 ORM ``TextChoices`` 双轨同步；Plan snapshot
测试会在 EdgeType 扩第 7 类边时立刻 fail 抓出漂移。
"""
from __future__ import annotations
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
RelationType = Literal[
 "CALL",
 "IMPORT",
 "SAME_FILE",
 "TEST_OF",
 "CO_CHANGED",
 "SEMANTIC",
]
"""与 ``code_relations.models.EdgeType`` 字面值双轨同步（不 import 避 Django 耦合）。"""
Direction = Literal["downstream", "upstream", "both"]
"""``downstream`` = 沿边正向；``upstream`` = 反向；``both`` = 双向合并（per work-item ）。"""
class FindRelatedCodeInput(BaseModel):
 """Agent tool ``find_related_code`` 输入契约（per ROADMAP / ）。
 三选一互斥起点：``file_path`` / ``chunk_id`` / ``symbol_name`` 恰好一个非 ``None``，
 否则 ``ValidationError`` 含 ``"exactly one"`` 关键字（方便 LLM 错误模式匹配）。
 """
 model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
 file_path: str | None = Field(
 default=None,
 description=(
 "起点文件路径（相对 repository 根）。命中后由 Plan tool 函数解析为该文件"
 "首 chunk 作为起点（per work-item ）。与 chunk_id / symbol_name 三选一。"
 ),
 )
 chunk_id: str | None = Field(
 default=None,
 description=(
 "起点 chunk UUID。最精准的起点形式（直接传给 HybridSearchService.find_related）。"
 "与 file_path / symbol_name 三选一。"
 ),
 )
 symbol_name: str | None = Field(
 default=None,
 description=(
 "起点符号名（如函数 / 类 / 方法名）。Plan 走 LocalProvider.lookup_symbols "
 "解析为所在文件 → chunk。与 file_path / chunk_id 三选一。"
 ),
 )
 repository_id: str | None = Field(
 default=None,
 description=(
 "目标仓库 UUID。chunk_id 跨 repo 语义上需限定单 repo 查询；None 时由 Plan "
 "tool 函数报错 '需要 repository_id'（per work-item ）。"
 ),
 )
 relation_types: list[RelationType] = Field(
 default=["CALL", "IMPORT", "TEST_OF"],
 description=(
 "图谱遍历关心的边类型；默认 ['CALL','IMPORT','TEST_OF']（强信号）。弱信号 "
 "SAME_FILE / CO_CHANGED / SEMANTIC 不默认开避免邻居稀释，需显式传入。"
 "Literal 字面值与 code_relations.models.EdgeType 双轨同步。"
 ),
 )
 hops: int = Field(
 default=1,
 ge=1,
 le=2,
 description=(
 "图谱遍历跳数上限；硬约束 ≤2，与 Phase HybridSearchService.find_related "
 "MAX_HOPS=2 双层守卫对齐（per ROADMAP ）。"
 ),
 )
 direction: Direction = Field(
 default="both",
 description=(
 "遍历方向：downstream（我依赖谁）/ upstream（谁依赖我）/ both（双向各取 "
 "limit/2 去重合并）。默认 both（per work-item ）。"
 ),
 )
 limit: int = Field(
 default=20,
 ge=1,
 le=100,
 description=(
 "返回邻居数量上限；默认 20。hops=2 时优先填 hop=1 再填 hop=2 "
 "（per work-item 跨 hops 行为）。"
 ),
 )
 @field_validator("chunk_id", "repository_id", mode="before")
 @classmethod
 def _validate_uuid_shape(cls, value: object) -> object:
 """守住 ``chunk_id`` / ``repository_id`` UUID 形态（per Phase）。
 Pydantic ``mode="before"`` 在类型转换前拦截非 UUID 字符串（典型 LLM 错觉：
 ``chunk_id="login_handler"`` / ``repository_id="repo-1"``），避免下游
 Django ORM ``UUIDField`` 在 query 执行时抛 ``ValueError: badly formed
 hexadecimal UUID string`` 冒泡到 agent runtime。
 ``None`` 直接放行（字段本身可空，互斥校验由 ``exactly_one_anchor`` 负责）。
 非字符串类型同样放行让默认类型校验报标准错误。
 """
 if value is None or not isinstance(value, str):
 return value
 try:
 uuid.UUID(value)
 except (ValueError, TypeError) as exc:
 raise ValueError(
 f"must be a valid UUID string (e.g. "
 f"'11111111-1111-1111-1111-111111111111'); got {value!r}"
 ) from exc
 return value
 @model_validator(mode="after")
 def exactly_one_anchor(self) -> FindRelatedCodeInput:
 """守住 ``file_path`` / ``chunk_id`` / ``symbol_name`` 恰好一个非 ``None``。
 Pydantic v2 ``mode='after'`` 让校验发生在字段类型转换之后；错误信息含
 ``"exactly one"`` 关键字便于 LLM 调用方做错误模式匹配（per ROADMAP ）。
 """
 anchors = [self.file_path, self.chunk_id, self.symbol_name]
 count = sum(1 for a in anchors if a is not None)
 if count != 1:
 raise ValueError(
 "exactly one of file_path / chunk_id / symbol_name must be provided; "
 f"got {count}"
 )
 return self
class NeighborOutput(BaseModel):
 """单个图谱邻居（per ROADMAP + work-item ）。
 字段名顺序与 ``services.retrieval.types.NeighborMetadata`` dataclass 完全一致，
 方便 Plan 通过 ``NeighborOutput(**asdict(neighbor_metadata))`` 单步装配。
 ``reason`` ``min_length=1`` 静态保证非空（Plan 透传 ``_explain_neighbor`` 输出
 不重写空字符串）。
 """
 model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
 chunk_id: str = Field(
 ...,
 description="邻居 chunk UUID。",
 )
 file_path: str = Field(
 ...,
 description="邻居 chunk 所在文件路径（相对 repository 根）。",
 )
 line_start: int | None = Field(
 default=None,
 description=(
 "邻居 chunk 起始行号（1-indexed）；Phase NeighborMetadata 允许 None "
 "（某些 chunk 无精确行号信息）。"
 ),
 )
 line_end: int | None = Field(
 default=None,
 description="邻居 chunk 终止行号（1-indexed）；nullable 同 line_start。",
 )
 edge_type: str = Field(
 ...,
 description=(
 "图谱边类型；运行时值来自 code_relations.models.EdgeType.values，"
 "字符串而非 Literal 是因为输出层不做枚举强约束（Phase API 已守过一遍）。"
 ),
 )
 weight: float = Field(
 ...,
 description="边权重（Phase ChunkEdge.weight）；用于 hop 内 weight 降序排序。",
 )
 reason: str = Field(
 ...,
 min_length=1,
 description=(
 "Phase ``_explain_neighbor(edge_type, source_payload)`` 输出的"
 "自然语言解释，例如 'caller of login_user' / 'test of src/auth.py'。"
 "min_length=1 静态保证非空（per ROADMAP ）。"
 ),
 )
 hop: int = Field(
 ...,
 ge=1,
 description="距离起点的跳数（1 或 2，与 FindRelatedCodeInput.hops 上限对齐）。",
 )
class FindRelatedCodeOutput(BaseModel):
 """Agent tool ``find_related_code`` 输出契约。
 ``neighbors`` 空时由 ``message`` 解释（"无关联代码" / "tool unavailable"），
 让 Agent 区分"查到了但无邻居"与"工具失败"两种空结果（per work-item ）。
 """
 model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
 neighbors: list[NeighborOutput] = Field(
 default_factory=list,
 description=(
 "图谱邻居列表，按 hop 升序 + weight 降序排（hop=1 强信号优先填充 limit）。"
 ),
 )
 message: str = Field(
 default="",
 description=(
 "空 neighbors 时的解释文本（例如 '无关联代码' / 'tool unavailable'）；"
 "neighbors 非空时通常为空串。"
 ),
 )
__all__ = [
 "Direction",
 "FindRelatedCodeInput",
 "FindRelatedCodeOutput",
 "NeighborOutput",
 "RelationType",
]
