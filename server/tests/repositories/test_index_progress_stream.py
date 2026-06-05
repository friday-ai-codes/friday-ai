"""GET /api/repositories/{id}/index/stream/ — 索引进度 SSE 测试。

端点契约：
- 鉴权失败 / 仓库不存在 → 标准 4xx
- 第 1 帧立即推送 progress（不等 tick），帧体形如：
    {"type": "progress",
     "repository": { index_status, overall_progress, overall_stage, ... },
     "running_history": null | { id, status, from_sha, to_sha,
                                  files_added, files_modified, files_deleted,
                                  changed_files, summary_text, ... }}
- 终止条件：仓库不在 INDEXING 且没有 RUNNING IndexHistory → 推 {"type": "done"} 关闭
- 客户端断开 / 达到 max_ticks → 推 done 关闭
- Content-Type 为 text/event-stream

测试通过 settings 把 tick 间隔 / 最大 tick 数缩到极小避免阻塞。
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from repositories.models import (
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _fast_sse_settings(settings: object) -> None:
    """缩短 SSE tick 让测试不卡住。"""
    setattr(settings, "INDEX_STREAM_TICK_INTERVAL", 0.0)
    setattr(settings, "INDEX_STREAM_MAX_TICKS", 2)


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(
        username="stream_user",
        email="stream@example.com",
        password="testpass",
    )


async def _auth_headers(user: User) -> dict[str, str]:
    refresh = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {refresh.access_token}"}


def _parse_sse_events(raw: str) -> list[dict]:
    events: list[dict] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            events.append(json.loads(block[6:]))
    return events


async def _read_sse_body(resp) -> str:
    return b"".join([chunk async for chunk in resp.streaming_content]).decode()


class TestIndexProgressStreamView:
    async def test_404_for_unknown_repository(self, user: User) -> None:
        client = AsyncClient()
        resp = await client.get(
            "/api/repositories/00000000-0000-0000-0000-000000000000/index/stream/",
            headers=await _auth_headers(user),
        )
        assert resp.status_code == 404

    async def test_accept_text_event_stream_does_not_406(self, user: User) -> None:
        """回归 #406：浏览器 fetch SSE 时 Accept: text/event-stream 走 DRF
        默认 content negotiation 会失败，View 必须显式声明 SSE renderer。

        如果回退到 APIView 默认 renderer，这条用例会拿到 406 而不是 200。
        """
        repo = await Repository.objects.acreate(
            name="accept-header-repo",
            git_url="https://github.com/test/accept.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )

        client = AsyncClient()
        headers = await _auth_headers(user)
        headers["accept"] = "text/event-stream"
        resp = await client.get(
            f"/api/repositories/{repo.id}/index/stream/",
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"SSE 端点不应因 Accept 协商返回 406，当前 status={resp.status_code}"
        )
        assert resp["Content-Type"].startswith("text/event-stream")

    async def test_idle_repo_emits_progress_then_done(self, user: User) -> None:
        """非 INDEXING + 无 RUNNING history → 推一帧 progress 后立即 done。"""
        repo = await Repository.objects.acreate(
            name="idle-repo",
            git_url="https://github.com/test/idle.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/repositories/{repo.id}/index/stream/",
            headers=await _auth_headers(user),
        )
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/event-stream")

        events = _parse_sse_events(await _read_sse_body(resp))
        types = [e["type"] for e in events]
        assert types[0] == "progress"
        assert "done" in types

        first = events[0]
        assert first["repository"]["index_status"] == IndexStatus.INDEXED
        assert "overall_progress" in first["repository"]
        assert "overall_stage" in first["repository"]
        assert first["running_history"] is None

    async def test_indexing_repo_emits_running_history_payload(
        self, user: User
    ) -> None:
        """INDEXING + RUNNING history → progress 帧带完整 running_history（含 changed_files）。"""
        repo = await Repository.objects.acreate(
            name="indexing-repo",
            git_url="https://github.com/test/indexing.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXING,
            index_total_chunks=100,
            index_processed_chunks=42,
            index_write_total=100,
            index_write_processed=10,
        )
        history = await IndexHistory.objects.acreate(
            repository=repo,
            trigger_type=TriggerType.WEBHOOK,
            status=IndexHistoryStatus.RUNNING,
            from_sha="abc1234",
            to_sha="def5678",
            files_added=3,
            files_modified=2,
            files_deleted=1,
            changed_files={
                "added": ["a.py", "b.py", "c.py"],
                "modified": ["m1.py", "m2.py"],
                "deleted": ["d1.py"],
            },
            summary_text="本次增量：新增 3 文件、修改 2 文件、删除 1 文件",
            started_at=timezone.now(),
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/repositories/{repo.id}/index/stream/",
            headers=await _auth_headers(user),
        )
        assert resp.status_code == 200

        events = _parse_sse_events(await _read_sse_body(resp))
        progress = [e for e in events if e["type"] == "progress"]
        assert progress, f"应有 progress 事件: {events}"

        rh_frame = next((e for e in progress if e.get("running_history")), None)
        assert rh_frame, f"progress 帧缺少 running_history: {events}"
        rh = rh_frame["running_history"]
        assert rh["id"] == str(history.id)
        assert rh["status"] == "running"
        assert rh["from_sha"] == "abc1234"
        assert rh["to_sha"] == "def5678"
        assert rh["files_added"] == 3
        assert rh["files_modified"] == 2
        assert rh["files_deleted"] == 1
        assert rh["changed_files"] == {
            "added": ["a.py", "b.py", "c.py"],
            "modified": ["m1.py", "m2.py"],
            "deleted": ["d1.py"],
        }
        assert rh["trigger_type"] == "webhook"
        assert rh["summary_text"]

        repo_payload = rh_frame["repository"]
        assert repo_payload["index_status"] == IndexStatus.INDEXING
        assert 0 <= repo_payload["overall_progress"] <= 100
        assert repo_payload["overall_stage"]
        assert repo_payload["index_total_chunks"] == 100
        assert repo_payload["index_processed_chunks"] == 42

    async def test_progress_uses_explicit_index_stage_when_set(
        self, user: User
    ) -> None:
        """Repository.index_stage 非空时 → SSE overall_stage 应直接取该值，
        而不是按 chunks/write 计数器推断。
        """
        repo = await Repository.objects.acreate(
            name="staged-repo",
            git_url="https://github.com/test/staged.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXING,
            index_total_chunks=0,  # 旧规则下会显示"解析文件中..."
            index_processed_chunks=0,
            index_write_total=0,
            index_write_processed=0,
            index_stage="克隆仓库中...",
        )
        await IndexHistory.objects.acreate(
            repository=repo,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/repositories/{repo.id}/index/stream/",
            headers=await _auth_headers(user),
        )
        assert resp.status_code == 200

        events = _parse_sse_events(await _read_sse_body(resp))
        progress = [e for e in events if e["type"] == "progress"]
        assert progress
        assert progress[0]["repository"]["overall_stage"] == "克隆仓库中..."

    async def test_max_ticks_emits_done_to_close_loop(self, user: User) -> None:
        """RUNNING 状态长期不结束 → 端点达到 max_ticks 推 done 自我关闭。"""
        repo = await Repository.objects.acreate(
            name="long-running-repo",
            git_url="https://github.com/test/long.git",
            git_platform="github",
            default_branch="main",
            index_status=IndexStatus.INDEXING,
        )
        await IndexHistory.objects.acreate(
            repository=repo,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/repositories/{repo.id}/index/stream/",
            headers=await _auth_headers(user),
        )
        assert resp.status_code == 200

        events = _parse_sse_events(await _read_sse_body(resp))
        types = [e["type"] for e in events]
        # max_ticks=2 + done frame
        assert types.count("progress") <= 3
        assert types[-1] == "done"
