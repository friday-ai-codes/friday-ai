"""Artifact 类型注册表（Chassis v2 · P1）。

把"某 artifact_type 的 content 长什么样、如何校验、如何渲染 markdown"集中为
可注册定义，ArtifactService 据此对任意类型统一处理。新增交付物类型只需
``register_artifact_type(...)``，无需改 service 核心。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# validator(content) -> (ok, error_message)
ContentValidator = Callable[[dict], "tuple[bool, str | None]"]
# renderer(content) -> markdown
ContentRenderer = Callable[[dict], str]


@dataclass(frozen=True)
class ArtifactTypeDef:
    """一种 artifact_type 的定义。"""

    artifact_type: str
    validator: ContentValidator | None = None
    renderer: ContentRenderer | None = None


_REGISTRY: dict[str, ArtifactTypeDef] = {}


def register_artifact_type(
    artifact_type: str,
    *,
    validator: ContentValidator | None = None,
    renderer: ContentRenderer | None = None,
) -> None:
    """注册（或覆盖）一种 artifact_type 定义。"""
    _REGISTRY[artifact_type] = ArtifactTypeDef(
        artifact_type=artifact_type, validator=validator, renderer=renderer
    )


def get_artifact_type(artifact_type: str) -> ArtifactTypeDef | None:
    return _REGISTRY.get(artifact_type)


def is_registered(artifact_type: str) -> bool:
    return artifact_type in _REGISTRY


def registered_types() -> list[str]:
    return sorted(_REGISTRY.keys())


def validate_content(artifact_type: str, content: dict) -> tuple[bool, str | None]:
    """按类型注册的校验器校验 content；未注册类型视为非法。"""
    type_def = _REGISTRY.get(artifact_type)
    if type_def is None:
        return False, f"未注册的 artifact_type: {artifact_type}"
    if type_def.validator is None:
        return True, None
    return type_def.validator(content)


def render_markdown(artifact_type: str, content: dict) -> str | None:
    """按类型注册的渲染器渲染 markdown；无渲染器返回 None。"""
    type_def = _REGISTRY.get(artifact_type)
    if type_def is None or type_def.renderer is None:
        return None
    return type_def.renderer(content)
