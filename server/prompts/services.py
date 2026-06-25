"""Prompt 核心查询与渲染服务。

决策依据（work-item.md）：
- contract 无缓存：每次调用直连 DB
- contract StrictUndefined + 声明前置校验
- contract 变量三步清洗（长度截断 / {{}} 转义 / XML tag 包裹）
- contract append-only 版本化 + 幂等字节级比对
- contract declared_variables 运行时 regex 计算
- contract PROMPT_CENTER_DISABLED_KEYS 环境变量灰度开关
"""

from __future__ import annotations

import os
import re
from difflib import unified_diff
from typing import Any, Final

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Max
from jinja2 import UndefinedError
from jinja2.exceptions import SecurityError, TemplateError

from prompts.engine import get_jinja_env
from prompts.exceptions import (
    PromptError,
    PromptNotFoundError,
    PromptRenderError,
    PromptVariableMissingError,
)
from prompts.keys import BUILTIN_SLUGS
from prompts.models import Prompt, PromptScope, PromptVersion

logger = structlog.get_logger(__name__)

# 变量声明正则（contract + contract）
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}"
)

# 变量值清洗阈值（contract）
VARIABLE_MAX_LENGTH: Final[int] = 1024


def get_declared_variables(body: str) -> list[str]:
    """从 body 派生已声明变量列表（contract 运行时 regex）。

    返回有序、去重的变量名列表（按出现顺序）。
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(body):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _get_disabled_keys() -> set[str]:
    """从 os.environ 读 PROMPT_CENTER_DISABLED_KEYS 灰度开关（contract）。

    每次调用都读 —— 支持运行时热更新（容器 ENV 改动）。
    """
    raw = os.environ.get("PROMPT_CENTER_DISABLED_KEYS", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def _sanitize_variables(
    variables: dict[str, Any],
    *,
    slug: str,
) -> dict[str, str]:
    """变量值三步清洗（contract），仅用于 DB 渲染路径，不用于 fallback。"""
    cleaned: dict[str, str] = {}
    for key, value in variables.items():
        text = str(value) if value is not None else ""
        # Step 1: 长度截断
        if len(text) > VARIABLE_MAX_LENGTH:
            logger.warning(
                "prompt_variable_truncated",
                slug=slug,
                var=key,
                original_len=len(text),
                max_len=VARIABLE_MAX_LENGTH,
            )
            text = text[:VARIABLE_MAX_LENGTH]
        # Step 2: 禁止二次渲染 —— {{ / }} 转 HTML entity
        text = text.replace("{{", "&#123;&#123;").replace("}}", "&#125;&#125;")
        # Step 3: XML tag 包裹
        cleaned[key] = f"<{key}>{text}</{key}>"
    return cleaned


async def get_active_prompt(
    slug: str,
    *,
    project_id: str | None = None,
) -> PromptVersion | None:
    """按 slug 解析活跃 PromptVersion。

    解析顺序（contract 无缓存）：
      1. 若给定 project_id，查 scope=project 的覆盖
      2. fallback 到 scope=system

    未命中返回 None。调用方（render_prompt）负责降级到 fallback 参数。
    """
    version: PromptVersion | None = None
    if project_id:
        prompt = await (
            Prompt.objects.filter(
                slug=slug,
                scope=PromptScope.PROJECT,
                space_id=project_id,
                active_version__isnull=False,
            )
            .select_related("active_version", "active_version__prompt")
            .afirst()
        )
        if prompt is not None:
            version = prompt.active_version

    if version is None:
        prompt = await (
            Prompt.objects.filter(
                slug=slug,
                scope=PromptScope.SYSTEM,
                active_version__isnull=False,
            )
            .select_related("active_version", "active_version__prompt")
            .afirst()
        )
        if prompt is not None:
            version = prompt.active_version

    return version


def _check_declared_vars(
    template_body: str,
    variables: dict[str, Any],
    *,
    slug: str,
) -> None:
    """contract 第一层校验：声明集合 vs 传入集合。"""
    declared = set(_PLACEHOLDER_RE.findall(template_body))
    passed = set(variables.keys())
    missing = declared - passed
    if missing:
        raise PromptVariableMissingError(
            slug=slug,
            missing=sorted(missing),
        )


def _render_fallback(
    slug: str,
    fallback: str,
    variables: dict[str, Any],
) -> str:
    """fallback 路径（contract）：跳过 contract 清洗但走 contract 声明校验。

    直接 regex 替换；不走 Jinja2 sandbox，避免 fallback 字符串触发沙箱误报。
    """
    _check_declared_vars(fallback, variables, slug=slug)
    return _PLACEHOLDER_RE.sub(
        lambda m: str(variables.get(m.group(1), "")),
        fallback,
    )


async def render_prompt(
    slug: str,
    *,
    project_id: str | None = None,
    variables: dict[str, Any] | None = None,
    fallback: str = "",
) -> str:
    """渲染提示词的统一入口（implementation 对外 API）。

    流程：
      1. 读 PROMPT_CENTER_DISABLED_KEYS（contract）— 命中直接 fallback
      2. 查 active PromptVersion（contract 无缓存）
      3. 未命中 → fallback（走 _render_fallback，跳过 XML 清洗）
      4. 命中 → 声明校验（contract）→ 变量清洗（contract）→ Jinja2 sandbox 渲染
      5. 捕获 UndefinedError / SecurityError / TemplateError → 包装为 PromptRenderError

    Raises:
        PromptVariableMissingError: 声明变量 ⊄ 传入变量（422）
        PromptNotFoundError: slug ∈ BUILTIN_SLUGS 但 DB 无记录且 fallback 为空（404）
        PromptRenderError: Jinja2 渲染内部故障（500）
    """
    variables = variables or {}

    # Step 1: 灰度开关（contract）
    if slug in _get_disabled_keys():
        logger.info(
            "prompt_disabled_by_flag",
            slug=slug,
            scope="fallback",
            project_id=project_id,
            fallback_used=True,
        )
        if not fallback:
            raise PromptNotFoundError(slug=slug)
        return _render_fallback(slug, fallback, variables)

    # Step 2: 查 DB
    version = await get_active_prompt(slug, project_id=project_id)

    # Step 3: 未命中 → fallback
    if version is None:
        logger.warning(
            "prompt_not_found",
            slug=slug,
            project_id=project_id,
            fallback_used=bool(fallback),
        )
        if not fallback:
            # 仅当 slug 在 BUILTIN_SLUGS 内却 DB 无记录 → 系统 bug（implementation seed 应补齐）
            if slug in BUILTIN_SLUGS:
                logger.error("prompt_builtin_missing_from_db", slug=slug)
            raise PromptNotFoundError(slug=slug)
        return _render_fallback(slug, fallback, variables)

    # Step 4: 命中 → 声明校验 + 清洗 + 渲染
    body = version.body
    _check_declared_vars(body, variables, slug=slug)

    try:
        sanitized = _sanitize_variables(variables, slug=slug)
        env = get_jinja_env()
        template = env.from_string(body)
        rendered = template.render(**sanitized)
    except UndefinedError as e:
        # StrictUndefined 兜底（理论上已被 _check_declared_vars 前置拦截）
        logger.error("prompt_render_undefined", slug=slug, reason=str(e))
        raise PromptRenderError(
            slug=slug,
            reason=f"undefined_variable: {e}",
        ) from e
    except SecurityError as e:
        logger.error("prompt_render_security", slug=slug, reason=str(e))
        raise PromptRenderError(
            slug=slug,
            reason=f"sandbox_security: {e}",
        ) from e
    except TemplateError as e:
        logger.error("prompt_render_template", slug=slug, reason=str(e))
        raise PromptRenderError(
            slug=slug,
            reason=f"template_error: {e}",
        ) from e

    logger.info(
        "prompt_rendered",
        slug=slug,
        scope=version.prompt.scope,
        project_id=project_id,
        variables_count=len(variables),
        body_length=len(rendered),
        fallback_used=False,
    )
    return rendered


# ============================================================================
# 版本管理（contract append-only + 幂等 + 事务）
# ============================================================================


def _append_version_sync(
    prompt: Prompt,
    new_body: str,
    user: Any,
    change_note: str = "",
) -> PromptVersion:
    """同步事务逻辑：追加新版本 + 激活。调用方必须用 sync_to_async 包装。

    contract 幂等保护：若 new_body == active_version.body 字节级相等，跳过创建。
    """
    with transaction.atomic():
        locked_prompt = Prompt.objects.select_for_update().get(pk=prompt.pk)

        # 幂等：字节级比对
        active = locked_prompt.active_version
        if active is not None and active.body == new_body:
            logger.info(
                "prompt_version_skipped_idempotent",
                slug=locked_prompt.slug,
                active_version=active.version,
            )
            return active

        # 计算新版本号
        max_version = (
            locked_prompt.versions.aggregate(max_v=Max("version"))["max_v"] or 0
        )
        new_version = PromptVersion.objects.create(
            prompt=locked_prompt,
            version=max_version + 1,
            body=new_body,
            created_by=user if user and user.is_authenticated else None,
            change_note=change_note,
        )
        locked_prompt.active_version = new_version
        locked_prompt.save(update_fields=["active_version", "updated_at"])

        logger.info(
            "prompt_version_created",
            slug=locked_prompt.slug,
            version=new_version.version,
            body_length=len(new_body),
        )
        return new_version


async def append_version(
    prompt: Prompt,
    new_body: str,
    user: Any,
    change_note: str = "",
) -> PromptVersion:
    """异步 API：追加新版本并激活。"""
    return await sync_to_async(_append_version_sync)(
        prompt, new_body, user, change_note,
    )


def _activate_version_sync(
    prompt: Prompt,
    target_version: PromptVersion,
) -> None:
    """同步事务：切换 active_version 指针（回滚通道，不创新版本）。"""
    if target_version.prompt_id != prompt.pk:
        raise PromptError("version_not_belong_to_prompt")

    with transaction.atomic():
        locked_prompt = Prompt.objects.select_for_update().get(pk=prompt.pk)
        locked_prompt.active_version = target_version
        locked_prompt.save(update_fields=["active_version", "updated_at"])

        logger.info(
            "prompt_version_activated",
            slug=locked_prompt.slug,
            version=target_version.version,
        )


async def activate_version(
    prompt: Prompt,
    target_version: PromptVersion,
) -> None:
    """异步 API：切换激活版本。"""
    await sync_to_async(_activate_version_sync)(prompt, target_version)


# ============================================================================
# 版本 diff（Plan-02 API 依赖）
# ============================================================================


def compute_version_diff(v1: PromptVersion, v2: PromptVersion) -> str:
    """计算两个版本 body 的 unified diff（供 API 返回）。

    前端 implementation 用 jsdiff 再次 render；后端只返回原始 diff text。
    """
    lines = list(
        unified_diff(
            v1.body.splitlines(keepends=True),
            v2.body.splitlines(keepends=True),
            fromfile=f"v{v1.version}",
            tofile=f"v{v2.version}",
            lineterm="",
            n=3,
        )
    )
    return "".join(lines)
