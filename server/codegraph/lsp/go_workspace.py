"""initial implementation: Go workspace 自动发现 —— go.work 优先 + go.mod 最浅路径策略。

per work item：gopls 复用 initial implementation _SUPERVISORS module-level 单实例缓存；
  workspace_root 指向 go.mod 最近父目录（不是文件所在目录）。
per work item：vendor/ 内嵌 go.mod 不采纳（只扫一级子目录）。
per Pitfall P-checkpoint：vendor/ 显式跳过，防误识别。
per Pitfall P-checkpoint：go.work use 路径相对于 go.work 所在目录，需 resolve() 绝对化。

公开 API
========

- ``discover_go_workspace(repo_root: Path) -> GoWorkspace | None``
- ``GoWorkspace`` frozen dataclass

设计约束
========

- 发现失败返 None，不 raise；让调用方走 fallback
- 只扫一级子目录（防 vendor/ 深层 go.mod 误命中）
- go.work 优先于 go.mod（gopls 官方推荐）
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Final

import structlog

logger = structlog.get_logger(__name__)

# structlog 事件名常量（per work item / work item）
_EVENT_WORKSPACE_DISCOVERED: Final[str] = "gopls_workspace_discovered"
_EVENT_MULTI_GOMOD_DETECTED: Final[str] = "gopls_multi_gomod_detected"


@dataclasses.dataclass(frozen=True)
class GoWorkspace:
    """Go workspace 信息（go.mod 根目录 + 版本 + 模块路径）。

    ``go_mod_root``：gopls workspace_root 的绝对 Path；
    ``go_version``：go.mod 声明的 go 版本（字符串，如 "1.22"）；
    ``module_path``：go.mod 的 module 路径（如 "example.com/myapp"）。
    """

    go_mod_root: Path
    go_version: str | None
    module_path: str | None


def discover_go_workspace(repo_root: Path) -> GoWorkspace | None:
    """从 repo_root 发现 Go workspace。

    策略（per work item）：
        1. 检查 repo_root/go.work → 解析 use 指令 → 取第一个模块为 workspace root
        2. 检查 repo_root/go.mod → 直接作为 workspace root
        3. 扫一级子目录（过滤 vendor/ node_modules/ 以 . 或 _ 开头）→ 找 go.mod
        4. 全部失败 → None

    Args:
        repo_root: 仓库根目录（或待检测目录）。

    Returns:
        ``GoWorkspace`` 或 None（无 go.mod 时）。
    """
    repo_root = repo_root.resolve()

    # 优先检查 go.work（per work item / go 1.18+ workspace 模式）
    go_work = repo_root / "go.work"
    if go_work.exists():
        ws = _parse_go_work(go_work, repo_root)
        if ws is not None:
            return ws

    # fallback：从 go.mod 发现
    return _discover_from_gomod(repo_root)


def _parse_go_work(go_work: Path, repo_root: Path) -> GoWorkspace | None:
    """解析 go.work 文件，提取第一个 use 指令作为 workspace root。

    per Pitfall P-checkpoint：use 路径相对于 go.work 所在目录（即 repo_root）。
    """
    try:
        content = go_work.read_text(encoding="utf-8")
    except OSError:
        return None

    # 匹配单行 use ./path 格式
    use_paths: list[str] = re.findall(
        r"^\s*use\s+([^\s()\n#]+)", content, re.MULTILINE
    )

    # 匹配多行 use (...) 块
    block_match = re.search(r"use\s*\(([^)]*)\)", content, re.DOTALL)
    if block_match:
        block_content = block_match.group(1)
        for line in block_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                use_paths.append(line)

    for use_path in use_paths:
        use_path = use_path.strip()
        if not use_path or use_path.startswith("#"):
            continue
        candidate_mod_root = (repo_root / use_path).resolve()
        go_mod = candidate_mod_root / "go.mod"
        if go_mod.exists():
            module_path, go_version = _parse_go_mod(go_mod)
            logger.info(
                _EVENT_WORKSPACE_DISCOVERED,
                source="go.work",
                go_mod_root=str(candidate_mod_root),
                module_path=module_path,
                go_version=go_version,
            )
            return GoWorkspace(
                go_mod_root=candidate_mod_root,
                go_version=go_version,
                module_path=module_path,
            )

    return None


def _discover_from_gomod(repo_root: Path) -> GoWorkspace | None:
    """从 go.mod 文件发现 workspace root（go.mod 最浅路径策略）。

    扫描范围：repo_root 直接子目录（含 repo_root 本身），跳过：
        - vendor/（per Pitfall P-checkpoint）
        - node_modules/
        - 以 "." 开头（.git 等）
        - 以 "_" 开头
    """
    candidates: list[Path] = []

    # repo_root 自身先检查
    if (repo_root / "go.mod").exists():
        candidates.append(repo_root)

    # 扫一级子目录（仅一级，防 vendor 深层误命中）
    try:
        children = sorted(repo_root.iterdir())
    except OSError:
        children = []

    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name.startswith("_"):
            continue
        if name in ("vendor", "node_modules"):
            continue
        if (child / "go.mod").exists():
            candidates.append(child)

    if not candidates:
        return None

    if len(candidates) > 1:
        logger.warning(
            _EVENT_MULTI_GOMOD_DETECTED,
            candidates_count=len(candidates),
            chosen_root=str(candidates[0]),
            all_candidates=[str(c) for c in candidates],
        )

    chosen = candidates[0]
    module_path, go_version = _parse_go_mod(chosen / "go.mod")
    logger.info(
        _EVENT_WORKSPACE_DISCOVERED,
        source="go.mod",
        go_mod_root=str(chosen),
        module_path=module_path,
        go_version=go_version,
    )
    return GoWorkspace(
        go_mod_root=chosen,
        go_version=go_version,
        module_path=module_path,
    )


def _parse_go_mod(go_mod_file: Path) -> tuple[str | None, str | None]:
    """解析 go.mod 文件，提取 module 路径和 go 版本。

    Returns:
        ``(module_path, go_version)``，解析失败时对应字段返 None。
    """
    module_path: str | None = None
    go_version: str | None = None

    try:
        with go_mod_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if module_path is None:
                    m = re.match(r"^module\s+(\S+)", line)
                    if m:
                        module_path = m.group(1)
                if go_version is None:
                    m = re.match(r"^go\s+(\d+\.\d+(?:\.\d+)?)", line)
                    if m:
                        go_version = m.group(1)
                if module_path is not None and go_version is not None:
                    break
    except OSError:
        return None, None

    return module_path, go_version


__all__ = ["GoWorkspace", "discover_go_workspace"]
