"""nx sub-project 自动发现层（三探针并集 + tsconfig.json 兜底）。


    - 第一探针 ``pnpm-workspace.yaml::packages`` glob 列表 + 展开
    - 第二探针 root ``package.json::workspaces``（array 或 ``{packages: [...]}``）
    - 第三探针 ``nx.json::workspaceLayout {appsDir, libsDir}``
    - 兜底过滤：每候选目录 ``tsconfig.json`` 必须存在；``node_modules`` 子目录显式
      跳过；``!`` 前缀 glob 不支持

per work item / 薄防御层 —— 读 package.json ``dependencies.vue`` /
``devDependencies.vue`` semver；vue<2.7 时仍纳入 SubProject list（标 vue_version）；
``VolarPool.get`` 入口再防御 raise，触发 implementation LspBackend 基类 fallback tree-sitter。

公开 API
========

- ``discover_sub_projects(repo_root: Path) -> list[SubProject]``
- ``is_vue_27_or_newer(vue_spec: str | None) -> bool``
- ``SubProject`` frozen dataclass（per work item 让其可作 dict key / OrderedDict 配合）
"""

from __future__ import annotations

import dataclasses
import glob
import json
from pathlib import Path
from typing import Any, Final

import structlog
import yaml
from packaging.version import Version

logger = structlog.get_logger(__name__)

_EVENT_DISCOVERY_COMPLETED: Final[str] = "volar_workspace_discovery_completed"
_EVENT_GLOB_EXCLUDE_SKIPPED: Final[str] = "volar_workspace_glob_exclude_skipped"


@dataclasses.dataclass(frozen=True)
class SubProject:
    """nx sub-project 元数据（per work item frozen=True 让其可作 dict key）。"""

    root: Path                  # sub-project 绝对路径（已 .resolve()）
    package_name: str | None    # package.json::name；缺失为 None
    vue_version: str | None     # package.json::dependencies.vue / devDependencies.vue
    tsconfig_path: Path         # sub-project root + tsconfig.json 绝对路径


def discover_sub_projects(repo_root: Path) -> list[SubProject]:
    """三探针并集 + tsconfig.json 兜底过滤。

    Args:
        repo_root: monorepo 根目录绝对路径。

    Returns:
        ``list[SubProject]``：按 ``root`` 路径升序排序，去重后的可独立 indexed
        sub-projects；缺 ``tsconfig.json`` 的候选自动跳过。
    """
    candidate_roots: set[Path] = set()
    candidate_roots.update(_probe_pnpm_workspace(repo_root))
    candidate_roots.update(_probe_package_json_workspaces(repo_root))
    candidate_roots.update(_probe_nx_json(repo_root))

    sub_projects: list[SubProject] = []
    skipped_missing_tsconfig = 0
    skipped_vue26 = 0

    for root in sorted(candidate_roots):
        tsconfig = root / "tsconfig.json"
        if not tsconfig.exists():
            skipped_missing_tsconfig += 1
            continue

        package_name, vue_version = _parse_package_json(root / "package.json")

        if vue_version and not is_vue_27_or_newer(vue_version):
            skipped_vue26 += 1

        sub_projects.append(
            SubProject(
                root=root.resolve(),
                package_name=package_name,
                vue_version=vue_version,
                tsconfig_path=tsconfig.resolve(),
            )
        )

    logger.info(
        _EVENT_DISCOVERY_COMPLETED,
        repo_root=str(repo_root),
        sub_project_count=len(sub_projects),
        skipped_missing_tsconfig=skipped_missing_tsconfig,
        skipped_vue26=skipped_vue26,
    )
    return sub_projects


def _probe_pnpm_workspace(repo_root: Path) -> set[Path]:
    """探针 1：``pnpm-workspace.yaml::packages`` glob 列表。"""
    file = repo_root / "pnpm-workspace.yaml"
    if not file.exists():
        return set()
    try:
        data: Any = yaml.safe_load(file.read_text()) or {}
    except yaml.YAMLError:
        return set()
    if not isinstance(data, dict):
        return set()
    packages = data.get("packages", [])
    if not isinstance(packages, list):
        return set()
    return _expand_globs(repo_root, packages)


