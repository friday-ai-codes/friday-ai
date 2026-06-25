"""调用下钻 API（LOG-04）：MCP 调用归因 + AI 对话会话原始。

复用现有 **Interaction Ledger**（``InteractionRun`` / ``ToolCallRecord`` /
``RetrievalTrace`` / ``ModelUsageRecord`` / ``InteractionEvent``）与
``Conversation`` / ``Message``，**不新建表、不复制数据**——三者经
``request_id`` / ``run_id`` / ``conversation_id`` 关联：

- ``CallDrilldownView``：按 ``request_id`` 或 ``run_id`` 定位 ``InteractionRun``，
  返回触发用户（按 ``token_fingerprint`` 解析所属用户，只回 id/用户名，绝不回 token）
  + 该 run 的工具调用 / 召回 / 模型用量 / 事件明细（全部为写入时已脱敏的 append-only 行）。
- ``ConversationDrilldownView``：按 ``conversation_id`` 取 ``Conversation`` 全部
  ``Message`` 与 ``created_by`` 归因，并按 ``correlation.conversation_id`` 关联出相关
  ``SystemLogEntry`` / ``InteractionRun``（只回关联键 + 摘要，不复制正文）。

全部端点 ``IsSuperUser`` fail-closed（T-71-05-03）；async ORM 经 ``sync_to_async``
桥接。下钻数据源均为写入时已 ``redact_for_ledger`` 的行，此处只读直出，绝不重拼明文
（T-71-05-02）。
"""

from __future__ import annotations

from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser

logger = structlog.get_logger(__name__)

# 单 run 明细返回上限（防超大 run 拖慢首屏）。
_MAX_DETAIL_ROWS = 500
# 单会话相关留痕返回上限（只回摘要，不复制正文）。
_MAX_RELATED_ROWS = 100


def _resolve_trigger_user(token_fingerprint: str) -> dict[str, Any]:
    """按 ``token_fingerprint`` 解析触发用户（绝不回 token，只回 id/用户名）。

    - ``user:<id>`` 形式（JWT / 退化路径，见 interactions.entry）：直接取该用户。
    - 否则按 ``AccessToken.token_hash`` 反查令牌所有者（PAT 路径）。
    - 解析不到：仅回 fingerprint（hash，非敏感），user 置空。
    """
    fp = (token_fingerprint or "").strip()
    if not fp:
        return {"id": None, "username": "", "fingerprint": ""}

    if fp.startswith("user:"):
        raw_id = fp.split(":", 1)[1]
        from accounts.models import User

        # User 主键可能是 UUID 或整数，不预判格式；非法 id（如解析失败）回退空用户。
        try:
            user = User.objects.filter(id=raw_id).first() if raw_id else None
        except Exception:  # noqa: BLE001 — 非法 id 解析失败按"解析不到"处理
            user = None
        if user is not None:
            return {"id": str(user.id), "username": user.username, "fingerprint": fp}
        return {"id": None, "username": "", "fingerprint": fp}

    # PAT 路径：按 token_hash 反查所有者（只回 owner id/用户名，绝不回 token）。
    from access_tokens.models import AccessToken

    token = (
        AccessToken.objects.select_related("created_by").filter(token_hash=fp).first()
    )
    if token is not None and token.created_by is not None:
        return {
            "id": str(token.created_by.id),
            "username": token.created_by.username,
            "fingerprint": fp,
        }
    return {"id": None, "username": "", "fingerprint": fp}


