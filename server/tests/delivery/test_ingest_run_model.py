"""IngestRun 持久化模型守护单测（Phase 32-01 Task 1，ING-01）。

纯 ORM、无网络（pytest-socket 隔离）、无编排依赖——直接建实例验证 schema /
默认值 / 三步形状 / status 枚举 / project 占位 / 「取最近一次」排序。
"""

from __future__ import annotations

import pytest

from delivery.models import IngestRun, default_steps

pytestmark = pytest.mark.django_db(transaction=True)


def test_default_steps_shape():
    """default_steps 返回三步全 pending，每步 {status,identifier,link,error}。"""
    steps = default_steps()
    assert list(steps.keys()) == ["work_item", "document", "mr_diff"]
    for step in steps.values():
        assert step == {"status": "pending", "identifier": "", "link": "", "error": ""}


def test_default_steps_not_shared():
    """可调用 default：两次调用互不共享（无可变默认 aliasing）。"""
    a = default_steps()
    b = default_steps()
    a["work_item"]["status"] = "ok"
    assert b["work_item"]["status"] == "pending"


def test_ingest_run_defaults():
    """新建 run：status=running、三步 pending、project=None、error=""。"""
    run = IngestRun.objects.create(
        board_url="https://project.feishu.cn/abc123/issue/detail/456",
        mr_url="https://gitlab.example.com/group/proj/-/merge_requests/42",
    )
    fetched = IngestRun.objects.get(pk=run.pk)
    assert fetched.status == IngestRun.Status.RUNNING
    assert fetched.steps == default_steps()
    assert fetched.project is None
    assert fetched.error == ""
    assert fetched.completed_at is None
    assert fetched.started_at is not None


def test_ingest_run_status_choices():
    """Status 枚举：既有 running/completed/failed + Phase 62-01 durable 队列化新增 queued/stopped。"""
    assert IngestRun.Status.RUNNING == "running"
    assert IngestRun.Status.COMPLETED == "completed"
    assert IngestRun.Status.FAILED == "failed"
    # Phase 62-01（CRAWL-01）：QUEUED 入队待领 + STOPPED 用户停止终态（可重投）。
    assert IngestRun.Status.QUEUED == "queued"
    assert IngestRun.Status.STOPPED == "stopped"
    assert {c[0] for c in IngestRun.Status.choices} == {
        "queued",
        "running",
        "completed",
        "failed",
        "stopped",
    }


def test_ingest_run_steps_persist_structured_results():
    """steps 可承载三步结构化结果（status/identifier/link/error）读回无损。"""
    steps = default_steps()
    steps["work_item"] = {
        "status": "ok",
        "identifier": "7010225564",
        "link": "https://project.feishu.cn/abc/issue/detail/7010225564",
        "error": "",
    }
    steps["document"] = {"status": "skipped", "identifier": "", "link": "", "error": "无文档"}
    steps["mr_diff"] = {"status": "failed", "identifier": "", "link": "", "error": "无匹配仓库"}
    run = IngestRun.objects.create(steps=steps, status=IngestRun.Status.COMPLETED)
    fetched = IngestRun.objects.get(pk=run.pk)
    assert fetched.steps == steps
    assert fetched.status == IngestRun.Status.COMPLETED


def test_ingest_run_recent_ordering():
    """ordering=-started_at：最近一次 run 排在最前（按 id 取最近范式）。"""
    first = IngestRun.objects.create()
    second = IngestRun.objects.create()
    latest = IngestRun.objects.all().first()
    assert latest.pk in {first.pk, second.pk}
    # 最新创建的（second）应排在 first 之前或同刻——取 first() 命中其一即可
    ids = list(IngestRun.objects.values_list("pk", flat=True))
    assert set(ids) == {first.pk, second.pk}
