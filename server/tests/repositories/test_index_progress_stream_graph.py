"""Phase Plan / GRAPH-：``IndexProgressStreamView`` 帧 payload
扩展 graph 顶层段 + 终止条件追加 ``graph_build_status != RUNNING`` 判定的端到端测试。
覆盖：
1. graph 字段顶层存在（``frame["graph"]`` 一定有，与 ``repository`` / ``running_history``
 平级）
2. 9 字段 schema：status / stage / files_processed / files_total / percent /
 current_file / started_at / edge_count_so_far / error_message
3. percent 边界：files_total=0 兜底 0，processed>total 上限 100
4. 终止条件扩展：``graph_build_status=RUNNING`` 时 SSE 不立即 done（即使
 ``index_status != INDEXING`` 且无 RUNNING IndexHistory）
5. 向后兼容：``repository`` + ``running_history`` 顶层字段保持完整不破坏 Phase
 既有 schema
测试模板沿用 ``test_index_progress_stream.py``：``AsyncClient`` + ``RefreshToken``
+ ``_parse_sse_events`` helper。tick / max_ticks 缩小到极小避免阻塞。
"""
from __future__ import annotations
import json
import uuid
import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from repositories.models import (
 GraphBuildHistory,
 GraphBuildHistoryStatus,
 GraphBuildHistoryTrigger,
 IndexHistory,
 IndexHistoryStatus,
 IndexStatus,
 Repository,
 RepositoryGraphStatus,
 TriggerType,
)
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fast_sse_settings(settings: object) -> None:
 """缩短 SSE tick 让测试不卡住——max_ticks=2 + 0 interval 保证流尽快关闭。"""
 setattr(settings, "INDEX_STREAM_TICK_INTERVAL", 0.0)
 setattr(settings, "INDEX_STREAM_MAX_TICKS", 2)
@pytest.fixture
def graph_user(db) -> User:
 return User.objects.create_user(
 username="graph_stream_user",
 email="graph_stream@example.com",
 password="testpass",
 )
async def _auth_headers(user: User) -> dict[str, str]:
 refresh = await sync_to_async(RefreshToken.for_user)(user)
 return {"authorization": f"Bearer {refresh.access_token}"}
def _parse_sse_events(raw: str) -> list[dict]:
 events: list[dict] =
 for block in raw.split("\n\n"):
 block = block.strip
 if block.startswith("data: "):
 events.append(json.loads(block[6:]))
 return events
async def _read_sse_body(resp) -> str:
 return b"".join([chunk async for chunk in resp.streaming_content]).decode
def _index_stream_url(repo_id: uuid.UUID | str) -> str:
 return f"/api/repositories/{repo_id}/index/stream/"
