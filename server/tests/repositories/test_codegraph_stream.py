"""Phase Plan / GRAPH-：独立 SSE 端点
``GET /api/repositories/<id>/codegraph/stream/`` + ``CodegraphCancelView``
同步写 ``Repository.graph_build_status=CANCELLED`` 的端到端测试。
覆盖：
1. 基本帧 schema：``frame["type"]=="progress"`` + 顶层 ``graph`` 字段（不含
 ``repository`` / ``running_history``，独立端点只关心 graph）
2. 9 字段 schema 与扩展端点完全一致（status / stage / files_processed /
 files_total / percent / current_file / started_at / edge_count_so_far /
 error_message）
3. 终止条件：``graph_build_status != RUNNING`` 即推 done idle（不依赖
 index_status）；``graph_build_status=RUNNING`` 连续推 progress 直至
 max_ticks
4. max_ticks 兜底：达到上限后推 done reason=max_ticks
5. 404 / 401 / SSE 响应头（Content-Type / Cache-Control / X-Accel-Buffering）
6. Cancel 同步写：``POST /codegraph/cancel/`` 调用后
 ``repo.graph_build_status=cancelled`` + 易失字段清零 +
 ``graph_last_built_at`` 非 None
7. URL 名锁定：``codegraph-progress-stream``（``reverse`` 解析路径与
 ``/codegraph/stream/`` 一致）
"""
from __future__ import annotations
import json
import uuid
import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from repositories.models import (
 GraphBuildHistory,
 GraphBuildHistoryStatus,
 GraphBuildHistoryTrigger,
 IndexStatus,
 Repository,
 RepositoryGraphStatus,
)
pytestmark = [pytest.mark.django_db(transaction=True)]
# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fast_sse_settings(settings: object) -> None:
 """缩短 SSE tick 让测试不卡住——max_ticks=2 + 0 interval。"""
 setattr(settings, "INDEX_STREAM_TICK_INTERVAL", 0.0)
 setattr(settings, "INDEX_STREAM_MAX_TICKS", 2)
@pytest.fixture
def cg_user(db) -> User:
 return User.objects.create_user(
 username="codegraph_stream_user",
 email="cg_stream@example.com",
 password="testpass",
 )
