"""Background scheduling for Feishu bot message processing."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def process_feishu_bot_message(message_id: str) -> dict[str, Any]:
    """Process a Feishu bot message.

    The full orchestration is implemented in later waves. The scheduler contract
    is introduced here so inbound dispatch can hand off quickly.
    """

    from feishu.bot.service import FeishuBotService

    logger.info("feishu_bot_message_processing_started", message_id=message_id)
    return await FeishuBotService().process_message(message_id)


def schedule_process_feishu_bot_message(message_id: str) -> None:
    """Schedule bot processing without blocking webhook acknowledgement."""

    async def runner() -> None:
        try:
            await process_feishu_bot_message(message_id)
        except Exception as exc:
            logger.exception("feishu_bot_message_processing_failed", message_id=message_id, error=str(exc))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(runner())
        return

    def _run() -> None:
        asyncio.run(runner())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
