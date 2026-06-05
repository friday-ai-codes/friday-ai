"""Services package.

注意：本模块对外暴露的 ``DependencyCacheManager`` / ``RepoCacheManager`` 通过
``__getattr__`` 懒加载，避免 Django app loading 阶段（populate phase）触发
``system.models`` 的模型类定义 —— 在 ``services.code_intel`` 加入 INSTALLED_APPS
之后，Django 需要在 apps_ready 之前导入 ``services`` 父包，eager import
``services.dependency_cache`` 会因 ``system.models`` ORM 元类调
``check_apps_ready()`` 而抛 ``AppRegistryNotReady`` (per initial implementation Rule 3 修复)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.dependency_cache import (
        DependencyCacheManager,
        LockFileInfo,
        PackageManager,
    )
    from services.repo_cache_manager import RepoCacheManager

__all__ = [
    "DependencyCacheManager",
    "LockFileInfo",
    "PackageManager",
    "RepoCacheManager",
]


def __getattr__(name: str) -> Any:
    if name in {"DependencyCacheManager", "LockFileInfo", "PackageManager"}:
        from services.dependency_cache import (
            DependencyCacheManager,
            LockFileInfo,
            PackageManager,
        )
        return {
            "DependencyCacheManager": DependencyCacheManager,
            "LockFileInfo": LockFileInfo,
            "PackageManager": PackageManager,
        }[name]
    if name == "RepoCacheManager":
        from services.repo_cache_manager import RepoCacheManager
        return RepoCacheManager
    raise AttributeError(f"module 'services' has no attribute {name!r}")
