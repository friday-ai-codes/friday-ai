"""仓库能力树的服务端业务校验（PageIndex 化，fail-closed）。

task 容器侧 submit_summary 工具的 JSON Schema 只能校验字段类型；本模块负责
JSON Schema 校不了的业务约束：

- node_type 枚举合法、parent 引用存在、无环
- 树深 ≤ MAX_DEPTH、单层扇出 ≤ MAX_FANOUT、总节点数 ≤ MAX_NODES
- paths 必须真实存在于该仓库 FileIndex（防 LLM 发明目录）
- monorepo 第一层 sub_app 必须与静态发现的子项目清单对齐

校验失败抛 TreeValidationError，callback 保留旧树不覆盖。
校验通过后输出嵌套树（children 递归结构），供 ai_summary_tree 持久化。
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field, ValidationError

logger = structlog.get_logger(__name__)

MAX_DEPTH = 4
MAX_FANOUT = 20
MAX_NODES = 100


class TreeValidationError(Exception):
    """能力树业务校验失败。"""


class TreeNodeIn(BaseModel):
    """扁平节点（task 容器 submit_summary 的 tree 元素）。"""

    node_id: str = Field(min_length=1, max_length=64)
    parent_id: str | None = None
    node_type: Literal["sub_app", "module", "capability"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    keywords: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)


def _normalize_path(p: str) -> str:
    return p.strip().strip("/").lstrip("./")


def assemble_nested_tree(flat_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """扁平邻接表 → 嵌套树；并做结构校验（引用/环/深度/扇出/总数）。

    Raises:
        TreeValidationError: 结构非法。
    """
    if len(flat_nodes) > MAX_NODES:
        raise TreeValidationError(f"节点数 {len(flat_nodes)} 超过上限 {MAX_NODES}")

    try:
        nodes = [TreeNodeIn.model_validate(n) for n in flat_nodes]
    except ValidationError as exc:
        raise TreeValidationError(f"节点字段非法: {exc}") from exc

    by_id: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if n.node_id in by_id:
            raise TreeValidationError(f"node_id 重复: {n.node_id}")
        by_id[n.node_id] = {
            "node_id": n.node_id,
            "node_type": n.node_type,
            "title": n.title,
            "summary": n.summary,
            "keywords": n.keywords[:20],
            "paths": [_normalize_path(p) for p in n.paths if p.strip()],
            "children": [],
        }

    roots: list[dict[str, Any]] = []
    for n in nodes:
        if n.parent_id is None or n.parent_id == "":
            roots.append(by_id[n.node_id])
            continue
        parent = by_id.get(n.parent_id)
        if parent is None:
            raise TreeValidationError(
                f"节点 {n.node_id} 的 parent_id={n.parent_id} 不存在"
            )
        parent["children"].append(by_id[n.node_id])

    if not roots and nodes:
        raise TreeValidationError("无顶层节点（所有节点都有 parent_id，存在环）")

    # 深度/环/扇出校验（迭代 DFS）
    visited: set[str] = set()
    stack: list[tuple[dict[str, Any], int]] = [(r, 1) for r in roots]
    while stack:
        node, depth = stack.pop()
        if node["node_id"] in visited:
            raise TreeValidationError(f"检测到环: {node['node_id']}")
        visited.add(node["node_id"])
        if depth > MAX_DEPTH:
            raise TreeValidationError(f"树深超过 {MAX_DEPTH} 层: {node['node_id']}")
        if len(node["children"]) > MAX_FANOUT:
            raise TreeValidationError(
                f"节点 {node['node_id']} 扇出 {len(node['children'])} 超过上限 {MAX_FANOUT}"
            )
        for child in node["children"]:
            stack.append((child, depth + 1))

    if len(visited) != len(nodes):
        raise TreeValidationError("存在不可达节点（环或游离子图）")

    return roots


def _collect_paths(tree: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    stack = list(tree)
    while stack:
        node = stack.pop()
        out.update(p for p in node.get("paths", []) if p)
        stack.extend(node.get("children", []))
    return out


# 整树拒绝阈值：无效 paths 占比超过该值才视为大规模虚构（疑似分析了错误仓库）。
# 低于阈值时仅剪掉无效 path 保留树——FileIndex 可能滞后于最新 commit（新增目录
# 尚未索引），个别无效 path 不应让整棵 80 节点的树 fail-closed 丢弃。
_PATH_REJECT_RATIO = 0.5


def validate_paths_against_file_index(
    tree: list[dict[str, Any]],
    indexed_paths: list[str],
    extra_valid_roots: list[str] | None = None,
) -> None:
    """paths 真实性校验：path 须是某个已索引文件的前缀（或全等）。

    无效 path 从节点上剪除（容忍 FileIndex 滞后与个别 LLM 笔误）；仅当无效
    占比超过 _PATH_REJECT_RATIO 时整树拒绝（大规模虚构）。
    仓库未索引（FileIndex 为空）时跳过——此时无事实可对照，只记 warning。

    Args:
        extra_valid_roots: 额外可信的目录根（如任务容器对新鲜 clone 静态扫描
            出的子项目清单）。FileIndex 可能滞后于最新 commit，这份清单比
            索引更新，落在其下的 path 视为真实。
    """
    if not indexed_paths:
        logger.warning("tree_paths_validation_skipped_no_file_index")
        return
    normalized = [_normalize_path(p) for p in indexed_paths]
    trusted_roots = [_normalize_path(p) for p in (extra_valid_roots or []) if p.strip()]
    claimed = _collect_paths(tree)
    if not claimed:
        return
    invalid: set[str] = set()
    for path in claimed:
        if any(f == path or f.startswith(path + "/") for f in normalized):
            continue
        if any(
            path == d or path.startswith(d + "/") or d.startswith(path + "/")
            for d in trusted_roots
        ):
            continue
        invalid.add(path)
    if not invalid:
        return
    if len(invalid) / len(claimed) > _PATH_REJECT_RATIO:
        raise TreeValidationError(
            f"超过 {int(_PATH_REJECT_RATIO * 100)}% 的 paths 不存在于仓库索引"
            f"（疑似大规模虚构）: {sorted(invalid)[:10]}"
        )
    stack = list(tree)
    while stack:
        node = stack.pop()
        node["paths"] = [p for p in node.get("paths", []) if p not in invalid]
        stack.extend(node.get("children", []))
    logger.warning(
        "tree_paths_pruned",
        pruned_count=len(invalid),
        claimed_count=len(claimed),
        pruned=sorted(invalid)[:10],
    )


def validate_monorepo_alignment(
    tree: list[dict[str, Any]], discovered_sub_projects: list[str]
) -> None:
    """monorepo 第一层 sub_app 必须与静态发现的子项目清单对齐。

    对齐定义：每个静态发现的子项目都有对应 sub_app 节点（paths 覆盖其根目录）；
    sub_app 节点的 paths 也必须落在清单内。允许 LLM 少建"空壳"子项目节点之外的
    额外顶层节点（如 docs），但 node_type=sub_app 的必须可对应。
    """
    if not discovered_sub_projects:
        return
    discovered = {_normalize_path(p) for p in discovered_sub_projects if p.strip()}
    sub_app_paths: set[str] = set()
    for node in tree:
        if node.get("node_type") != "sub_app":
            continue
        sub_app_paths.update(node.get("paths", []))

    # sub_app path 合法形态：等于某子项目根、其子路径、或其**父目录**——
    # 子项目数量超出扇出上限时（如 50+ 个 plugins/* 包），LLM 会合法地用
    # 父目录（plugins）做分组 sub_app 节点。
    fabricated = {
        p for p in sub_app_paths
        if not any(
            p == d or p.startswith(d + "/") or d.startswith(p + "/")
            for d in discovered
        )
    }
    if fabricated:
        raise TreeValidationError(
            f"sub_app 节点 paths 不在静态子项目清单内: {sorted(fabricated)[:10]}"
        )

    missing = {
        d for d in discovered
        if not any(
            p == d or p.startswith(d + "/") or d.startswith(p + "/")
            for p in sub_app_paths
        )
    }
    if not missing:
        return
    # 子项目数超过单层扇出上限时，「每个子项目一个第一层节点」结构上不可能
    # 满足（MAX_FANOUT 会先拒绝），缺失降级为 warning 不拦截。
    if len(discovered) > MAX_FANOUT:
        logger.warning(
            "tree_monorepo_alignment_partial",
            discovered_count=len(discovered),
            missing_count=len(missing),
            missing=sorted(missing)[:10],
        )
        return
    raise TreeValidationError(
        f"静态子项目清单中以下子应用未在树第一层出现: {sorted(missing)[:10]}"
    )


async def validate_and_assemble_tree(
    repository_id: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """完整校验入口：结构 → paths 真实性 → monorepo 对齐。

    Args:
        repository_id: 仓库 UUID 字符串。
        payload: submit_summary 的结构化结果（含 tree / discovered_sub_projects）。

    Returns:
        嵌套能力树（roots 列表）。

    Raises:
        TreeValidationError: 任一校验失败。
    """
    flat_nodes = payload.get("tree")
    if not isinstance(flat_nodes, list) or not flat_nodes:
        raise TreeValidationError("tree 字段缺失或为空")

    nested = assemble_nested_tree(flat_nodes)

    from repositories.models import FileIndex

    def _load_indexed_paths() -> list[str]:
        return list(
            FileIndex.objects.filter(repository_id=repository_id).values_list(
                "file_path", flat=True
            )
        )

    indexed_paths = await sync_to_async(_load_indexed_paths, thread_sensitive=False)()
    discovered = payload.get("discovered_sub_projects") or []
    discovered_list = [str(p) for p in discovered] if isinstance(discovered, list) else []

    # 静态发现的子项目清单来自任务容器对新鲜 clone 的扫描，比 FileIndex 更新，
    # 作为额外可信目录根参与 paths 校验。
    validate_paths_against_file_index(
        nested, indexed_paths, extra_valid_roots=discovered_list
    )

    if discovered_list:
        validate_monorepo_alignment(nested, discovered_list)

    return nested
