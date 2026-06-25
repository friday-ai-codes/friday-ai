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

from knowledge.ingestion import EdgeSpec, IngestionEvent
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

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
    v_missing = version_factory(e_missing, qdrant_point_ids=[missing_pid], vector_synced=True)

    # 漂移 2：非 latest 版本的点 payload 仍 is_latest=true → stale_latest
    e_stale = entity_factory()
    stale_pid = str(uuid.uuid4())
    version_factory(e_stale, is_latest=False, qdrant_point_ids=[stale_pid], vector_synced=True)

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


# ============================================================================
# Task 2：rebuild_delivery_knowledge 删建后全量重嵌入
# ============================================================================


def _setup_rebuild_env(mock_qdrant_client) -> None:
    """rebuild 路径的 Qdrant mock：collection 不存在 → ensure 走创建分支。"""
    mock_qdrant_client.get_collections.return_value = SimpleNamespace(collections=[])


def _run_rebuild() -> str:
    out = io.StringIO()
    call_command("rebuild_delivery_knowledge", "--yes", stdout=out)
    return out.getvalue()


def test_rebuild_reembeds_all_latest_versions(
    entity_factory, version_factory, mock_qdrant_client, monkeypatch
) -> None:
    """rebuild --yes：删建后逐个 latest 版本调 revectorize_version（2 个 → 2 次）。"""
    reembed = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.revectorize_version", reembed)
    _setup_rebuild_env(mock_qdrant_client)

    v1 = version_factory(entity_factory(), vector_synced=True)
    v2 = version_factory(entity_factory(), vector_synced=True)
    # 非 latest 版本不得进入重嵌入（P10：旧版本不进检索面）
    version_factory(entity_factory(), is_latest=False)

    output = _run_rebuild()

    assert reembed.await_count == 2
    reembedded_ids = {call.args[0].id for call in reembed.await_args_list}
    assert reembedded_ids == {v1.id, v2.id}
    assert "reembedded=2" in output
    assert "failed=0" in output


def test_rebuild_reembed_failure_does_not_abort(
    entity_factory, version_factory, mock_qdrant_client, monkeypatch
) -> None:
    """单版本重嵌入失败不中断全量循环：失败计数出现在输出，其余版本照常重嵌入。"""
    calls: list[uuid.UUID] = []

    async def _flaky(version):
        calls.append(version.id)
        if len(calls) == 1:
            raise RuntimeError("embedding api down")

    monkeypatch.setattr("knowledge.ingestion.revectorize_version", _flaky)
    _setup_rebuild_env(mock_qdrant_client)

    version_factory(entity_factory(), vector_synced=True)
    version_factory(entity_factory(), vector_synced=True)

    output = _run_rebuild()

    assert len(calls) == 2  # 失败后循环未中断
    assert "reembedded=1" in output
    assert "failed=1" in output


# ============================================================================
# Task 3：--fix 修复路径断言（调用参数级）
# ============================================================================


def test_fix_repairs_missing_stale_and_orphan(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers
) -> None:
    """--fix 三类修复：missing → revectorize；stale → tombstone+delete；orphan → delete。"""
    # missing：latest 版本有 point ids 但 Qdrant 查无此点
    e_missing = entity_factory(
        kind=EntityKind.TECH_PLAN, origin=EntityOrigin.CHAT, source_kind="coding_plan"
    )
    missing_pid = str(uuid.uuid4())
    v_missing = version_factory(e_missing, qdrant_point_ids=[missing_pid], vector_synced=True)

    # stale：非 latest 版本的点 payload 仍 is_latest=true
    e_stale = entity_factory()
    stale_pid = str(uuid.uuid4())
    version_factory(e_stale, is_latest=False, qdrant_point_ids=[stale_pid], vector_synced=True)

    # orphan：scroll 返回的点 payload.version_id 不在 PG
    orphan_pid = str(uuid.uuid4())
    orphan_record = _record(
        orphan_pid,
        entity_id=str(uuid.uuid4()),
        version=1,
        version_id=str(uuid.uuid4()),
        is_latest=True,
    )

    def _retrieve(collection_name, ids, with_payload=None):
        return [_record(stale_pid, is_latest=True)] if stale_pid in ids else []

    mock_qdrant_client.retrieve.side_effect = _retrieve
    mock_qdrant_client.scroll.return_value = ([orphan_record], None)

    output = _run_reconcile("--fix")
    summary = _parse_summary(output)

    # missing → revectorize_version 被调，参数为漂移版本本体
    assert mock_fixers["revectorize"].await_count == 1
    assert mock_fixers["revectorize"].await_args.args[0].id == v_missing.id
    # stale → tombstone + delete（point id 列表逐项比对）
    mock_fixers["tombstone"].assert_awaited_once_with([stale_pid])
    delete_calls = [call.args[0] for call in mock_fixers["delete"].await_args_list]
    assert [stale_pid] in delete_calls
    # orphan → delete（按 point id 列表）
    assert [orphan_pid] in delete_calls
    assert summary["fixed"] == 3


