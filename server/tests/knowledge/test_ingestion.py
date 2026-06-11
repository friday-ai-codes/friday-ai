"""统一摄取核心测试（Plan 13-02，INGEST-06/07/08）。

调度层（Task 1，A1 首验）：async 上下文经 ``sync_to_async`` 注册
``transaction.on_commit`` 的投递边界——autocommit 立即投递 / rollback 丢弃 /
异常永不上抛（"永不阻塞主流程"纪律）。

执行体（Task 2）：六步版本翻转事务序 + 四层幂等 + 边精细置位
（首摄 / 幂等三连发 / 版本翻转 / chaos 注入 / embedding abort / 边自愈）。

测试纪律（RESEARCH Pitfall 5/6）：执行体测试一律直接 ``await ingest_events(...)``
绕过调度层，不真跑 background worker 线程写库；Qdrant / embedding 全 mock，
``--disable-socket`` 是第二道保险。
"""

from __future__ import annotations

import sys
import types

import pytest
from asgiref.sync import async_to_sync
from django.db import transaction
from structlog.testing import capture_logs

from knowledge.ingestion import IngestionRequest, aschedule_ingestion
from knowledge.sources import get_normalizer

# SQLite + async（sync_to_async 跨线程）需要 transaction=True；
# 同时 on_commit 边界用例（autocommit 立即执行语义）也依赖真实事务。
pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# Task 1：调度层（aschedule_ingestion，A1 首验）
# ============================================================================


async def test_schedule_delivers_immediately_under_autocommit(monkeypatch) -> None:
    """A1 首验：autocommit 下 await 返回后 run_in_background 已被调用，name 含定位信息。"""
    submitted: list[str | None] = []
    monkeypatch.setattr(
        "knowledge.ingestion.run_in_background",
        lambda factory, *, name=None: submitted.append(name),
    )
    await aschedule_ingestion(IngestionRequest("coding_plan", "abc-123", "chat_plan_created"))
    assert len(submitted) == 1
    assert "coding_plan" in (submitted[0] or "")
    assert "abc-123" in (submitted[0] or "")


def test_schedule_not_delivered_on_rollback(monkeypatch) -> None:
    """A1 边界：atomic 块内注册、块内 raise 回滚后，run_in_background 未被调用。"""
    submitted: list[str | None] = []
    monkeypatch.setattr(
        "knowledge.ingestion.run_in_background",
        lambda factory, *, name=None: submitted.append(name),
    )
    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction.atomic():
            async_to_sync(aschedule_ingestion)(
                IngestionRequest("coding_plan", "abc-123", "chat_plan_created")
            )
            raise RuntimeError("force rollback")
    assert submitted == []


async def test_schedule_swallows_exceptions(monkeypatch) -> None:
    """异常隔离：run_in_background 抛异常 → aschedule_ingestion 不上抛 + structlog warning。"""

    def _boom(factory, *, name=None):
        raise RuntimeError("runner down")

    monkeypatch.setattr("knowledge.ingestion.run_in_background", _boom)
    with capture_logs() as cap:
        await aschedule_ingestion(IngestionRequest("coding_plan", "abc", "chat_plan_created"))
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "knowledge_ingest_schedule_failed" in warnings


# ============================================================================
# Task 1：sources 注册表（get_normalizer 惰性 import）
# ============================================================================


def test_get_normalizer_unknown_kind_raises_keyerror() -> None:
    """未知 source_kind 直接 KeyError（响亮，配置错误不可静默）。"""
    with pytest.raises(KeyError):
        get_normalizer("unknown_kind")


def test_get_normalizer_lazy_imports_registered_module(monkeypatch) -> None:
    """注册表惰性 import：注入 fake 模块（13-03 才落地真实 normalizer）。"""
    fake = types.ModuleType("knowledge.sources.coding_plan")

    async def normalize(request):
        return []

    fake.normalize = normalize  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "knowledge.sources.coding_plan", fake)
    assert get_normalizer("coding_plan") is normalize
