"""Claude Code SDK 会话 transcript 读写辅助（resume 支撑）。

Claude Code 把每个 SDK 会话的对话 transcript 以 jsonl 落在
``~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl``（目录名为 cwd realpath
把所有非字母数字字符替换成 ``-``）。``ClaudeAgentOptions(resume=session_id)`` 续跑时
SDK 从该文件恢复对话历史。

容器是 ephemeral 的，transcript 随容器销毁。为支持「7 天内改方案/回溯续跑」：
- 编码结束时用 :func:`read_transcript` 读出 transcript，经 callback 上传 server 落库；
- resume 时用 :func:`write_transcript` 把 server 拉回的 transcript 还原到本地，
  再让 SDK ``resume`` 续跑。

优先复用 SDK 内部路径解析（``claude_agent_sdk._internal.sessions``），不可用时回退到
等价的本地实现（与 SDK ``_sanitize_path`` 逐字符一致）。
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]")
_MAX_SANITIZED_LENGTH = 200


def _claude_config_home() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(unicodedata.normalize("NFC", config_dir))
    return Path(unicodedata.normalize("NFC", str(Path.home() / ".claude")))


def _project_dir(cwd: str) -> Path:
    """计算 cwd 对应的 SDK project 目录（与 SDK _get_project_dir 等价）。"""
    try:
        canonical = unicodedata.normalize("NFC", os.path.realpath(cwd))
    except OSError:
        canonical = unicodedata.normalize("NFC", cwd)
    sanitized = _SANITIZE_RE.sub("-", canonical)
    # 容器 workspace 路径恒短（/app/workspace），不触发 hash 截断分支；
    # 仍保留长度保护与 SDK 一致，避免 realpath 异常超长时路径不一致。
    if len(sanitized) > _MAX_SANITIZED_LENGTH:
        sanitized = sanitized[:_MAX_SANITIZED_LENGTH]
    return _claude_config_home() / "projects" / sanitized


def _transcript_path(session_id: str, cwd: str) -> Path:
    return _project_dir(cwd) / f"{session_id}.jsonl"


def read_transcript(session_id: str, cwd: str) -> str:
    """读取 SDK 会话 transcript 原文（jsonl）；不存在或失败返回空串。

    优先用 SDK 内部 ``_read_session_file``（带 worktree 回退），回退到直接读文件。
    """
    if not session_id:
        return ""

    try:
        from claude_agent_sdk._internal.sessions import _read_session_file

        content = _read_session_file(session_id, cwd)
        if content:
            return content
    except Exception as exc:  # noqa: BLE001 — SDK 内部 API 变动时回退
        logger.debug("sdk_read_session_file_unavailable", error=str(exc))

    path = _transcript_path(session_id, cwd)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("transcript_not_found", session_id=session_id, path=str(path))
        return ""


def write_transcript(session_id: str, cwd: str, content: str) -> bool:
    """把 server 拉回的 transcript 还原到本地 SDK project 目录，供 resume 续跑。

    返回是否写入成功。空 session_id / content 视为无需还原（返回 False）。
    """
    if not session_id or not content:
        return False

    path = _transcript_path(session_id, cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info(
            "transcript_restored",
            session_id=session_id,
            path=str(path),
            size=len(content),
        )
        return True
    except OSError as exc:
        logger.warning(
            "transcript_restore_failed",
            session_id=session_id,
            path=str(path),
            error=str(exc),
        )
        return False
