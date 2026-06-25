"""Prompt 缓存失效 signal（contract 预埋 hook）。

只打日志，不做任何缓存删除（contract 无缓存）。
implementation+：若引入版本化缓存，在本 handler 中补充相应失效逻辑。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.db.models.signals import post_save
from django.dispatch import receiver

from prompts.models import Prompt

logger = structlog.get_logger(__name__)


@receiver(post_save, sender=Prompt)
def prompt_post_save_handler(
    sender: type[Prompt],
    instance: Prompt,
    created: bool,
    **kwargs: Any,
) -> None:
    """Prompt 保存后触发的缓存失效钩子（implementation 只打日志）。"""
    logger.info(
        "prompt_cache_invalidated",
        slug=instance.slug,
        scope=instance.scope,
        project_id=str(instance.space_id) if instance.space_id else None,
        created=created,
    )
