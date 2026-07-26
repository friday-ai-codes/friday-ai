"""feature list 取数与展平（技术方案编排的输入适配层）。

把三种来源统一成编排要的 ``feature_segments``：

1. **项目**：项目已录入的 ``feature_list`` 工件 → ``FeatureListService.build_tree``。
2. **分支**：分支名反查 ``ProjectBranch`` 定位项目 → 同上（复用手动绑定分支能力，BIND-01）。
3. **纯文本**：调用方直接贴 feature list 原文。有项目上下文时走 LLM 逐字解析（质量高、
   与项目录入同源）；无项目上下文（如 IDE 里还没建项目）则退到启发式结构解析——不能因为
   缺项目就不给用，这是 IDE / CLI 场景的主要入口。

展平结果每项形如 ``{"title", "module", "layer", "acceptance"}``：``title`` 是功能点名，
``module`` 是所属模块，``layer`` 恒空（feature list 不含前后端分层信息，交由路由与分类
阶段按代码证据判断，此处不臆造）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "FeatureSourceError",
    "ResolvedFeatureSource",
    "flatten_feature_tree",
    "parse_feature_text_heuristic",
    "aresolve_feature_source",
]

_COMPONENT = "feature_source"

# 展平上限——超大 feature list 全量进编排会撑爆 prompt 与检索预算。
_MAX_SEGMENTS = 60

# 启发式解析：模块标题（``模块 1：xxx`` / ``## xxx`` / ``一、xxx``）
_MODULE_PATTERNS = (
    re.compile(r"^#{1,3}\s+(?:模块\s*\d+[：:]\s*)?(.+?)\s*$"),
    re.compile(r"^模块\s*\d+\s*[：:]\s*(.+?)\s*$"),
    re.compile(r"^\d+\s*[、.]\s*(.+?)\s*$"),
)
# 启发式解析：功能点（``功能点 A：xxx`` / ``#### xxx`` / ``- xxx``）
_FEATURE_PATTERNS = (
    re.compile(r"^功能点\s*[A-Za-z0-9]+\s*[：:]\s*(.+?)\s*$"),
    re.compile(r"^#{4,6}\s+(.+?)\s*$"),
    re.compile(r"^[-*]\s+(.+?)\s*$"),
)
# 验收项行（``当 ... 时，系统应 ...``）
_ACCEPTANCE_PATTERN = re.compile(r"^(?:当|Given|When)\s*.+")


class FeatureSourceError(Exception):
    """feature list 取数失败（携机器可读 code 供 MCP 映射 HTTP 状态）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class ResolvedFeatureSource:
    """取数结果：展平后的功能点 + 定位到的项目（可为 None）+ 来源描述。"""

    segments: list[dict[str, Any]] = field(default_factory=list)
    project: Any = None
    source: str = ""
    module_count: int = 0
    truncated: bool = False

    @property
    def project_id(self) -> str:
        return str(getattr(self.project, "id", "") or "")


def flatten_feature_tree(
    tree: Any, *, max_segments: int = _MAX_SEGMENTS
) -> tuple[list[dict], int, bool]:
    """``FeatureListService.build_tree`` 内部树 → 展平功能点列表。

    Args:
        tree: ``{"modules": [{"module", "summary", "features": [{"name", "acceptance", ...}]}]}``。
        max_segments: 展平上限，超出截断。

    Returns:
        ``(segments, module_count, truncated)``。
    """
    if not isinstance(tree, dict):
        return [], 0, False
    modules = tree.get("modules") or []
    if not isinstance(modules, list):
        return [], 0, False

    segments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    truncated = False
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        module_name = str(mod.get("module") or mod.get("name") or "").strip()
        for feat in mod.get("features") or []:
            if not isinstance(feat, dict):
                continue
            title = str(feat.get("name") or "").strip()
            if not title:
                continue
            dedupe_key = (module_name, title)
            if dedupe_key in seen:
                continue
            if len(segments) >= max_segments:
                truncated = True
                break
            seen.add(dedupe_key)
            acceptance = [str(a).strip() for a in (feat.get("acceptance") or []) if str(a).strip()]
            segments.append(
                {
                    "title": title,
                    "module": module_name,
                    # feature list 不含前后端分层信息——留空交由路由/分类按代码证据判断。
                    "layer": "",
                    "acceptance": acceptance,
                }
            )
        if truncated:
            break
    return segments, len(modules), truncated


