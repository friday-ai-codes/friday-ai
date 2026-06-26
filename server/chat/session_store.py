"""SessionStore —— SDK session 跨容器持久化（HOOK-04，Phase 86）。

容器是 ephemeral 的，Claude Code SDK 把 transcript 以 jsonl 落在容器本地
``~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl``——**本地态跨容器/跨副本不共享**。
为支持「冷启动 / 跨容器 / 跨副本 resume」，把 ``CodingSession.sdk_session_id`` +
``sdk_transcript``（+ cwd、saved_at）镜像一份到 Redis（Django ``CACHES`` 框架，
``KEY_PREFIX=friday`` + ``IGNORE_EXCEPTIONS``）。

约束（与 86-02-PLAN / observability 规范一致）：
- **DB 恒为真相源**：Redis 仅作跨副本加速镜像。``load`` 优先读 Redis，未命中 / Redis
  故障降级回 DB（``CodingSession`` 实例已载字段，无额外查询）；两者皆空 → ``None``
  （调用方走「用应用态重灌新 session」兜底）。
- **cwd 一致校验**：SDK transcript 目录按 **cwd realpath** 派生（见
  ``task/core/sdk_sessions``），cwd 漂移会令 resume 落空甚至错配他容器 transcript。
  resume 前必须经 :meth:`SessionStore.assert_cwd_consistent` 校验 dispatch 容器
  workspace cwd 与首跑一致，不一致放弃 transcript resume、回退新 session（绝不静默错配）。
- **best-effort 绝不反噬**：任何 Redis / 序列化异常都吞掉 + structlog warning
  （category=sampling, component=chat），绝不反噬派发 / 回调主流程。
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from django.conf import settings
from django.core.cache import cache

logger = structlog.get_logger(__name__)

__all__ = ["WORKSPACE_CWD", "SessionStore"]

_COMPONENT = "chat"

# 容器编码 workspace 约定 cwd：dispatch 固定下发（``env_FRIDAY_TASK_WORKSPACE_CWD``）
# 供 resume 时校验 cwd 一致。SDK transcript 目录按 cwd realpath 派生，cwd 一致才可
# 跨容器命中同一 transcript（见 task/core/sdk_sessions._project_dir）。
WORKSPACE_CWD = "/app/workspace"

# 镜像缓存键（最终 redis key 形如 ``friday:1:sdk_session:<id>``，KEY_PREFIX 由 CACHES 配）。
_KEY_TEMPLATE = "sdk_session:{coding_session_id}"

# 镜像 TTL（秒）：与「7 天内改方案 / 回溯续跑」窗口一致，作漏失效兜底过期。
_DEFAULT_TTL = 7 * 24 * 3600


def _cache_key(coding_session_id: Any) -> str:
    return _KEY_TEMPLATE.format(coding_session_id=str(coding_session_id))


def _normalize_cwd(cwd: str) -> str:
    """归一 cwd 以判定 transcript 目录是否同源（按 realpath 派生的语义对齐）。"""
    if not cwd:
        return ""
    try:
        return os.path.normpath(cwd.strip())
    except (ValueError, TypeError):
        return cwd.strip()


class SessionStore:
    """SDK session Redis 镜像读写 + DB fallback + cwd 一致校验（best-effort 降级）。"""

    def __init__(self, *, ttl: int | None = None) -> None:
        self.ttl = (
            ttl
            if ttl is not None
            else getattr(settings, "SDK_SESSION_MIRROR_TTL", _DEFAULT_TTL)
        )

    async def mirror(self, *, coding_session: Any, cwd: str = WORKSPACE_CWD) -> None:
        """把 ``sdk_session_id`` + ``sdk_transcript``(+cwd, saved_at) 镜像到 Redis。

        Redis 不可用 / 序列化异常 → 吞掉（best-effort，DB 仍是真相源）。无 session_id
        视为无需镜像（与 ``_persist_sdk_session`` 落库前提一致）。
        """
        from django.utils import timezone

        sid = (getattr(coding_session, "sdk_session_id", "") or "").strip()
        if not sid:
            return
        transcript = getattr(coding_session, "sdk_transcript", "") or ""
        payload = {
            "sdk_session_id": sid,
            "sdk_transcript": transcript,
            "cwd": cwd or "",
            "saved_at": timezone.now().isoformat(),
        }
        try:
            cache.set(
                _cache_key(coding_session.id),
                json.dumps(payload, ensure_ascii=False),
                timeout=self.ttl,
            )
            logger.info(
                "sdk_session_mirrored",
                coding_session_id=str(coding_session.id),
                has_transcript=bool(transcript),
                component=_COMPONENT,
                category="sampling",
            )
        except Exception as exc:  # noqa: BLE001 — 镜像 best-effort，绝不反噬回调主流程
            logger.warning(
                "sdk_session_mirror_failed",
                coding_session_id=str(getattr(coding_session, "id", "")),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    def load(self, *, coding_session: Any) -> dict[str, str] | None:
        """取回 session 镜像：优先 Redis，未命中 / Redis 故障降级回 DB。

        返回 ``{sdk_session_id, sdk_transcript, cwd}``；Redis 与 DB 皆无可用数据 →
        ``None``（调用方走「应用态重灌新 session」兜底）。DB fallback 读实例已载字段，
        无额外查询；DB 无 cwd 信息 → ``cwd`` 置空（cwd 校验按「无信息不阻断」放行）。
        """
        # 1. Redis read-through（故障静默降级直读 DB）。
        raw: Any = None
        try:
            raw = cache.get(_cache_key(getattr(coding_session, "id", "")))
        except Exception as exc:  # noqa: BLE001 — redis 故障降级 DB，绝不反噬主流程
            logger.debug(
                "sdk_session_load_cache_degraded",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("sdk_session_id"):
                    return {
                        "sdk_session_id": str(data.get("sdk_session_id", "")),
                        "sdk_transcript": str(data.get("sdk_transcript", "") or ""),
                        "cwd": str(data.get("cwd", "") or ""),
                    }
            except (ValueError, TypeError):
                pass  # 反序列化坏值 → 走 DB 兜底

        # 2. DB fallback（CodingSession 真相源，实例已载字段）。
        sid = (getattr(coding_session, "sdk_session_id", "") or "").strip()
        transcript = getattr(coding_session, "sdk_transcript", "") or ""
        if sid and transcript:
            return {"sdk_session_id": sid, "sdk_transcript": transcript, "cwd": ""}
        return None

    def assert_cwd_consistent(self, *, stored_cwd: str, dispatch_cwd: str) -> bool:
        """校验 resume cwd 与首跑一致；不一致 → ``False``（放弃 transcript resume）。

        ``stored_cwd`` 为空（DB fallback / 旧数据无 cwd 信息）→ 无从判定漂移，按一致
        放行，保持 v0.8 既有 DB resume 行为不回退；非空时按归一后的目录语义比较。
        """
        if not stored_cwd:
            return True
        return _normalize_cwd(stored_cwd) == _normalize_cwd(dispatch_cwd)
