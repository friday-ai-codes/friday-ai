"""构建 Claude Code SDK resume 续跑的 dispatch env（分片下发，零 runner 改动）。

容器只能到达 runner 本地中转，无法直连 server 拉 transcript；而单个环境变量受
``MAX_ARG_STRLEN``(~128KB) 限制。故把 transcript 拆成多个 ``env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}``
经 dispatch metadata 下发（runner 已会把 ``env_`` 前缀键透传成容器环境变量），容器侧
:func:`core.sdk_sessions.write_transcript` 重组还原后 ``ClaudeAgentOptions(resume=...)`` 续跑。

超 :data:`MAX_RESUME_TRANSCRIPT_BYTES`（留余量给 prompt + 其它 env，防超 ARG_MAX ~2MB）则
不下发 resume env —— 容器无 resume 标记即全新执行，自动回退语义重建路径。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from chat.models import CodingSession

logger = structlog.get_logger(__name__)

# 单 transcript chunk 的最大字符数。UTF-8 下单字符最多 4 字节，25_000 字符 ≤ 100KB，
# 安全低于 MAX_ARG_STRLEN(~128KB)。
RESUME_CHUNK_CHARS = 25_000

# transcript 下发总字节上限。低于 ARG_MAX(~2MB) 大幅留余量给 coding prompt + 其它 env。
# 超限放弃 resume 下发（走语义重建回退），避免 exec() 因 E2BIG 失败。
MAX_RESUME_TRANSCRIPT_BYTES = 800_000


def build_resume_dispatch_env(coding_session: CodingSession) -> dict[str, str]:
    """据 CodingSession 已存的 SDK 会话数据构建 resume 下发 env（分片）。

    无 sdk_session_id / transcript，或 transcript 超字节上限 → 返回空 dict（默认安全，
    不改变现有 dispatch 行为，容器全新执行）。
    """
    sid = (coding_session.sdk_session_id or "").strip()
    transcript = coding_session.sdk_transcript or ""
    if not sid or not transcript:
        return {}

    byte_len = len(transcript.encode("utf-8"))
    if byte_len > MAX_RESUME_TRANSCRIPT_BYTES:
        logger.warning(
            "resume_transcript_too_large_skip",
            coding_session_id=str(coding_session.id),
            bytes=byte_len,
            cap=MAX_RESUME_TRANSCRIPT_BYTES,
        )
        return {}

    chunks = [
        transcript[i : i + RESUME_CHUNK_CHARS]
        for i in range(0, len(transcript), RESUME_CHUNK_CHARS)
    ]
    env: dict[str, str] = {
        "env_FRIDAY_TASK_RESUME_SESSION_ID": sid,
        "env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS": str(len(chunks)),
    }
    for i, chunk in enumerate(chunks):
        env[f"env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}"] = chunk

    logger.info(
        "resume_dispatch_env_built",
        coding_session_id=str(coding_session.id),
        sdk_session_id=sid,
        chunks=len(chunks),
        bytes=byte_len,
    )
    return env