def parse_feature_text_heuristic(text: str) -> dict[str, Any]:
    """无项目上下文时的启发式 feature list 解析（不调 LLM）。

    按「模块标题 → 功能点 → 验收项」三层结构切分。识别不出模块时全部归入「未分组」；
    识别不出任何功能点时返回空树，由调用方报错——**绝不把整篇文档当成一个功能点**
    （那会让后续分类与方案完全失焦）。
    """
    modules: list[dict[str, Any]] = []
    current_module: dict[str, Any] | None = None
    current_feature: dict[str, Any] | None = None

    def _ensure_module() -> dict[str, Any]:
        nonlocal current_module
        if current_module is None:
            current_module = {"module": "未分组", "features": []}
            modules.append(current_module)
        return current_module

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        feature_name = _match_first(line, _FEATURE_PATTERNS)
        module_name = _match_first(line, _MODULE_PATTERNS)

        # 功能点模式优先于模块模式：`#### xxx` 同时匹配两类前缀时应判为功能点。
        if feature_name and _is_feature_line(line):
            current_feature = {"name": feature_name, "acceptance": [], "source": line}
            _ensure_module()["features"].append(current_feature)
            continue
        if module_name and _is_module_line(line):
            current_module = {"module": module_name, "features": []}
            modules.append(current_module)
            current_feature = None
            continue
        if current_feature is not None and _ACCEPTANCE_PATTERN.match(line):
            current_feature["acceptance"].append(line)

    # 丢掉没有任何功能点的空模块（纯标题噪音）。
    modules = [m for m in modules if m["features"]]
    return {"modules": modules}


def _match_first(line: str, patterns: tuple[re.Pattern, ...]) -> str:
    for pattern in patterns:
        m = pattern.match(line)
        if m:
            value = m.group(1).strip()
            if value:
                return value
    return ""


def _is_feature_line(line: str) -> bool:
    return bool(
        line.startswith("功能点") or re.match(r"^#{4,6}\s+", line) or re.match(r"^[-*]\s+", line)
    )


def _is_module_line(line: str) -> bool:
    return bool(
        line.startswith("模块")
        or re.match(r"^#{1,3}\s+", line)
        or re.match(r"^\d+\s*[、.]\s+", line)
    )


async def aresolve_feature_source(
    *,
    project_id: Any = None,
    branch_name: str = "",
    repository_id: Any = None,
    feature_list_text: str = "",
    max_segments: int = _MAX_SEGMENTS,
) -> ResolvedFeatureSource:
    """三源取数 → 展平功能点。三者至少给一个，优先级 text > project_id > branch_name。

    Raises:
        FeatureSourceError: 无任何来源 / 项目不存在 / 分支未绑定项目 / 解析不出功能点。
    """
    from initiatives.models import Project
    from initiatives.services.feature_list_service import FeatureListService

    project = None
    source = ""

    # 1. 定位项目（text 模式下项目可选，仅用于 LLM provider 解析与权限归属）。
    if project_id:
        project = await Project.objects.select_related("space").filter(pk=project_id).afirst()
        if project is None:
            raise FeatureSourceError("project_not_found", "项目不存在")
        source = "project"
    elif branch_name:
        project = await _aresolve_project_by_branch(branch_name, repository_id)
        if project is None:
            raise FeatureSourceError(
                "branch_not_bound",
                f"分支 {branch_name} 未绑定任何项目——请先在项目工作台「关联分支」绑定，"
                "或改用 project_id / feature_list_text 发起",
            )
        source = "branch"

    # 2. 取 feature 树。
    if feature_list_text.strip():
        tree = await _aparse_text(feature_list_text, project)
        source = "text"
    else:
        if project is None:
            raise FeatureSourceError(
                "missing_source",
                "需提供 project_id、branch_name 或 feature_list_text 之一",
            )
        tree = await FeatureListService().build_tree(project.id)

    segments, module_count, truncated = flatten_feature_tree(tree, max_segments=max_segments)
    if not segments:
        raise FeatureSourceError(
            "empty_feature_list",
            "未解析出任何功能点——项目尚未录入 feature list，或提供的文本不含可识别的功能点结构",
        )

    logger.info(
        "feature_source_resolved",
        category="caller",
        component=_COMPONENT,
        source=source,
        project_id=str(getattr(project, "id", "") or ""),
        module_count=module_count,
        feature_count=len(segments),
        truncated=truncated,
    )
    return ResolvedFeatureSource(
        segments=segments,
        project=project,
        source=source,
        module_count=module_count,
        truncated=truncated,
    )


async def _aresolve_project_by_branch(branch_name: str, repository_id: Any) -> Any:
    """分支名 → 项目（复用手动绑定的 ``ProjectBranch``）。多命中且未指定仓库 → 取最近绑定。"""
    from initiatives.models import ProjectBranch

    qs = ProjectBranch.objects.filter(branch_name=branch_name)
    if repository_id:
        qs = qs.filter(repository_id=repository_id)
    binding = await qs.select_related("project", "project__space").order_by("-created_at").afirst()
    return getattr(binding, "project", None)


async def _aparse_text(text: str, project: Any) -> dict[str, Any]:
    """文本 → feature 树。有项目走 LLM 逐字解析，无项目/解析失败退启发式。"""
    if project is not None:
        try:
            from initiatives.services.feature_list_import import (
                agenerate_feature_modules_from_text,
            )

            modules = await agenerate_feature_modules_from_text(project.id, text)
            if modules:
                return {"modules": modules}
        except Exception as exc:  # noqa: BLE001 — LLM 解析失败退启发式，不阻断
            logger.warning(
                "feature_source_llm_parse_failed_fallback_heuristic",
                category="sampling",
                component=_COMPONENT,
                error=str(exc),
            )
    return parse_feature_text_heuristic(text)
