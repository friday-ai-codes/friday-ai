"""统一仓库路由服务的静态边界守卫。"""

from __future__ import annotations

import ast
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
# 摘要通道是 V2 内部实现，允许出现 route_repo_summaries 符号本身。
ALLOWED_INTERNAL_MODULES = {
    SERVER_ROOT / "codegraph/services/repo_summaries_channel.py",
}


def _production_python_files():
    for path in SERVER_ROOT.rglob("*.py"):
        relative = path.relative_to(SERVER_ROOT)
        if (
            "tests" in relative.parts
            or any(part.startswith(".") for part in relative.parts)
            or path in ALLOWED_INTERNAL_MODULES
        ):
            continue
        yield path


def test_legacy_repo_router_module_is_gone() -> None:
    """旧公开入口 repo_router.py 必须已删除，不得以兼容壳回潮。"""

    assert not (SERVER_ROOT / "codegraph/services/repo_router.py").exists()


def test_production_code_does_not_import_legacy_repo_router() -> None:
    """生产代码只能调用 RepoRouterV2，不得重新引入公开 v1 路由面。"""

    violations: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == (
                "codegraph.services.repo_router"
            ):
                violations.append(f"{path.relative_to(SERVER_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "codegraph.services.repo_router":
                        violations.append(f"{path.relative_to(SERVER_ROOT)}:{node.lineno}")

    assert violations == [], f"生产代码仍引用旧 RepoRouter: {violations}"


def test_summaries_channel_is_only_called_by_unified_router() -> None:
    """摘要通道是 V2 内部能力，不得成为另一套业务入口。"""

    callers: list[str] = []
    for path in _production_python_files():
        source = path.read_text(encoding="utf-8")
        if "route_repo_summaries" in source:
            callers.append(str(path.relative_to(SERVER_ROOT)))

    assert callers == ["codegraph/services/repo_router_v2.py"]
