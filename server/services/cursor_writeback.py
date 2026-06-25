"""Cursor 上报写回质量门槛（CURSOR-03 防噪音）。

Cursor 处理完成后经 MCP ``report_project_knowledge`` 上报沉淀，由 Friday 写入项目 memory
草稿。为防止低信息量/重复内容污染共享记忆，本模块在入库（草稿）前做**可配置质量门槛**过滤：

- **过短**：去空白后长度 < ``min_length``。
- **低信息量**：去重后的「实词」数 < ``min_distinct_words``（避免 "ok done"、纯标点等噪音）。
- **重复**：与既有 active 记忆中任一条的 token 集合 Jaccard 相似度 ≥ ``max_dup_ratio``。

阈值经 ``SettingKeys.CURSOR_WRITEBACK_CONFIG``（JSON）可配；缺省用本模块默认值。
脱敏在 ``MemoryService.create_draft`` 内置（``redact_secrets_in_text``），本模块只判质量、不改内容。
纯逻辑 + 一次设置读取，best-effort（读取失败回退默认，绝不阻断上报判定为拒收）。
"""

from __future__ import annotations

import json
import re

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = ["evaluate_writeback_quality", "WritebackThresholds"]

# 合理默认阈值（可经 SystemSetting 覆盖）。
_DEFAULT_MIN_LENGTH = 12
_DEFAULT_MIN_DISTINCT_WORDS = 3
_DEFAULT_MAX_DUP_RATIO = 0.85

# 拉丁词（连续字母数字下划线）或单个 CJK 字符——中文非空格分词，按字计 token，
# 避免一整句中文被当成 1 个 token 而误判低信息量。
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class WritebackThresholds:
    """质量门槛阈值（值对象）。"""

    def __init__(
        self,
        *,
        min_length: int = _DEFAULT_MIN_LENGTH,
        min_distinct_words: int = _DEFAULT_MIN_DISTINCT_WORDS,
        max_dup_ratio: float = _DEFAULT_MAX_DUP_RATIO,
    ) -> None:
        self.min_length = min_length
        self.min_distinct_words = min_distinct_words
        self.max_dup_ratio = max_dup_ratio


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def evaluate_quality_sync(
    content: str,
    existing_contents: list[str],
    thresholds: WritebackThresholds,
) -> tuple[bool, str]:
    """质量判定（纯函数）。返回 ``(ok, reason)``；``ok=False`` 时 ``reason`` 为拒收原因码。"""
    normalized = (content or "").strip()
    if len(normalized) < thresholds.min_length:
        return False, "too_short"

    tokens = _tokens(normalized)
    if len(tokens) < thresholds.min_distinct_words:
        return False, "low_information"

    for existing in existing_contents:
        if _jaccard(tokens, _tokens(existing)) >= thresholds.max_dup_ratio:
            return False, "duplicate"

    return True, ""


@sync_to_async
def _load_thresholds() -> WritebackThresholds:
    try:
        from system.models import SettingKeys, SystemSetting

        obj = SystemSetting.objects.filter(
            key=SettingKeys.CURSOR_WRITEBACK_CONFIG
        ).first()
        if obj is None or not obj.value:
            return WritebackThresholds()
        cfg = json.loads(obj.value)
        if not isinstance(cfg, dict):
            return WritebackThresholds()
        return WritebackThresholds(
            min_length=int(cfg.get("min_length", _DEFAULT_MIN_LENGTH)),
            min_distinct_words=int(
                cfg.get("min_distinct_words", _DEFAULT_MIN_DISTINCT_WORDS)
            ),
            max_dup_ratio=float(cfg.get("max_dup_ratio", _DEFAULT_MAX_DUP_RATIO)),
        )
    except Exception:  # noqa: BLE001 — 配置异常回退默认，绝不反噬
        return WritebackThresholds()


async def evaluate_writeback_quality(
    content: str,
    existing_contents: list[str],
) -> tuple[bool, str]:
    """评估上报内容是否达到入库（草稿）质量门槛（异步入口，读取可配阈值）。

    Args:
        content: 上报正文。
        existing_contents: 该项目既有 active 记忆正文（用于重复判定）。

    Returns:
        ``(ok, reason)``。``ok=True`` 表示通过；``False`` 时 ``reason`` ∈
        ``{too_short, low_information, duplicate}``。
    """
    thresholds = await _load_thresholds()
    return evaluate_quality_sync(content, existing_contents, thresholds)
