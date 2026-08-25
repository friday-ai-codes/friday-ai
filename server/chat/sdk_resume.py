"""构建 Claude Code SDK resume 续跑的 dispatch env（分片下发，零 runner 改动）。

容器只能到达 runner 本地中转，无法直连 server 拉 transcript；而单个环境变量受
``MAX_ARG_STRLEN``(~128KB) 限制。故把 transcript 拆成多个 ``env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}``
经 dispatch metadata 下发（runner 已会把 ``env_`` 前缀键透传成容器环境变量），容器侧
:func:`core.sdk_sessions.write_transcript` 重组还原后 ``ClaudeAgentOptions(resume=...)`` 续跑。

超 :data:`MAX_RESUME_TRANSCRIPT_BYTES`（留余量给 prompt + 其它 env，防超 ARG_MAX ~2MB）则
不下发 resume env —— 容器无 resume 标记即全新执行，自动回退语义重建路径。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from chat.session_store import WORKSPACE_CWD, SessionStore

if TYPE_CHECKING:
    from chat.models import CodingSession

logger = structlog.get_logger(__name__)

# 单 transcript chunk 的最大字符数。UTF-8 下单字符最多 4 字节，25_000 字符 ≤ 100KB，
# 安全低于 MAX_ARG_STRLEN(~128KB)。
RESUME_CHUNK_CHARS = 25_000

# transcript 下发总字节上限。低于 ARG_MAX(~2MB) 大幅留余量给 coding prompt + 其它 env。
# 超限放弃 resume 下发（走语义重建回退），避免 exec() 因 E2BIG 失败。
MAX_RESUME_TRANSCRIPT_BYTES = 800_000


def validate_sdk_transcript(transcript: str) -> tuple[bool, str]:
    """校验 SDK resume JSONL 的最低兼容契约。

    SDK 会拒绝只有加密 ``signature``、没有明文 ``thinking`` 的 thinking block。
    服务端应在派发前安全降级为新会话，避免反复注入已知不兼容的 transcript。
    """
    if not transcript.strip():
        return False, "empty"

    line_count = 0
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_count += 1
        try:
            message = json.loads(line)
        except (TypeError, ValueError):
            return False, "malformed_jsonl"
        if not isinstance(message, dict):
            return False, "message_not_object"

        payload = message.get("message")
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "thinking":
                continue
            if not str(block.get("thinking") or "").strip():
                return False, "thinking_text_missing"

    if line_count == 0:
        return False, "empty"
    return True, ""


def build_resume_dispatch_env(
    coding_session: CodingSession,
    *,
    dispatch_cwd: str = WORKSPACE_CWD,
) -> dict[str, str]:
    """据已镜像的 SDK 会话数据构建 resume 下发 env（分片）。

    经 :class:`chat.session_store.SessionStore` 取回 transcript（Redis 镜像 → DB
    fallback），支持跨容器 / 跨副本 / 冷启动 resume。命中后再经
    :meth:`SessionStore.assert_cwd_consistent` 校验容器 workspace cwd 与首跑一致——
    cwd 漂移会令 transcript 目录派生落空甚至错配他容器，**不一致即放弃 resume**。

    无 sdk_session_id / transcript、cwd 不一致，或 transcript 超字节上限 → 返回空 dict
    （默认安全，不改变现有 dispatch 行为，容器全新执行）。
    """
    store = SessionStore()
    data = store.load(coding_session=coding_session)
    if not data:
        return {}

    sid = (data.get("sdk_session_id") or "").strip()
    transcript = data.get("sdk_transcript") or ""
    if not sid or not transcript:
        return {}
    compatible, reason = validate_sdk_transcript(transcript)
    if not compatible:
        logger.warning(
            "resume_transcript_incompatible",
            category="sampling",
            component="sdk_resume",
            owner_id=str(getattr(coding_session, "id", "")),
            reason=reason,
        )
        return {}

    # cwd 一致校验：stored_cwd 空（DB fallback / 旧数据）→ 放行不回退；非空且漂移 → 放弃。
    stored_cwd = data.get("cwd") or ""
    if not store.assert_cwd_consistent(stored_cwd=stored_cwd, dispatch_cwd=dispatch_cwd):
        logger.warning(
            "resume_cwd_mismatch_skip",
            coding_session_id=str(getattr(coding_session, "id", "")),
            stored_cwd=stored_cwd,
            dispatch_cwd=dispatch_cwd,
        )
        return {}

    env = build_resume_env(sid, transcript, owner_id=str(coding_session.id))
    if env:
        logger.info(
            "resume_dispatch_env_built",
            coding_session_id=str(coding_session.id),
            sdk_session_id=sid,
            chunks=env.get("env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS"),
        )
    return env


def build_resume_env(sdk_session_id: str, transcript: str, *, owner_id: str = "") -> dict[str, str]:
    """把 ``(session_id, transcript)`` 折成分片 resume env（**纯函数，零模型依赖**）。

    Phase 120 从 :func:`build_resume_dispatch_env` 抽出：蓝图的逐仓调研 / 分仓方案容器同样
    要 resume，但它们的留痕在 ``SubAgentSession`` 上、没有 ``CodingSession`` 也没有
    ``SessionStore`` 镜像 ⇒ 需要一个不绑那两者的入口。⛔ **分片规则只能有这一份**：
    容器侧 ``core.sdk_sessions.write_transcript`` 按 ``_CHUNKS`` + ``_{i}`` 重组，两处漂移
    即还原出半份 transcript（比没有 resume 更糟——agent 会拿着截断的历史继续推理）。

    空 id / 空 transcript / 超 :data:`MAX_RESUME_TRANSCRIPT_BYTES` ⇒ 返回空 dict
    （默认安全：容器无 resume 标记即全新执行，自动回退语义重建）。
    """
    sid = str(sdk_session_id or "").strip()
    text = transcript or ""
    if not sid or not text:
        return {}

    byte_len = len(text.encode("utf-8"))
    if byte_len > MAX_RESUME_TRANSCRIPT_BYTES:
        logger.warning(
            "resume_transcript_too_large_skip",
            owner_id=owner_id,
            bytes=byte_len,
            cap=MAX_RESUME_TRANSCRIPT_BYTES,
        )
        return {}

    chunks = [text[i : i + RESUME_CHUNK_CHARS] for i in range(0, len(text), RESUME_CHUNK_CHARS)]
    env: dict[str, str] = {
        "env_FRIDAY_TASK_RESUME_SESSION_ID": sid,
        "env_FRIDAY_TASK_RESUME_TRANSCRIPT_CHUNKS": str(len(chunks)),
    }
    for i, chunk in enumerate(chunks):
        env[f"env_FRIDAY_TASK_RESUME_TRANSCRIPT_{i}"] = chunk
    return env
