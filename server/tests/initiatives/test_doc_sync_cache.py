"""doc_sync_cache read-through 缓存单测（83-05 / SYNC-05）。

覆盖四路径：
- 命中：set 后 get 返回缓存值（不查 DB）。
- 未命中：未 set / 已失效 → get 返回 None（调用方降级读 DB 回填）。
- 失效：invalidate 用 ``cache.delete``（非 set 空），失效后 get 返回 None。
- redis 故障降级：``cache.get`` 抛异常 → ``get_doc_render`` 返回 None 不抛 + 记一次
  ``doc_render_cache_degraded``（绝不反噬主流程）。

不依赖 DB / 飞书外呼：用 ``override_settings`` 强制 LocMemCache，纯内存验证缓存语义。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from initiatives.services.doc_sync_cache import (
    doc_render_cache_key,
    get_doc_render,
    invalidate_doc_render,
    set_doc_render,
)

# 强制本地内存缓存：与 redis / IGNORE_EXCEPTIONS 解耦，专测模块自身的 read-through 语义。
_LOCMEM = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

_MODULE_FILE = (
    Path(__file__).resolve().parents[2]
    / "initiatives"
    / "services"
    / "doc_sync_cache.py"
)


def test_cache_key_format() -> None:
    assert doc_render_cache_key(123) == "projdoc:render:123"
    assert doc_render_cache_key("abc") == "projdoc:render:abc"


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_set_then_get_hit() -> None:
    cache.clear()
    set_doc_render(7, "<rendered markdown>")
    # 命中：直接返回缓存值，无需读 DB。
    assert get_doc_render(7) == "<rendered markdown>"


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_get_miss_returns_none() -> None:
    cache.clear()
    # 未写入 → 未命中 → None（调用方据此降级读 DB 回填）。
    assert get_doc_render(404) is None


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_invalidate_then_get_miss() -> None:
    cache.clear()
    set_doc_render(9, "v1")
    assert get_doc_render(9) == "v1"
    invalidate_doc_render(9)
    # 失效后再读应未命中（delete 而非 set 空）。
    assert get_doc_render(9) is None


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_invalidate_uses_delete_not_set_empty() -> None:
    cache.clear()
    set_doc_render(11, "v1")
    with patch.object(cache, "delete") as mock_delete, patch.object(cache, "set") as mock_set:
        invalidate_doc_render(11)
    mock_delete.assert_called_once_with(doc_render_cache_key(11))
    # 失效绝不走 set（防 set 空值穿透 / 脏读）。
    mock_set.assert_not_called()


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_get_degrades_to_none_when_cache_raises() -> None:
    cache.clear()
    # 模拟 redis 抖动 / 不可用：cache.get 抛异常 → get_doc_render 静默降级返回 None 不抛。
    with patch.object(cache, "get", side_effect=RuntimeError("redis down")):
        with patch("initiatives.services.doc_sync_cache.logger") as mock_logger:
            result = get_doc_render(13)
    assert result is None
    # 记一次 degraded 事件（sampling / debug）。
    mock_logger.debug.assert_called_once()
    assert mock_logger.debug.call_args.args[0] == "doc_render_cache_degraded"


@override_settings(CACHES=_LOCMEM, DOC_RENDER_CACHE_TTL=300)
def test_set_and_invalidate_swallow_cache_errors() -> None:
    cache.clear()
    # 写 / 失效路径同样吞异常，绝不反噬主流程。
    with patch.object(cache, "set", side_effect=RuntimeError("redis down")):
        set_doc_render(15, "v1")  # 不抛
    with patch.object(cache, "delete", side_effect=RuntimeError("redis down")):
        invalidate_doc_render(15)  # 不抛


def test_degraded_log_carries_no_render_body() -> None:
    """静态守护：degraded 日志只记 doc_id / op / error_type，绝不落渲染正文。"""
    text = _MODULE_FILE.read_text(encoding="utf-8")
    # 失效必须用 cache.delete（非 set 空）。
    assert "cache.delete(key)" in text
    # degraded 事件不得把 value / 渲染正文塞进日志字段。
    assert "value=" not in text
    assert "render=" not in text
