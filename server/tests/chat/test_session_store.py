"""SessionStore 守护测试（Phase 86, HOOK-04）：

- mirror → load 命中 Redis 返回相同 sdk_session_id/transcript（跨容器镜像）
- Redis 不可用（mock 抛错）→ load 降级返回 DB，mirror 吞异常不抛（best-effort）
- assert_cwd_consistent：一致 True / 不一致 False / stored 空放行 True
- build_resume_dispatch_env：SessionStore 命中 + cwd 一致 → 非空 resume env；
  cwd 漂移 → {}（回退新 session）；未命中且 DB 空 → {}（默认安全，行为同现状）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.cache import cache

from chat.session_store import WORKSPACE_CWD, SessionStore


def _session(sid: str = "", transcript: str = "", *, cs_id: str = "cs-1") -> SimpleNamespace:
    return SimpleNamespace(id=cs_id, sdk_session_id=sid, sdk_transcript=transcript)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestSessionStoreMirrorLoad:
    @pytest.mark.asyncio
    async def test_mirror_then_load_hits_redis(self) -> None:
        store = SessionStore()
        cs = _session("sess-redis", "transcript-body", cs_id="cs-mirror")
        await store.mirror(coding_session=cs, cwd=WORKSPACE_CWD)

        # load 命中镜像：返回相同 sdk_session_id / transcript / cwd。
        loaded = store.load(coding_session=_session(cs_id="cs-mirror"))
        assert loaded is not None
        assert loaded["sdk_session_id"] == "sess-redis"
        assert loaded["sdk_transcript"] == "transcript-body"
        assert loaded["cwd"] == WORKSPACE_CWD

    @pytest.mark.asyncio
    async def test_mirror_noop_without_session_id(self) -> None:
        store = SessionStore()
        await store.mirror(coding_session=_session("", "x", cs_id="cs-empty"))
        # 无 session_id 不写镜像 → load 走 DB fallback（实例也空）→ None。
        assert store.load(coding_session=_session(cs_id="cs-empty")) is None

    def test_load_db_fallback_on_redis_miss(self) -> None:
        store = SessionStore()
        # Redis 未命中（cache 已清）→ 降级读 DB（实例已载字段）。
        loaded = store.load(coding_session=_session("db-sid", "db-transcript", cs_id="cs-db"))
        assert loaded == {
            "sdk_session_id": "db-sid",
            "sdk_transcript": "db-transcript",
            "cwd": "",
        }

    def test_load_none_when_both_empty(self) -> None:
        store = SessionStore()
        assert store.load(coding_session=_session("", "", cs_id="cs-none")) is None


class TestSessionStoreRedisDown:
    """Redis 故障：load 降级 DB、mirror 吞异常不抛（best-effort 绝不反噬）。"""

    def test_load_degrades_to_db_when_cache_get_raises(self) -> None:
        store = SessionStore()
        with patch.object(cache, "get", side_effect=RuntimeError("redis down")):
            loaded = store.load(
                coding_session=_session("db-sid", "db-transcript", cs_id="cs-down")
            )
        assert loaded is not None
        assert loaded["sdk_session_id"] == "db-sid"
        assert loaded["sdk_transcript"] == "db-transcript"

    @pytest.mark.asyncio
    async def test_mirror_swallows_cache_set_error(self) -> None:
        store = SessionStore()
        with patch.object(cache, "set", side_effect=RuntimeError("redis down")):
            # 不抛即满足 best-effort 语义。
            await store.mirror(coding_session=_session("sid", "t", cs_id="cs-down2"))


class TestAssertCwdConsistent:
    def test_consistent_same_cwd(self) -> None:
        store = SessionStore()
        assert store.assert_cwd_consistent(
            stored_cwd=WORKSPACE_CWD, dispatch_cwd=WORKSPACE_CWD
        )

    def test_inconsistent_different_cwd(self) -> None:
        store = SessionStore()
        assert not store.assert_cwd_consistent(
            stored_cwd="/app/workspace", dispatch_cwd="/tmp/other-container/xyz"
        )

    def test_empty_stored_cwd_allows_resume(self) -> None:
        # DB fallback / 旧数据无 cwd → 放行不回退（保持 v0.8 既有 DB resume 行为）。
        store = SessionStore()
        assert store.assert_cwd_consistent(stored_cwd="", dispatch_cwd=WORKSPACE_CWD)


class TestBuildResumeDispatchEnvWithStore:
    @pytest.mark.asyncio
    async def test_resume_env_built_when_mirror_hit_and_cwd_consistent(self) -> None:
        from chat.sdk_resume import build_resume_dispatch_env

        transcript = '{"type":"user"}\n{"type":"assistant"}\n'
        await SessionStore().mirror(
            coding_session=_session("sess-x", transcript, cs_id="cs-resume"),
            cwd=WORKSPACE_CWD,
        )
        env = build_resume_dispatch_env(
            _session(cs_id="cs-resume"), dispatch_cwd=WORKSPACE_CWD
        )
        assert env["env_FRIDAY_TASK_RESUME_SESSION_ID"] == "sess-x"
        count = int(env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"])
        reassembled = "".join(
            env[f"env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}"] for i in range(count)
        )
        assert reassembled == transcript

    @pytest.mark.asyncio
    async def test_cwd_mismatch_falls_back_to_fresh_session(self) -> None:
        from chat.sdk_resume import build_resume_dispatch_env

        await SessionStore().mirror(
            coding_session=_session("sess-y", "body", cs_id="cs-mismatch"),
            cwd="/app/workspace",
        )
        # dispatch_cwd 与镜像 cwd 不一致 → 放弃 transcript resume，返回 {}。
        env = build_resume_dispatch_env(
            _session(cs_id="cs-mismatch"), dispatch_cwd="/tmp/another/path"
        )
        assert env == {}

    def test_empty_when_no_session_anywhere(self) -> None:
        from chat.sdk_resume import build_resume_dispatch_env

        # Redis miss + DB 空 → {}（默认安全，行为同现状）。
        assert build_resume_dispatch_env(_session(cs_id="cs-blank")) == {}

    def test_db_fallback_resume_works_without_cwd(self) -> None:
        from chat.sdk_resume import build_resume_dispatch_env

        # 无 Redis 镜像，DB 有 transcript 且无 cwd → 仍可 resume（v0.8 行为不回退）。
        env = build_resume_dispatch_env(_session("db-sid", "db-body", cs_id="cs-dbonly"))
        assert env["env_FRIDAY_TASK_RESUME_SESSION_ID"] == "db-sid"
