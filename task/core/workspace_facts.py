"""monorepo 子项目静态发现（任务容器侧轻量版）。

与 server/codegraph/lsp/workspace_discovery.py 的三探针同源，但服务两个不同目的：
server 版为 LSP 索引发现 Vue sub-project（要求 tsconfig.json）；本模块为
repo_summary 能力树生成提供**事实约束**——发现的子项目清单会注入 prompt，
要求 agent 以此为树第一层骨架，禁止 LLM 自行猜测/合并/遗漏子应用。

因此判定标准放宽为 package.json 存在（而非 tsconfig.json），并额外支持
go.work 多模块工作区。任务容器无 pyyaml 依赖，pnpm-workspace.yaml 用
行级解析（仅取 packages: 列表项，足够覆盖常规写法）。
"""

from __future__ import annotations

import glob as _glob
import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_SKIP_DIR_MARKERS = ("node_modules", ".git")


def _parse_pnpm_workspace_packages(workspace: Path) -> list[str]:
    """行级解析 pnpm-workspace.yaml 的 packages 列表（无 yaml 依赖）。"""
    f = workspace / "pnpm-workspace.yaml"
    if not f.is_file():
        return []
    patterns: list[str] = []
    in_packages = False
    try:
        for raw_line in f.read_text(encoding="utf-8").splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("packages:"):
                in_packages = True
                continue
            if in_packages:
                if stripped.startswith("- "):
                    value = stripped[2:].strip().strip("'\"")
                    if value and not value.startswith("!"):
                        patterns.append(value)
                elif not line.startswith((" ", "\t")):
                    # 新的顶层 key，packages 块结束
                    in_packages = False
    except OSError:
        return []
    return patterns


def _parse_package_json_workspaces(workspace: Path) -> list[str]:
    f = workspace / "package.json"
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    ws = data.get("workspaces")
    if isinstance(ws, list):
        return [str(p) for p in ws if isinstance(p, str) and not p.startswith("!")]
    if isinstance(ws, dict):
        pkgs = ws.get("packages", [])
        if isinstance(pkgs, list):
            return [str(p) for p in pkgs if isinstance(p, str) and not p.startswith("!")]
    return []


def _parse_nx_layout_patterns(workspace: Path) -> list[str]:
    f = workspace / "nx.json"
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    layout = data.get("workspaceLayout", {})
    patterns: list[str] = []
    if isinstance(layout, dict):
        for key in ("appsDir", "libsDir"):
            value = layout.get(key)
            if isinstance(value, str) and value:
                patterns.append(f"{value}/*")
    return patterns


def _parse_go_work_dirs(workspace: Path) -> list[Path]:
    """解析 go.work 的 use 指令（含块语法）。"""
    f = workspace / "go.work"
    if not f.is_file():
        return []
    dirs: list[Path] = []
    in_use_block = False
    try:
        for raw_line in f.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("use ("):
                in_use_block = True
                continue
            if in_use_block:
                if stripped == ")":
                    in_use_block = False
                    continue
                candidate = stripped
            elif stripped.startswith("use "):
                candidate = stripped[4:].strip()
            else:
                continue
            candidate = candidate.strip().strip("'\"")
            if candidate in ("", "."):
                continue
            p = (workspace / candidate).resolve()
            if p.is_dir():
                dirs.append(p)
    except OSError:
        return []
    return dirs


def _expand_glob_patterns(workspace: Path, patterns: list[str]) -> set[Path]:
    roots: set[Path] = set()
    for pattern in patterns:
        for matched in _glob.glob(str(workspace / pattern)):
            p = Path(matched).resolve()
            if not p.is_dir():
                continue
            if any(marker in p.parts for marker in _SKIP_DIR_MARKERS):
                continue
            roots.add(p)
    return roots


def _read_package_name(root: Path) -> str | None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = data.get("name")
    return str(name) if isinstance(name, str) and name else None


def discover_workspace_facts(workspace: Path) -> dict[str, Any]:
    """发现 monorepo 子项目清单，作为能力树第一层骨架的事实约束。

    Returns:
        {"is_monorepo": bool, "sub_projects": [{"root": 相对路径, "package_name": str|None}]}
    """
    workspace = workspace.resolve()
    patterns = (
        _parse_pnpm_workspace_packages(workspace)
        + _parse_package_json_workspaces(workspace)
        + _parse_nx_layout_patterns(workspace)
    )
    candidate_roots = _expand_glob_patterns(workspace, patterns)

    # JS 系探针要求 package.json 存在（描述用途，放宽于 server 版的 tsconfig 要求）
    js_roots = {p for p in candidate_roots if (p / "package.json").is_file()}

    go_roots = set(_parse_go_work_dirs(workspace))

    all_roots = sorted(js_roots | go_roots)
    sub_projects = [
        {
            "root": str(p.relative_to(workspace)),
            "package_name": _read_package_name(p),
        }
        for p in all_roots
        if p != workspace
    ]

    facts = {
        "is_monorepo": len(sub_projects) >= 2,
        "sub_projects": sub_projects,
    }
    logger.info(
        "workspace_facts_discovered",
        sub_project_count=len(sub_projects),
        is_monorepo=facts["is_monorepo"],
    )
    return facts


def format_facts_prompt_section(facts: dict[str, Any]) -> str:
    """把发现结果格式化为 prompt 注入段；非 monorepo 返回空字符串。"""
    sub_projects = facts.get("sub_projects") or []
    if not facts.get("is_monorepo") or not sub_projects:
        return ""
    if len(sub_projects) > 20:
        # 子项目数超过树的单层扇出上限（20）时，「每包一个第一层节点」结构上
        # 不可能满足——改为要求按父目录分组（如 plugins/、packages/）。
        skeleton_rules = [
            f"- 清单共 {len(sub_projects)} 个子项目，超过树第一层扇出上限（20）。"
            "请按父目录分组建 sub_app 节点（如 `apps/` 下每个应用一个节点、"
            "`plugins/` 整体一个节点，paths 指向该父目录），组内重要包降为 module 子节点",
            "- 禁止发明清单之外的子应用；分组节点的 paths 必须是清单内子项目的真实父目录",
        ]
    else:
        skeleton_rules = [
            "- 以这份清单为能力树的**第一层骨架**（node_type=sub_app，每个子项目一个节点）",
            "- 禁止合并、遗漏或发明清单之外的子应用",
        ]
    lines = [
        "",
        "## Monorepo 子项目清单（事实约束，最高优先级）",
        "",
        "静态扫描（pnpm-workspace / package.json workspaces / nx.json / go.work）"
        "已确认本仓库为 monorepo，子项目清单如下。你必须：",
        *skeleton_rules,
        "- 逐个子项目阅读其 README / 入口 / 路由后撰写职责描述",
        "",
    ]
    for sp in sub_projects:
        pkg = f"（package: {sp['package_name']}）" if sp.get("package_name") else ""
        lines.append(f"- `{sp['root']}/`{pkg}")
    return "\n".join(lines)
