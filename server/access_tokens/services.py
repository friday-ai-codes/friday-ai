"""任务级短 TTL token 铸造与吊销（Phase 103 AGENT-01）。

统一入口：三条派发链路（workflow / chat / MCP）派发编码任务时经 ``mint_task_token``
为发起用户铸造 kind="task" 的短 TTL token；任务终态（callbacks HTTP / consumers WS /
断连收敛）经 ``arevoke_task_tokens`` 按 session_id 幂等吊销。

PAT-02 语义澄清（底线不破）：mint 是**新签发**——明文由 ``generate_pat()`` 在内存中
生成、仅经返回值一次性交给调用方直接写容器 env，DB 只存 ``hash_token(明文)`` 的
sha256。这与「从 DB 反取明文」本质不同（后者被禁止且不可能——DB 无明文可取）。
明文绝不落盘、绝不进日志（结构化事件只含 session_id/user_id/过期秒数等非敏感字段）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from django.utils import timezone

from runners.models import hash_token

from .models import AccessToken, generate_pat

logger = structlog.get_logger(__name__)

# 过期余量：任务 timeout 之外额外保留 10 分钟（容器收尾/回调延迟缓冲，Claude's
# Discretion 采纳 CONTEXT 建议值）。
TASK_TOKEN_EXPIRY_MARGIN = timedelta(minutes=10)


async def mint_task_token(user: Any, session_id: str, timeout_seconds: int) -> str:
    """为发起用户铸造任务级短 TTL token，返回明文（仅在内存，调用方直进容器 env）。

    Args:
        user: 发起用户（accounts.User 实例，token 归属 created_by）。
        session_id: 关联的 subagent session_id（终态吊销按此定位）。
        timeout_seconds: 任务超时秒数；expires_at = now + timeout + 10 分钟余量。

    Returns:
        token 明文（friday_pat_ 前缀）。**唯一一次**暴露明文——绝不落盘、绝不进日志。
    """
    expires_in = timedelta(seconds=timeout_seconds) + TASK_TOKEN_EXPIRY_MARGIN
    plaintext = generate_pat()
    await AccessToken.objects.acreate(
        name=f"task:{session_id}",
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:12],
        token_suffix=plaintext[-4:],
        created_by=user,
        kind="task",
        session_id=session_id,
        expires_at=timezone.now() + expires_in,
    )
    # 结构化事件：绝不含明文 / hash / 前后缀之外的任何 token 材料（此处连指纹都不记）。
    logger.info(
        "task_token_minted",
        session_id=session_id,
        user_id=str(user.id),
        expires_in_seconds=int(expires_in.total_seconds()),
        category="caller",
        component="access_tokens",
    )
    return plaintext


async def arevoke_task_tokens(session_id: str) -> int:
    """按 session_id 吊销全部未吊销的任务 token（幂等 best-effort）。

    重复调用第二次 count=0（filter 排除已吊销行，revoked_at 保留首次时间戳）。
    整体 try/except 吞异常返回 0——吊销是终态回调路径上的附属动作，绝不反噬
    回调/WS 消息处理主流程（观测 best-effort 原则）。

    Returns:
        本次实际吊销的 token 行数。
    """
    try:
        count = await AccessToken.objects.filter(
            kind="task", session_id=session_id, revoked_at__isnull=True
        ).aupdate(revoked_at=timezone.now())
        if count:
            logger.info(
                "task_token_revoked",
                session_id=session_id,
                count=count,
                initiated_by_user_id="system",
                category="caller",
                component="access_tokens",
            )
        return count
    except Exception:  # noqa: BLE001 — best-effort，吊销失败由 expires_at 自过期兜底
        return 0
