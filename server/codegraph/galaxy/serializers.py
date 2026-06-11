"""Galaxy API schema 类型定义 —— 统一 node / edge / meta TypedDict。"""

from __future__ import annotations

from typing import Optional

from typing_extensions import NotRequired, TypedDict


class GalaxyNode(TypedDict):
    """统一节点 schema，适配 5 类节点类型。

    id 格式："{type_prefix}:{uuid}"
    type：chunk_registry | symbol | endpoint | api_wrapper | api_call_site
    """

    id: str
    type: str
    label: str
    repository_id: str
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    metadata: Optional[dict]
    degree: int


class GalaxyEdge(TypedDict):
    """统一边 schema，适配 ChunkEdge 8 类 + CrossRepoApiCall API_CALLS。"""

    id: str
    source: str
    target: str
    edge_type: str
    weight: float
    repository_id: str
    target_repository_id: Optional[str]
    metadata: Optional[dict]


class GalaxyNeighbor(TypedDict):
    """1-hop 邻居条目。"""

    node: GalaxyNode
    edge: GalaxyEdge
    direction: str  # "outgoing" | "incoming"


class GalaxyReference(TypedDict):
    """节点引用（ApiCallSite 调用 Endpoint 等）。"""

    type: str
    id: str
    label: str
    repository_id: str
    match_confidence: float


class GalaxyMeta(TypedDict):
    """Galaxy payload 元数据。"""

    total_nodes: int
    total_edges: int
    sampled: bool
    by_node_type: dict
    per_repo_hint: bool
    # 本次响应是否命中文件缓存（仅 L1 GalaxyView 设置）
    cache_hit: NotRequired[bool]


__all__ = [
    "GalaxyEdge",
    "GalaxyMeta",
    "GalaxyNeighbor",
    "GalaxyNode",
    "GalaxyReference",
]