@pytest.fixture
def cg_repo(db) -> Repository:
 return Repository.objects.create(
 name="codegraph-stream-repo",
 git_url="https://github.com/test/cg-stream.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 graph_build_status=RepositoryGraphStatus.IDLE,
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
def _stream_url(repo_id: uuid.UUID | str) -> str:
 return f"/api/repositories/{repo_id}/codegraph/stream/"
def _cancel_url(repo_id: uuid.UUID | str) -> str:
 return f"/api/repositories/{repo_id}/codegraph/cancel/"
# ===========================================================================
# Section 1：基本帧 schema
# ===========================================================================
class TestBasicFrameSchema:
 @pytest.mark.asyncio
 async def test_codegraph_stream_first_frame_only_has_graph_field(
 self, cg_user: User, cg_repo: Repository
 ) -> None:
 """idle 仓库 → progress 帧顶层只含 type/ts/graph，不含 repository/running_history。"""
 client = AsyncClient
 resp = await client.get(
 _stream_url(cg_repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200, resp.content
 events = _parse_sse_events(await _read_sse_body(resp))
 progress = [e for e in events if e["type"] == "progress"]
 assert progress, f"应至少一帧 progress：{events}"
 first = progress[0]
 assert first["type"] == "progress"
 assert "graph" in first
 assert "repository" not in first, (
 f"独立端点不应含 repository 顶层字段：{first.keys}"
 )
 assert "running_history" not in first, (
 f"独立端点不应含 running_history 顶层字段：{first.keys}"
 )
 assert first["graph"]["status"] == RepositoryGraphStatus.IDLE
# ===========================================================================
# Section 2：9 字段 schema 一致
# ===========================================================================
class TestSchemaParity:
 @pytest.mark.asyncio
 async def test_codegraph_stream_graph_schema_matches_extended_endpoint(
 self, cg_user: User
 ) -> None:
 """同 fixture 下，独立端点 graph payload 字段集合应与扩展端点完全一致。"""
 started = timezone.now
 repo = await Repository.objects.acreate(
 name="cg-parity-repo",
 git_url="https://github.com/test/parity.git",
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
 _stream_url(repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 progress = [e for e in events if e["type"] == "progress"]
 assert progress
 graph = progress[0]["graph"]
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
 assert set(graph.keys) == expected_keys
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
# Section 3：终止条件（独立端点不依赖 index_status）
# ===========================================================================
class TestTerminationCondition:
 @pytest.mark.asyncio
 async def test_codegraph_stream_done_when_graph_not_running(
 self, cg_user: User, cg_repo: Repository
 ) -> None:
 """graph_build_status=idle → 第一帧 progress 后第二帧 done idle。"""
 client = AsyncClient
 resp = await client.get(
 _stream_url(cg_repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 assert types[0] == "progress"
 assert "done" in types
 done = [e for e in events if e["type"] == "done"]
 assert done[0].get("reason") == "idle"
 @pytest.mark.asyncio
 async def test_codegraph_stream_does_not_done_when_graph_running(
 self, cg_user: User
 ) -> None:
 """graph_build_status=RUNNING → 连续推 progress，直到 max_ticks。"""
 repo = await Repository.objects.acreate(
 name="cg-running",
 git_url="https://github.com/test/cg-running.git",
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
 _stream_url(repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 assert types.count("progress") >= 2, types
 done = [e for e in events if e["type"] == "done"]
 assert done and done[-1].get("reason") == "max_ticks"
# ===========================================================================
# Section 4：max_ticks 兜底（与上一类合并验证，单独再加一条精确帧数断言）
# ===========================================================================
class TestMaxTicksFallback:
 @pytest.mark.asyncio
 async def test_codegraph_stream_done_max_ticks(self, cg_user: User) -> None:
 """max_ticks=2 + graph 持续 RUNNING → 2 progress + 1 done(max_ticks)。"""
 repo = await Repository.objects.acreate(
 name="cg-max-ticks",
 git_url="https://github.com/test/max-ticks.git",
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
 with override_settings(
 INDEX_STREAM_MAX_TICKS=2, INDEX_STREAM_TICK_INTERVAL=0.0
 ):
 client = AsyncClient
 resp = await client.get(
 _stream_url(repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200
 events = _parse_sse_events(await _read_sse_body(resp))
 types = [e["type"] for e in events]
 assert types.count("progress") == 2, types
 assert types[-1] == "done"
 done = [e for e in events if e["type"] == "done"]
 assert done[0].get("reason") == "max_ticks"
# ===========================================================================
# Section 5：404 / 401 / 响应头
# ===========================================================================
class TestErrorAndHeaders:
 @pytest.mark.asyncio
 async def test_codegraph_stream_404_on_missing_repository(
 self, cg_user: User
 ) -> None:
 """随机 UUID → 404 + body 含 detail。"""
 missing = uuid.uuid4
 client = AsyncClient
 resp = await client.get(
 _stream_url(missing),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 404
 body = json.loads(resp.content)
 assert "detail" in body
 @pytest.mark.asyncio
 async def test_codegraph_stream_401_unauthenticated(
 self, cg_repo: Repository
 ) -> None:
 """未登录 → 401（或 403，IsAuthenticated 强制）。"""
 client = AsyncClient
 resp = await client.get(_stream_url(cg_repo.id))
 assert resp.status_code in (401, 403)
 @pytest.mark.asyncio
 async def test_codegraph_stream_response_headers(
 self, cg_user: User, cg_repo: Repository
 ) -> None:
 """SSE 必备响应头：Content-Type / Cache-Control / X-Accel-Buffering。"""
 client = AsyncClient
 resp = await client.get(
 _stream_url(cg_repo.id),
 headers=await _auth_headers(cg_user),
 )
 assert resp.status_code == 200
 assert resp["Content-Type"].startswith("text/event-stream")
 assert resp["Cache-Control"] == "no-cache"
 assert resp["X-Accel-Buffering"] == "no"
 # 排干流避免 background task 残留
 await _read_sse_body(resp)
# ===========================================================================
# Section 6：URL 名锁定（reverse 解析）
# ===========================================================================
class TestUrlReverse:
 def test_codegraph_stream_url_reverse(self) -> None:
 """``codegraph-progress-stream`` URL 名能 reverse 解析为 .../codegraph/stream/。"""
 url = reverse(
 "codegraph-progress-stream",
 kwargs={"repository_id": uuid.UUID("00000000-0000-0000-0000-000000000000")},
 )
 assert url.endswith("/codegraph/stream/"), url
# ===========================================================================
# Section 7：Cancel 同步写 Repository.graph_build_status=CANCELLED
# ===========================================================================
class TestCancelSync:
 def test_cancel_view_updates_repository_graph_build_status(
 self, authenticated_client: APIClient, cg_repo: Repository
 ) -> None:
 """POST /codegraph/cancel/ 应同步把 Repository.graph_build_status=cancelled
 并清零 graph_stage / current_graph_file / graph_files_processed +
 写 graph_last_built_at=now（Phase Plan CONTEXT Grey Area 1
 取消出口决议）。
 """
 cg_repo.graph_build_status = RepositoryGraphStatus.RUNNING
 cg_repo.graph_stage = "building..."
 cg_repo.current_graph_file = "foo.py"
 cg_repo.graph_files_processed = 42
 cg_repo.graph_files_total = 100
 cg_repo.save(
 update_fields=[
 "graph_build_status",
 "graph_stage",
 "current_graph_file",
 "graph_files_processed",
 "graph_files_total",
 ]
 )
 GraphBuildHistory.objects.create(
 repository=cg_repo,
 trigger_type=GraphBuildHistoryTrigger.MANUAL,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 response = authenticated_client.post(_cancel_url(cg_repo.id))
 assert response.status_code == 204, getattr(response, "data", response)
 cg_repo.refresh_from_db
 assert cg_repo.graph_build_status == RepositoryGraphStatus.CANCELLED
 assert cg_repo.graph_stage == ""
 assert cg_repo.current_graph_file == ""
 assert cg_repo.graph_files_processed == 0
 assert cg_repo.graph_last_built_at is not None