# ===========================================================================
# Section 1：graph 字段顶层存在
# ===========================================================================
class TestGraphFieldTopLevel:
 async def test_progress_frame_includes_graph_field_at_top_level(
 self, graph_user: User
 ) -> None:
 """idle 仓库的 progress 帧必须包含顶层 graph 字段且 status=idle。"""
 repo = await Repository.objects.acreate(
 name="graph-top-level",
 git_url="https://github.com/test/graph-top.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.IDLE,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress_frames = [e for e in events if e["type"] == "progress"]
 assert progress_frames, f"应至少推一帧 progress：{events}"
 first = progress_frames[0]
 assert first["type"] == "progress"
 assert "graph" in first, f"progress 帧缺顶层 graph 字段：{first.keys}"
 assert first["graph"]["status"] == RepositoryGraphStatus.IDLE
# ===========================================================================
# Section 2：graph payload 9 字段 schema
# ===========================================================================
class TestGraphPayloadSchema:
 async def test_graph_payload_has_nine_fields(self, graph_user: User) -> None:
 """running 仓库 + 配套 RUNNING GraphBuildHistory → graph payload 9 字段齐全。
 percent / edge_count_so_far / started_at 与字段值精确断言：
 - 10/100 → percent=10
 - 5+3+2+1 → edge_count_so_far=11
 - started_at 取 RUNNING history.started_at（非 None）
 """
 started = timezone.now
 repo = await Repository.objects.acreate(
 name="graph-9-fields",
 git_url="https://github.com/test/graph-9.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.RUNNING,
 graph_stage="building...",
 current_graph_file="x.py",
 graph_files_processed=10,
 graph_files_total=100,
 )
 await GraphBuildHistory.objects.acreate(
 repository=repo,
 trigger_type=GraphBuildHistoryTrigger.MANUAL,
 status=GraphBuildHistoryStatus.RUNNING,
 started_at=started,
 symbols_count=5,
 imports_count=3,
 calls_count=2,
 endpoints_count=1,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress_frames = [e for e in events if e["type"] == "progress"]
 assert progress_frames
 graph = progress_frames[0]["graph"]
 expected_keys = {
 "status",
 "stage",
 "files_processed",
 "files_total",
 "percent",
 "current_file",
 "started_at",
 "edge_count_so_far",
 "error_message",
 }
 assert set(graph.keys) == expected_keys, (
 f"graph keys 不匹配 9 字段：{set(graph.keys)}"
 )
 assert graph["status"] == RepositoryGraphStatus.RUNNING
 assert graph["stage"] == "building..."
 assert graph["files_processed"] == 10
 assert graph["files_total"] == 100
 assert graph["percent"] == 10
 assert graph["current_file"] == "x.py"
 assert graph["started_at"] is not None
 assert graph["edge_count_so_far"] == 11
 assert graph["error_message"] == ""
# ===========================================================================
# Section 3：percent 边界计算
# ===========================================================================
class TestPercentBoundary:
 async def test_percent_zero_when_files_total_zero(
 self, graph_user: User
 ) -> None:
 """``graph_files_total=0`` 时 percent 兜底 0，避免除零。"""
 repo = await Repository.objects.acreate(
 name="graph-pct-zero",
 git_url="https://github.com/test/pct-zero.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.IDLE,
 graph_files_processed=5,
 graph_files_total=0,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress = [e for e in events if e["type"] == "progress"]
 assert progress[0]["graph"]["percent"] == 0
 async def test_percent_clamped_at_100(self, graph_user: User) -> None:
 """``processed > total`` 时 percent clamp 100。"""
 repo = await Repository.objects.acreate(
 name="graph-pct-clamp",
 git_url="https://github.com/test/pct-clamp.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.COMPLETED,
 graph_files_processed=150,
 graph_files_total=100,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress = [e for e in events if e["type"] == "progress"]
 assert progress[0]["graph"]["percent"] == 100
# ===========================================================================
# Section 4：终止条件扩展（graph_build_status=RUNNING 时不立即 done）
# ===========================================================================
class TestTerminationCondition:
 async def test_stream_does_not_done_when_only_graph_running(
 self, graph_user: User
 ) -> None:
 """index_status=INDEXED + 无 RUNNING IndexHistory + graph_build_status=RUNNING
 → 不应在第一帧 progress 后立即 done；应继续推 progress 直至达到 max_ticks。
 既有终止逻辑（仅看 index_status + running history）会立即 done，
 本测试锁定扩展后的"任一活跃路径都阻止 done"语义。
 """
 repo = await Repository.objects.acreate(
 name="graph-only-running",
 git_url="https://github.com/test/graph-only.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.RUNNING,
 )
 await GraphBuildHistory.objects.acreate(
 repository=repo,
 trigger_type=GraphBuildHistoryTrigger.MANUAL,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 # max_ticks=2 → 至少 2 帧 progress；最后一帧应为 max_ticks done（非 idle done）
 assert types.count("progress") >= 2, (
 f"graph 仍在 RUNNING 时不应只推一帧便 done：{types}"
 )
 # 最后一帧 done 的 reason 应为 max_ticks 而非 idle
 done_frames = [e for e in events if e["type"] == "done"]
 assert done_frames, f"达到 max_ticks 后必须推 done 关闭：{events}"
 assert done_frames[-1].get("reason") == "max_ticks"
 async def test_stream_done_when_index_and_graph_both_idle(
 self, graph_user: User
 ) -> None:
 """index_status=INDEXED + 无 RUNNING IndexHistory + graph_build_status=IDLE
 → 第一帧 progress 后立即 done idle（保 Phase 既有行为）。
 """
 repo = await Repository.objects.acreate(
 name="graph-both-idle",
 git_url="https://github.com/test/both-idle.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.IDLE,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 assert types[0] == "progress"
 assert "done" in types
 done = [e for e in events if e["type"] == "done"]
 assert done[0].get("reason") == "idle"
 async def test_stream_does_not_done_when_graph_running_even_index_indexing(
 self, graph_user: User
 ) -> None:
 """index_status=INDEXING + RUNNING IndexHistory + graph_build_status=RUNNING
 → 既有逻辑会阻止 done；扩展后仍阻止（不退化）。
 """
 repo = await Repository.objects.acreate(
 name="graph-both-running",
 git_url="https://github.com/test/both-running.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXING,
 graph_build_status=RepositoryGraphStatus.RUNNING,
 )
 await IndexHistory.objects.acreate(
 repository=repo,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 await GraphBuildHistory.objects.acreate(
 repository=repo,
 trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 assert types.count("progress") >= 2
 done = [e for e in events if e["type"] == "done"]
 # 达到 max_ticks 才 done，不是 idle done
 assert done and done[-1].get("reason") == "max_ticks"
# ===========================================================================
# Section 5：向后兼容（老消费者忽略未知字段；既有 schema 完整）
# ===========================================================================
class TestBackwardCompat:
 async def test_legacy_payload_keys_preserved(
 self, graph_user: User
 ) -> None:
 """扩展后 progress 帧仍含 repository + running_history 顶层字段；
 repository 子对象字段集合 ⊇ Phase 既有 schema。
 """
 repo = await Repository.objects.acreate(
 name="graph-back-compat",
 git_url="https://github.com/test/compat.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXING,
 index_total_chunks=100,
 index_processed_chunks=42,
 index_write_total=100,
 index_write_processed=10,
 graph_build_status=RepositoryGraphStatus.RUNNING,
 )
 await IndexHistory.objects.acreate(
 repository=repo,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 client = AsyncClient
 resp = await client.get(
 _index_stream_url(repo.id),
 headers=await _auth_headers(graph_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress = [e for e in events if e["type"] == "progress"]
 first = progress[0]
 # 顶层既有字段不破坏
 assert "repository" in first
 assert "running_history" in first
 assert "graph" in first
 legacy_repo_keys = {
 "index_status",
 "last_indexed_at",
 "index_error",
 "index_total_chunks",
 "index_processed_chunks",
 "index_write_total",
 "index_write_processed",
 "overall_progress",
 "overall_stage",
 }
 actual_repo_keys = set(first["repository"].keys)
 assert legacy_repo_keys.issubset(actual_repo_keys), (
 f"repository payload 缺既有字段：{legacy_repo_keys - actual_repo_keys}"
 )
 # running_history 不应为空（既有逻辑）
 assert first["running_history"] is not None
