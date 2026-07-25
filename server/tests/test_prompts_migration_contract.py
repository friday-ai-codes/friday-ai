"""implementation data migration 字节级 hash 契约测试。

清单以 ``CONTRACT_SLUGS`` 为准（随 seed 迁移增删同步），不写死条目数。

目的：防止任一方（Python 常量 / DB body）漂移。
任一方改动都会触发测试红灯，强制开发者同步另一方。
参考 v17.0 ALL_EVENT_TYPES frozenset 契约模式。
"""
from __future__ import annotations

import hashlib
import importlib
from typing import Any

import pytest

from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# (slug, module_path, attr_name, dict_key_or_None)
CONTRACT_SLUGS: list[tuple[str, str, str, str | None]] = [
    (PromptSlugs.AUX_TITLE_GENERATION, "chat.title_service", "TITLE_PROMPT", None),
    (PromptSlugs.CHAT_SYSTEM_DEVELOPER, "chat.conversation_service", "ROLE_PROMPTS", "developer"),
    (PromptSlugs.CHAT_SYSTEM_PM, "chat.conversation_service", "ROLE_PROMPTS", "pm"),
    (PromptSlugs.CHAT_SYSTEM_DESIGNER, "chat.conversation_service", "ROLE_PROMPTS", "designer"),
    (PromptSlugs.CHAT_SYSTEM_QA, "chat.conversation_service", "ROLE_PROMPTS", "qa"),
    (PromptSlugs.CHAT_SYSTEM_GENERAL, "chat.conversation_service", "ROLE_PROMPTS", "general"),
    (PromptSlugs.CHAT_STRATEGY_DEFAULT, "chat.conversation_service", "_STRATEGY_DEFAULT", None),
    (PromptSlugs.CHAT_STRATEGY_DEEP_ANALYSIS, "chat.conversation_service", "_STRATEGY_DEEP_ANALYSIS", None),
    (PromptSlugs.CHAT_CODING_GUIDANCE, "chat.conversation_service", "_CODING_GUIDANCE", None),
    (PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR, "workflows.nodes.ai.variable_extractor", "EXTRACTION_PROMPT_TEMPLATE", None),
    (PromptSlugs.AI_NODE_CODE_REVIEW, "workflows.nodes.ai.code_review", "REVIEW_SYSTEM_PROMPT", None),
]
# ai_node.plan_generation.system 不在清单内：Chassis v2 删除 ai_plan_generation 节点后，
# prompts/migrations/0002 的 seed 条目对 `_PLAN_GENERATION_BASE_PROMPT` 做了 ImportError
# 跳过、0009 的 resync 变成 no-op，该 slug 已不再入库（PromptSlugs 常量仅作历史保留）。


def _resolve_constant(module_path: str, attr_name: str, dict_key: str | None) -> str:
    mod = importlib.import_module(module_path)
    value: Any = getattr(mod, attr_name)
    if dict_key is not None:
        value = value[dict_key]
    assert isinstance(value, str), f"{module_path}.{attr_name} is not str"
    return value


@pytest.mark.django_db
class TestPromptMigrationContract:
    """implementation seed slug 的字节级契约测试。"""

    @pytest.mark.parametrize(
        "slug,module_path,attr_name,dict_key",
        CONTRACT_SLUGS,
        ids=[c[0] for c in CONTRACT_SLUGS],
    )
    def test_db_body_matches_python_constant(
        self,
        slug: str,
        module_path: str,
        attr_name: str,
        dict_key: str | None,
    ) -> None:
        """DB 里的 active body 必须与 Python 常量字节级相等。"""
        py_constant = _resolve_constant(module_path, attr_name, dict_key)
        py_hash = _sha256(py_constant)

        prompt = Prompt.objects.select_related("active_version").get(
            slug=slug,
            scope=PromptScope.SYSTEM,
            space=None,
        )
        assert prompt.active_version is not None, (
            f"Prompt {slug} has no active_version"
        )
        db_body = prompt.active_version.body
        db_hash = _sha256(db_body)

        assert db_hash == py_hash, (
            f"Byte drift detected for slug={slug}:\n"
            f"  Python constant ({module_path}.{attr_name}"
            f"{'[' + dict_key + ']' if dict_key else ''}): sha256={py_hash}\n"
            f"  DB body (Prompt {prompt.id}): sha256={db_hash}\n"
            f"  Fix: rerun `cd server && uv run python manage.py migrate prompts` "
            f"OR update Python constant to match DB"
        )

    def test_all_seed_slugs_present(self) -> None:
        """CONTRACT_SLUGS 里的系统级 is_builtin slug 都必须在 DB。"""
        slugs_in_db = set(
            Prompt.objects.filter(
                scope=PromptScope.SYSTEM,
                is_builtin=True,
            ).values_list("slug", flat=True)
        )
        expected = {c[0] for c in CONTRACT_SLUGS}
        missing = expected - slugs_in_db
        assert not missing, (
            f"Missing seed slugs: {sorted(missing)}\n"
            f"Expected {len(expected)} seed slugs, got {len(slugs_in_db & expected)}"
        )
