"""Artifact 类型注册表包（Chassis v2 · P1）。

每种 ``artifact_type`` 在此注册 content 校验器（+ 可选渲染器），使 ArtifactService
对任意类型走统一"校验→落库"路径。``technical_plan`` 为首个注册类型。
"""

# 触发内置类型注册（import 副作用）。
from delivery.artifacts import builtin_types  # noqa: E402, F401
from delivery.artifacts.registry import (
    ArtifactTypeDef,
    get_artifact_type,
    is_registered,
    register_artifact_type,
    registered_types,
    validate_content,
)

__all__ = [
    "ArtifactTypeDef",
    "register_artifact_type",
    "get_artifact_type",
    "is_registered",
    "registered_types",
    "validate_content",
]
