"""SDK resume 下发 env 构建 + 容器侧重组 round-trip 测试。"""

from __future__ import annotations

from types import SimpleNamespace

from chat.sdk_resume import (
    MAX_RESUME_TRANSCRIPT_BYTES,
    RESUME_CHUNK_CHARS,
    build_resume_dispatch_env,
)


def _reassemble(env: dict[str, str]) -> str:
    """镜像 task/core/runner.py::_load_resume_transcript 的重组逻辑。"""
    single = env.get("env_FRIDAY_TASK_RESUME_TRANSCRIPT", "")
    if single:
        return single
    count = int(env.get("env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS", "0"))
    return "".join(env.get(f"env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}", "") for i in range(count))


def _session(sid: str, transcript: str) -> SimpleNamespace:
    return SimpleNamespace(id="cs-1", sdk_session_id=sid, sdk_transcript=transcript)


def test_empty_when_no_session_id():
    assert build_resume_dispatch_env(_session("", "x")) == {}


def test_empty_when_no_transcript():
    assert build_resume_dispatch_env(_session("sess-1", "")) == {}


def test_roundtrip_small_transcript():
    transcript = '{"type":"user","content":"hello"}\n{"type":"assistant"}\n'
    env = build_resume_dispatch_env(_session("sess-1", transcript))
    assert env["env_FRIDAY_TASK_RESUME_SESSION_ID"] == "sess-1"
    assert _reassemble(env) == transcript


def test_roundtrip_multichunk_transcript():
    # 跨多个 chunk（含多字节中文，验证按字符切不破坏 UTF-8）
    transcript = ("行内容测试-" * 10_000)
    assert len(transcript) > RESUME_CHUNK_CHARS
    env = build_resume_dispatch_env(_session("sess-1", transcript))
    chunk_count = int(env["env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"])
    assert chunk_count > 1
    # 每个 chunk 的 UTF-8 字节数安全低于 MAX_ARG_STRLEN(~128KB)
    for i in range(chunk_count):
        assert len(env[f"env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}"].encode("utf-8")) < 128_000
    assert _reassemble(env) == transcript


def test_oversize_transcript_skipped():
    # 超字节上限 → 不下发 resume env（回退语义重建）
    big = "x" * (MAX_RESUME_TRANSCRIPT_BYTES + 1)
    assert build_resume_dispatch_env(_session("sess-1", big)) == {}
