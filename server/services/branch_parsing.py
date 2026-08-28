"""分支名 → work_item_id 反向解析（CURSOR-01 地基）。

Friday 编码节点（``workflows/nodes/ai/coding.py::_generate_candidate_branch``）按
``feat/xxxx-m{work_item_id}-{slug}`` 单向生成分支名；本模块提供**对称的反向解析**，供
MCP ``lookup_project_by_branch`` 用当前分支名反查飞书工作项 → 项目。

设计要点：
- **fail-soft**：无法解析（空串/格式不符/无数字 id）一律返回 ``None``，绝不抛。
- **宽松匹配**：优先严格对齐生成格式 ``feat/xxxx-m{id}-...``；兜底允许任意前缀的
  ``-m{digits}`` 段（如 ``feature/foo-m123`` / ``hotfix-m456-bar``），覆盖人工/历史分支命名漂移。
- 纯函数、无 IO/ORM，可单测、可被 MCP 异步视图直接调用。
"""

from __future__ import annotations

import re

__all__ = ["is_default_branch", "parse_work_item_id_from_branch"]

_WELL_KNOWN_DEFAULT_BRANCHES = frozenset({"main", "master", "develop"})

# 严格对齐生成器：feat/xxxx-m{id}-slug（id 为飞书数值工作项 id）。
_STRICT_RE = re.compile(r"^feat/xxxx-m(?P<id>\d+)(?:-.*)?$", re.IGNORECASE)

# 宽松兜底：任意位置的 `-m{digits}` 段（边界为 `-` 或串尾），覆盖命名漂移。
_LOOSE_RE = re.compile(r"-m(?P<id>\d+)(?:-|$)", re.IGNORECASE)


def is_default_branch(branch_name: str | None, default_branch: str | None = None) -> bool:
    """判断分支是否为约定或仓库配置的默认分支（大小写敏感）。"""
    if not branch_name:
        return False
    return branch_name in _WELL_KNOWN_DEFAULT_BRANCHES or (
        bool(default_branch) and branch_name == default_branch
    )


def parse_work_item_id_from_branch(branch_name: str | None) -> int | None:
    """从分支名抽取飞书工作项数值 id（``feat/xxxx-m{id}-slug``）。

    Args:
        branch_name: 分支名（可空）。

    Returns:
        解析到的 ``work_item_id``（int），无法解析返回 ``None``（fail-soft，绝不抛）。
    """
    if not branch_name:
        return None
    candidate = branch_name.strip()
    if not candidate:
        return None

    match = _STRICT_RE.match(candidate) or _LOOSE_RE.search(candidate)
    if match is None:
        return None
    try:
        return int(match.group("id"))
    except (TypeError, ValueError):  # pragma: no cover — regex 已保证 \d+
        return None
