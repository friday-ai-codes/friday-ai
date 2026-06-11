"""reconcile / rebuild 对账命令测试（Plan 13-04，INGEST-06/07）。

覆盖 `reconcile_delivery_knowledge` 六检查项的检测（dry-run 默认零写）、
单点异常隔离（skip 不崩整命令）与 `--fix` 修复路径（Task 3 补全）；
以及 `rebuild_delivery_knowledge` 删建后全量重嵌入（Task 2 追加）。

测试纪律：Qdrant 经 ``mock_qdrant_client`` seam 注入漂移，修复动作
（revectorize / tombstone / delete / apply_edge_specs）一律 monkeypatch
模块属性为 AsyncMock，断言调用参数——绝不触真实向量库
（``--disable-socket`` 是第二道保险）。
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from django.core.management import call_command
from django.utils import timezone

from knowledge.models import EntityKind, EntityOrigin

# SQLite + async（命令内 asyncio.run + sync_to_async 跨线程）需要 transaction=True
pytestmark = pytest.mark.django_db(transaction=True)


def _record(point_id: str, **payload) -> SimpleNamespace:
    """构造 Qdrant retrieve/scroll 返回的 record 形态（id + payload）。"""
    return SimpleNamespace(id=point_id, payload=payload)


def _run_reconcile(*args: str) -> str:
    """跑 reconcile 命令并捕获 stdout（call_command + StringIO，命令范式）。"""
    out = io.StringIO()
    call_command("reconcile_delivery_knowledge", *args, stdout=out)
    return out.getvalue()


def _parse_summary(output: str) -> dict[str, int]:
    """解析末行 ``Summary: k=v ...`` 为计数 dict（test 断言锚点）。"""
    line = next(ln for ln in output.splitlines() if ln.startswith("Summary:"))
    pairs = (item.split("=") for item in line.removeprefix("Summary:").split())
    return {key: int(value) for key, value in pairs}


@pytest.fixture
def mock_fixers(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """全部修复动作的 AsyncMock seam（命令经模块属性调用，monkeypatch 即拦截）。"""
    fixers = {
        "revectorize": AsyncMock(),
        "tombstone": AsyncMock(),
        "delete": AsyncMock(),
        "apply_edges": AsyncMock(),
    }
    monkeypatch.setattr("knowledge.ingestion.revectorize_version", fixers["revectorize"])
    monkeypatch.setattr("knowledge.vector_ops.tombstone_points", fixers["tombstone"])
    monkeypatch.setattr("knowledge.vector_ops.delete_points", fixers["delete"])
    monkeypatch.setattr("knowledge.ingestion.apply_edge_specs", fixers["apply_edges"])
    return fixers


def _assert_zero_writes(fixers: dict[str, AsyncMock]) -> None:
    """dry-run 零写断言：四类修复动作均未被调用。"""
    for name, mock in fixers.items():
        assert mock.await_count == 0, f"dry-run 下 {name} 不应被调用"


# ============================================================================
# Task 1：漂移检测（dry-run 默认）+ 单点异常隔离
# ============================================================================


def _drift_scenario(entity_factory, version_factory, mock_qdrant_client) -> dict:
    """注入三类漂移：missing（检查项 1）、stale_latest（检查项 2）、missing_edges（检查项 6）。"""
    # 漂移 1：latest 版本有 point ids 但 Qdrant 查无此点 → missing
    e_missing = entity_factory(
        kind=EntityKind.TECH_PLAN, origin=EntityOrigin.CHAT, source_kind="coding_plan"
    )
    missing_pid = str(uuid.uuid4())
    v_missing = version_factory(
        e_missing, qdrant_point_ids=[missing_pid], vector_synced=True
    )

    # 漂移 2：非 latest 版本的点 payload 仍 is_latest=true → stale_latest
    e_stale = entity_factory()
    stale_pid = str(uuid.uuid4())
    version_factory(
        e_stale, is_latest=False, qdrant_point_ids=[stale_pid], vector_synced=True
    )

    # 漂移 3：origin=mcp 且 kind=tech_plan 的 latest 实体无活跃 HAS_PLAN 入边 → missing_edges
    e_no_edge = entity_factory(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.MCP,
        source_kind="mcp_technical_plan",
    )
    ok_pid = str(uuid.uuid4())
    v_ok = version_factory(e_no_edge, qdrant_point_ids=[ok_pid], vector_synced=True)

    def _retrieve(collection_name, ids, with_payload=None):
        records = []
        for pid in ids:
            if pid == stale_pid:
                records.append(_record(pid, is_latest=True))
            elif pid == ok_pid:
                # e_no_edge 的向量完好（检查项 1 不报），只缺边（检查项 6 报）
                records.append(_record(pid, is_latest=True, version=v_ok.version))
        return records

    mock_qdrant_client.retrieve.side_effect = _retrieve
    mock_qdrant_client.scroll.return_value = ([], None)
    return {
        "missing_version": v_missing,
        "stale_pid": stale_pid,
        "no_edge_entity": e_no_edge,
    }


def test_detect_drift_reports_missing_stale_and_missing_edges(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers
) -> None:
    """漂移检测：missing / stale_latest / missing_edges 各计 1，六计数齐现 Summary 行。"""
    _drift_scenario(entity_factory, version_factory, mock_qdrant_client)

    output = _run_reconcile()
    summary = _parse_summary(output)

    assert summary["missing"] == 1
    assert summary["stale_latest"] == 1
    assert summary["missing_edges"] == 1
    assert summary["multi_latest"] == 0
    assert summary["orphans"] == 0
    assert summary["db_anomalies"] == 0
    assert summary["checked"] >= 2  # 两个 latest 版本被检查
    assert summary["fixed"] == 0


def test_dry_run_detect_zero_write(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers
) -> None:
    """dry-run 零写：注入漂移但无 --fix → 四类修复动作零调用，Qdrant 零写副作用。"""
    _drift_scenario(entity_factory, version_factory, mock_qdrant_client)

    _run_reconcile()

    _assert_zero_writes(mock_fixers)
    assert mock_qdrant_client.set_payload.call_count == 0
    assert mock_qdrant_client.upsert.call_count == 0
    assert mock_qdrant_client.delete.call_count == 0


def test_item_exception_skips_without_crash(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers
) -> None:
    """单点异常隔离：retrieve 抛异常 → 该项 skip 计数 +1，命令完整跑完（退出码 0）。"""
    entity = entity_factory(kind=EntityKind.TECH_PLAN, origin=EntityOrigin.CHAT)
    version_factory(entity, qdrant_point_ids=[str(uuid.uuid4())], vector_synced=True)

    mock_qdrant_client.retrieve.side_effect = RuntimeError("qdrant down")
    mock_qdrant_client.scroll.return_value = ([], None)

    # call_command 正常返回即退出码 0（异常会直接 raise 让测试失败）
    output = _run_reconcile()
    summary = _parse_summary(output)

    assert summary["skipped"] >= 1
    _assert_zero_writes(mock_fixers)
