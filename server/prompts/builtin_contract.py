"""内置 Prompt 的 Python 字面量与 DB active body 契约。

契约检查属于运维路径，刻意与 ``render_prompt`` 热路径隔离，避免为每次对话增加
额外查询。chat 模块只能惰性导入，否则会与 ``prompts.services`` 形成循环依赖。
"""

from __future__ import annotations

import hashlib
import importlib
from typing import Any, TypedDict

from django.db import transaction
from django.db.models import Max

from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion

BuiltinContractEntry = tuple[str, str, str, str | None]

BUILTIN_CONTRACT_SLUGS: tuple[BuiltinContractEntry, ...] = (
    (PromptSlugs.AUX_TITLE_GENERATION, "chat.title_service", "TITLE_PROMPT", None),
    (
        PromptSlugs.CHAT_SYSTEM_DEVELOPER,
        "chat.conversation_service",
        "ROLE_PROMPTS",
        "developer",
    ),
    (PromptSlugs.CHAT_SYSTEM_PM, "chat.conversation_service", "ROLE_PROMPTS", "pm"),
    (
        PromptSlugs.CHAT_SYSTEM_DESIGNER,
        "chat.conversation_service",
        "ROLE_PROMPTS",
        "designer",
    ),
    (PromptSlugs.CHAT_SYSTEM_QA, "chat.conversation_service", "ROLE_PROMPTS", "qa"),
    (
        PromptSlugs.CHAT_SYSTEM_GENERAL,
        "chat.conversation_service",
        "ROLE_PROMPTS",
        "general",
    ),
    (
        PromptSlugs.CHAT_STRATEGY_DEFAULT,
        "chat.conversation_service",
        "_STRATEGY_DEFAULT",
        None,
    ),
    (
        PromptSlugs.CHAT_STRATEGY_DEEP_ANALYSIS,
        "chat.conversation_service",
        "_STRATEGY_DEEP_ANALYSIS",
        None,
    ),
    (
        PromptSlugs.CHAT_CODING_GUIDANCE,
        "chat.conversation_service",
        "_CODING_GUIDANCE",
        None,
    ),
    (
        PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
        "workflows.nodes.ai.variable_extractor",
        "EXTRACTION_PROMPT_TEMPLATE",
        None,
    ),
    (
        PromptSlugs.AI_NODE_CODE_REVIEW,
        "workflows.nodes.ai.code_review",
        "REVIEW_SYSTEM_PROMPT",
        None,
    ),
)


class BuiltinPromptDrift(TypedDict):
    slug: str
    reason: str
    py_sha256: str
    db_sha256: str | None
    py_length: int
    db_length: int | None


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def resolve_builtin_constant(
    module_path: str,
    attr_name: str,
    dict_key: str | None,
) -> str:
    """惰性解析常量，避免 Prompt 服务与 chat 模块在 import 阶段互相依赖。"""
    module = importlib.import_module(module_path)
    value: Any = getattr(module, attr_name)
    if dict_key is not None:
        value = value[dict_key]
    if not isinstance(value, str):
        raise TypeError(f"{module_path}.{attr_name} is not str")
    return value


def detect_builtin_prompt_drift() -> list[BuiltinPromptDrift]:
    """运维侧显式检查已部署 DB，弥补 fresh migrate 契约测试看不到存量漂移的缺口。"""
    drift: list[BuiltinPromptDrift] = []
    for slug, module_path, attr_name, dict_key in BUILTIN_CONTRACT_SLUGS:
        body = resolve_builtin_constant(module_path, attr_name, dict_key)
        py_hash = _sha256(body)
        try:
            prompt = Prompt.objects.select_related("active_version").get(
                slug=slug,
                scope=PromptScope.SYSTEM,
                space=None,
            )
        except Prompt.DoesNotExist:
            drift.append(
                {
                    "slug": slug,
                    "reason": "missing_prompt",
                    "py_sha256": py_hash,
                    "db_sha256": None,
                    "py_length": len(body),
                    "db_length": None,
                }
            )
            continue

        active = prompt.active_version
        if active is None:
            drift.append(
                {
                    "slug": slug,
                    "reason": "missing_active_version",
                    "py_sha256": py_hash,
                    "db_sha256": None,
                    "py_length": len(body),
                    "db_length": None,
                }
            )
            continue

        db_hash = _sha256(active.body)
        if db_hash != py_hash:
            drift.append(
                {
                    "slug": slug,
                    "reason": "body_mismatch",
                    "py_sha256": py_hash,
                    "db_sha256": db_hash,
                    "py_length": len(body),
                    "db_length": len(active.body),
                }
            )
    return drift


def resync_builtin_prompt_drift(slugs: list[str] | None = None) -> list[str]:
    """仅 append 并切 active，保留历史版本以降低运维修复的回滚风险。"""
    requested = set(slugs) if slugs is not None else None
    fixed: list[str] = []
    for slug, module_path, attr_name, dict_key in BUILTIN_CONTRACT_SLUGS:
        if requested is not None and slug not in requested:
            continue
        body = resolve_builtin_constant(module_path, attr_name, dict_key)
        with transaction.atomic():
            try:
                prompt = Prompt.objects.select_for_update().get(
                    slug=slug,
                    scope=PromptScope.SYSTEM,
                    space=None,
                )
            except Prompt.DoesNotExist:
                continue
            active = prompt.active_version
            if active is not None and active.body == body:
                continue
            max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
            new_version = PromptVersion.objects.create(
                prompt=prompt,
                version=max_v + 1,
                body=body,
                variables_schema={},
                change_note="运维修复：字节级对齐 Python builtin prompt 契约",
            )
            prompt.active_version = new_version
            prompt.save(update_fields=["active_version", "updated_at"])
            fixed.append(slug)
    return fixed