class CallDrilldownView(APIView):
    """GET /api/system/calls/drilldown/?request_id=... | run_id=... — MCP 调用下钻。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        request_id = (request.query_params.get("request_id") or "").strip()
        run_id = (request.query_params.get("run_id") or "").strip()
        if not request_id and not run_id:
            return Response(
                {"detail": "需提供 request_id 或 run_id"}, status=400
            )

        data = await sync_to_async(self._build, thread_sensitive=True)(
            request_id, run_id
        )
        if data is None:
            return Response({"detail": "未找到对应调用"}, status=404)

        logger.info(
            "call_drilldown_viewed",
            category="caller",
            component="call_drilldown",
            source="rest",
            run_id=str(data["run"].get("run_id") or ""),
        )
        return Response(data)

    @staticmethod
    def _build(request_id: str, run_id: str) -> dict[str, Any] | None:
        from interactions.models import InteractionRun

        run: InteractionRun | None = None
        if run_id:
            run = InteractionRun.objects.filter(run_id=run_id).first()
            if run is None:
                run = InteractionRun.objects.filter(id=run_id).first()
        else:
            run = (
                InteractionRun.objects.filter(request_id=request_id)
                .order_by("-created_at")
                .first()
            )
        if run is None:
            return None

        user = _resolve_trigger_user(run.token_fingerprint)

        tool_calls = [
            {
                "id": str(tc.id),
                "tool_name": tc.tool_name,
                "status": tc.status,
                "duration_ms": tc.duration_ms,
                "input": tc.input,
                "output": tc.output,
                "error": tc.error,
                "retry_index": tc.retry_index,
                "created_at": tc.created_at.isoformat(),
            }
            for tc in run.tool_calls.all().order_by("created_at")[:_MAX_DETAIL_ROWS]
        ]
        retrieval = [
            {
                "id": str(rt.id),
                "seq": rt.seq,
                "kind": rt.kind,
                "payload": rt.payload,
                "created_at": rt.created_at.isoformat(),
            }
            for rt in run.retrieval_traces.all().order_by("seq")[:_MAX_DETAIL_ROWS]
        ]
        model_usages = [
            {
                "id": str(mu.id),
                "provider": mu.provider,
                "model": mu.model,
                "prompt_tokens": mu.prompt_tokens,
                "completion_tokens": mu.completion_tokens,
                "total_tokens": mu.total_tokens,
                "duration_ms": mu.duration_ms,
                "failure_type": mu.failure_type,
                "created_at": mu.created_at.isoformat(),
            }
            for mu in run.model_usages.all().order_by("created_at")[:_MAX_DETAIL_ROWS]
        ]
        events = [
            {
                "id": str(ev.id),
                "seq": ev.seq,
                "event_type": ev.event_type,
                "payload": ev.payload,
                "created_at": ev.created_at.isoformat(),
            }
            for ev in run.events.all().order_by("seq")[:_MAX_DETAIL_ROWS]
        ]

        return {
            "run": {
                "run_id": str(run.run_id),
                "source": run.source,
                "request_id": run.request_id,
                "status": run.status,
                "token_fingerprint": run.token_fingerprint,
                "created_at": run.created_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            },
            "user": user,
            "tool_calls": tool_calls,
            "retrieval": retrieval,
            "model_usages": model_usages,
            "events": events,
        }


class ConversationDrilldownView(APIView):
    """GET /api/system/conversations/<uuid>/drilldown/ — AI 对话会话原始下钻。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, conversation_id: Any) -> Response:
        data = await sync_to_async(self._build, thread_sensitive=True)(
            str(conversation_id)
        )
        if data is None:
            return Response({"detail": "未找到该会话"}, status=404)

        logger.info(
            "conversation_drilldown_viewed",
            category="caller",
            component="conversation_drilldown",
            source="rest",
            conversation_id=str(conversation_id),
        )
        return Response(data)

    @staticmethod
    def _build(conversation_id: str) -> dict[str, Any] | None:
        from chat.models import Conversation, Message

        conv = (
            Conversation.objects.select_related("created_by")
            .filter(id=conversation_id)
            .first()
        )
        if conv is None:
            return None

        created_by = None
        if conv.created_by is not None:
            created_by = {
                "id": str(conv.created_by.id),
                "username": conv.created_by.username,
            }

        messages = [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "parts": m.parts,
                "metadata": m.metadata,
                "created_at": m.created_at.isoformat(),
            }
            for m in Message.objects.filter(conversation=conv).order_by("created_at")
        ]

        # 关联键下钻（不复制正文）：按 correlation.conversation_id 取相关 SystemLogEntry
        # 摘要，再从其 correlation.run_id 关联出相关 InteractionRun 摘要。
        related_logs, related_runs = _related_links(conversation_id)

        return {
            "conversation": {
                "id": str(conv.id),
                "title": conv.title,
                "status": conv.status,
                "model": conv.model,
                "project_id": str(conv.space_id) if conv.space_id else None,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
            },
            "created_by": created_by,
            "messages": messages,
            "related_logs": related_logs,
            "related_runs": related_runs,
        }


def _related_links(
    conversation_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 ``correlation.conversation_id`` 关联出 SystemLogEntry / InteractionRun 摘要。

    只回关联键 + 摘要（id / 事件 / 时间 / 关联键），**不复制正文**（per「三者关联不复制」）。
    JSON key 查询在 PG / SQLite（JSON1）均可用；失败保守返回空（best-effort）。
    """
    from interactions.models import InteractionRun
    from system.models import SystemLogEntry

    related_logs: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    try:
        logs = SystemLogEntry.objects.filter(
            correlation__conversation_id=conversation_id
        ).order_by("-ts")[:_MAX_RELATED_ROWS]
        for log in logs:
            corr = log.correlation if isinstance(log.correlation, dict) else {}
            related_logs.append(
                {
                    "id": log.id,
                    "ts": log.ts.isoformat() if log.ts else None,
                    "level": log.level,
                    "component": log.component,
                    "event": log.event,
                    "request_id": log.request_id,
                    "correlation": corr,
                }
            )
            rid = corr.get("run_id")
            if rid:
                run_ids.add(str(rid))
    except Exception:  # noqa: BLE001 — 关联下钻 best-effort，绝不反噬主响应
        related_logs = []

    related_runs: list[dict[str, Any]] = []
    if run_ids:
        try:
            for run in InteractionRun.objects.filter(run_id__in=run_ids):
                related_runs.append(
                    {
                        "run_id": str(run.run_id),
                        "source": run.source,
                        "status": run.status,
                        "request_id": run.request_id,
                        "created_at": run.created_at.isoformat(),
                    }
                )
        except Exception:  # noqa: BLE001 — best-effort
            related_runs = []

    return related_logs, related_runs