def test_fix_missing_edges_applies_edge_specs(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers, monkeypatch
) -> None:
    """--fix 检查项 6：经 fake normalizer 取 EdgeSpec 后 apply_edge_specs 被调（参数级断言）。"""
    e_plan = entity_factory(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.MCP,
        source_kind="mcp_technical_plan",
    )
    ok_pid = str(uuid.uuid4())
    v_plan = version_factory(e_plan, qdrant_point_ids=[ok_pid], vector_synced=True)
    mock_qdrant_client.retrieve.side_effect = lambda collection_name, ids, with_payload=None: (
        [_record(ok_pid, is_latest=True, version=v_plan.version)] if ok_pid in ids else []
    )
    mock_qdrant_client.scroll.return_value = ([], None)

    event_time = timezone.now()
    edge = EdgeSpec(relation=EdgeRelation.HAS_PLAN, target_entity_id=e_plan.id, exclusive=True)
    anchor_event = IngestionEvent(
        kind="work_item",
        origin="mcp",
        source_kind="feishu_work_item",
        source_id="PROJ:story:42",
        title="工作项锚",
        content="工作项锚",
        payload={},
        space_id=None,
        repository_id=None,
        event_time=event_time,
        edges=(edge,),
    )

    async def fake_normalize(request):
        assert request.source_id == e_plan.source_id
        return [anchor_event]

    monkeypatch.setattr("knowledge.sources.get_normalizer", lambda source_kind: fake_normalize)

    output = _run_reconcile("--fix")
    summary = _parse_summary(output)

    assert summary["missing_edges"] == 1
    expected_source = generate_entity_id("work_item", "feishu_work_item", "PROJ:story:42")
    mock_fixers["apply_edges"].assert_awaited_once_with(
        expected_source, (edge,), event_time=event_time
    )
    assert summary["fixed"] == 1


def test_fix_missing_edges_source_missing_skips(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers, monkeypatch
) -> None:
    """--fix 检查项 6 边界：normalizer 源对象已删（返回空事件）→ skip+warning 不崩。"""
    e_plan = entity_factory(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.MCP,
        source_kind="mcp_technical_plan",
    )
    ok_pid = str(uuid.uuid4())
    v_plan = version_factory(e_plan, qdrant_point_ids=[ok_pid], vector_synced=True)
    mock_qdrant_client.retrieve.side_effect = lambda collection_name, ids, with_payload=None: (
        [_record(ok_pid, is_latest=True, version=v_plan.version)] if ok_pid in ids else []
    )
    mock_qdrant_client.scroll.return_value = ([], None)

    async def fake_normalize(request):
        return []  # 源对象已删：normalizer 契约返回空列表

    monkeypatch.setattr("knowledge.sources.get_normalizer", lambda source_kind: fake_normalize)

    output = _run_reconcile("--fix")
    summary = _parse_summary(output)

    assert summary["missing_edges"] == 1
    assert summary["skipped"] >= 1
    assert mock_fixers["apply_edges"].await_count == 0
    assert summary["fixed"] == 0


def test_fix_pitfall2_vector_missing_detected_and_reembedded(
    entity_factory, version_factory, mock_qdrant_client, mock_fixers
) -> None:
    """Pitfall 2 端到端：hash 短路掩盖向量缺失（vector_synced=False + Qdrant 无点）
    由检查项 1 检出，--fix 后 revectorize_version 被调（同时计入 DB 不变量抽检）。"""
    entity = entity_factory(
        kind=EntityKind.TECH_PLAN, origin=EntityOrigin.CHAT, source_kind="coding_plan"
    )
    version = version_factory(entity, qdrant_point_ids=[str(uuid.uuid4())], vector_synced=False)

    mock_qdrant_client.retrieve.return_value = []  # Qdrant 无该版本任何点
    mock_qdrant_client.scroll.return_value = ([], None)

    output = _run_reconcile("--fix")
    summary = _parse_summary(output)

    assert summary["missing"] == 1
    assert summary["db_anomalies"] == 1  # vector_synced=False 的 latest 被抽检报告
    assert mock_fixers["revectorize"].await_count == 1
    assert mock_fixers["revectorize"].await_args.args[0].id == version.id