def _probe_package_json_workspaces(repo_root: Path) -> set[Path]:
    """探针 2：root ``package.json::workspaces``（兼容 array / dict 两风格）。"""
    file = repo_root / "package.json"
    if not file.exists():
        return set()
    try:
        data: Any = json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(data, dict):
        return set()
    workspaces: Any = data.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])
    if not isinstance(workspaces, list):
        return set()
    return _expand_globs(repo_root, workspaces)


def _probe_nx_json(repo_root: Path) -> set[Path]:
    """探针 3：``nx.json::workspaceLayout {appsDir, libsDir}``。"""
    file = repo_root / "nx.json"
    if not file.exists():
        return set()
    try:
        data: Any = json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(data, dict):
        return set()
    layout = data.get("workspaceLayout")
    if not isinstance(layout, dict):
        layout = {}
    apps_dir = layout.get("appsDir", "apps")
    libs_dir = layout.get("libsDir", "libs")
    result: set[Path] = set()
    for sub_dir in (apps_dir, libs_dir):
        if not isinstance(sub_dir, str):
            continue
        full = repo_root / sub_dir
        if full.is_dir():
            for child in full.iterdir():
                if child.is_dir() and "node_modules" not in child.parts:
                    result.add(child)
    return result


def _expand_globs(repo_root: Path, patterns: list[Any]) -> set[Path]:
    """workspaces glob 展开；跳过 ``!`` 前缀 + ``node_modules`` 子目录。

    简化策略：把 ``foo/**`` 归一为 ``foo/*``（仅展开一级，sub-project 一般是 monorepo
    的直接子目录）；嵌套 sub-project 不在本 phase 范围（per Deferred）。
    """
    result: set[Path] = set()
    for pat in patterns:
        if not isinstance(pat, str):
            continue
        if pat.startswith("!"):
            logger.debug(_EVENT_GLOB_EXCLUDE_SKIPPED, pattern=pat)
            continue
        normalized = pat.rstrip("/")
        if normalized.endswith("/**"):
            normalized = normalized[:-3] + "/*"
        elif not any(ch in normalized for ch in "*?["):
            normalized = normalized + "/*"
        for match in glob.glob(str(repo_root / normalized)):
            mp = Path(match)
            if mp.is_dir() and "node_modules" not in mp.parts:
                result.add(mp)
    return result


def _parse_package_json(file: Path) -> tuple[str | None, str | None]:
    """读 package.json::name + dependencies.vue / devDependencies.vue。"""
    if not file.exists():
        return None, None
    try:
        data: Any = json.loads(file.read_text())
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    name = data.get("name") if isinstance(data.get("name"), str) else None

    vue_spec: Any = None
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        vue_spec = deps.get("vue")
    if vue_spec is None:
        dev_deps = data.get("devDependencies")
        if isinstance(dev_deps, dict):
            vue_spec = dev_deps.get("vue")
    return name, vue_spec if isinstance(vue_spec, str) else None


def is_vue_27_or_newer(vue_spec: str | None) -> bool:
    """判断 vue semver 是否 ≥ 2.7.0；None / 无法解析返 False（保守走 tree-sitter）。

    per work item 防御性 Vue 2.6- fallback。

    支持的输入形式（≥ 2.7 → True）::

        "2.7.14" / "^2.7.14" / "~2.7.14" / "2.7.x" / "3.0.0"

    返 False 的情况::

        "2.6.14" / None / "" / "invalid" / 不可解析的字符串
    """
    if not vue_spec:
        return False
    cleaned = vue_spec.lstrip("^~>=<")
    if "x" in cleaned:
        cleaned = cleaned.replace("x", "0")
    try:
        ver = Version(cleaned)
    except Exception:  # noqa: BLE001
        return False
    return ver >= Version("2.7.0")


__all__ = ["SubProject", "discover_sub_projects", "is_vue_27_or_newer"]
