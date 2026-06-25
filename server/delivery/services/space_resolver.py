"""空间（Space）解析器：把用户给的「空间标识符」解析到 Space。

JSON 批量摄取里「空间」可写三种形态，本解析器按优先级依次尝试：

1. **系统 UUID**（``Space.id``）——精确。
2. **飞书项目 key**（``Space.feishu_project_key``，亦即 URL simple_name）——精确。
3. **人类可读名**（``Space.name``）——模糊：先精确名，再前缀/包含；唯一命中才算成功，
   多命中返回 ``ambiguous``（调用方据此提示用户改用 key/id 消歧）。

返回 ``(project, reason)``；``project`` 为 None 时 ``reason`` 说明原因
（``empty`` / ``ambiguous`` / ``not_found``）。
"""

from __future__ import annotations

import uuid

from projects.models import Space

__all__ = ["aresolve_space", "SpaceResolution"]


class SpaceResolution:
    """解析结果原因常量（前端展示/调试用）。"""

    BY_ID = "id"
    BY_KEY = "key"
    BY_NAME_EXACT = "name_exact"
    BY_NAME_FUZZY = "name_fuzzy"
    EMPTY = "empty"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def aresolve_space(identifier: str) -> tuple[Space | None, str]:
    """把空间标识符解析到 ``Space``；返回 ``(project, reason)``。"""
    ident = (identifier or "").strip()
    if not ident:
        return None, SpaceResolution.EMPTY

    # 1) 系统 UUID
    if _looks_like_uuid(ident):
        project = await Space.objects.filter(id=ident).afirst()
        if project is not None:
            return project, SpaceResolution.BY_ID

    # 2) 飞书项目 key（精确）
    project = await Space.objects.filter(feishu_project_key=ident).afirst()
    if project is not None:
        return project, SpaceResolution.BY_KEY

    # 3) 人类可读名（模糊）
    lowered = ident.lower()
    candidates = [p async for p in Space.objects.filter(name__icontains=ident)]
    if not candidates:
        return None, SpaceResolution.NOT_FOUND

    # 精确名（忽略大小写）唯一命中优先
    exact = [p for p in candidates if (p.name or "").lower() == lowered]
    if len(exact) == 1:
        return exact[0], SpaceResolution.BY_NAME_EXACT

    # 前缀命中优先（如「学习工具」→「学习工具与平台」）
    prefix = [p for p in candidates if (p.name or "").lower().startswith(lowered)]
    if len(prefix) == 1:
        return prefix[0], SpaceResolution.BY_NAME_FUZZY

    if len(candidates) == 1:
        return candidates[0], SpaceResolution.BY_NAME_FUZZY

    # 多命中无法消歧
    return None, SpaceResolution.AMBIGUOUS
