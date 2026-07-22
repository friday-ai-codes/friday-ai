"""单 token MCP/Skill 外部入口集成 helper（供 work-item 复用）。

把「认证 + 顶层 run 创建」收敛成一处薄封装，让后续 work-item 的 MCP/Skill view
不必各自拼装 ledger 调用：

- ``ACCESS_TOKEN_AUTH`` / ``AccessTokenAuthentication``：约定后续 view 把
  ``authentication_classes`` 指向 Friday Access Token 认证类。有效 token 即放行
  （contract single token，无 scope 分权）；认证类是创建 run 之前的唯一关卡
  （威胁 security mitigation-04：未认证请求不可能拿到 ``request.auth`` 进而建 run）。
- ``begin_interaction_run``：异步入口，在请求通过认证后同步创建顶层
  ``InteractionRun``（contract 保证可追踪），``token_fingerprint`` 取
  ``request.auth.token_hash``（绝不取明文，contract），``raw_request`` 经
  ``acreate_interaction_run`` 内部统一脱敏后入库。
- Skill 编排可在首个 tool 响应拿到 ``run_id`` 后，把后续请求的
  ``X-Friday-Run-ID`` / ``X-Friday-Workflow-Run-ID`` 设为该值，从而把多次 MCP
  tool call 复用到同一个 running ``InteractionRun``。可选
  ``X-Friday-Skill-Step`` 会写入 ``skill_step`` 事件。

约定用法（work-item 的 MCP/Skill view）::

    from interactions.entry import AccessTokenAuthentication, begin_interaction_run

    class SomeMcpView(APIView):
        authentication_classes = [AccessTokenAuthentication]
        permission_classes = [AllowAny]  # token-only 访问，认证类已是唯一关卡

        async def post(self, request):
            run = await begin_interaction_run(request, source="mcp")
            ...  # 工具调用 + record_event / record_tool_call 挂到该 run
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request

# re-export 认证类，方便后续 view 直接 `from interactions.entry import ...`。
from access_tokens.authentication import AccessTokenAuthentication
from interactions.ledger import acreate_interaction_run, arecord_event
from interactions.models import InteractionEvent, InteractionRun

# 认证类点路径常量，便于 DRF settings / 字符串引用场景复用。
ACCESS_TOKEN_AUTH = "access_tokens.authentication.AccessTokenAuthentication"

__all__ = [
    "ACCESS_TOKEN_AUTH",
    "AccessTokenAuthentication",
    "begin_interaction_run",
]


async def begin_interaction_run(request: Request, *, source: str) -> InteractionRun:
    """通过认证后创建顶层 InteractionRun（异步入口，contract）。

    ``request.auth`` 由 ``AccessTokenAuthentication`` 注入（AccessToken 实例）。
    ``token_fingerprint`` 取其 ``token_hash``——只存 hash，绝不回写明文
    （contract）；``request_id`` 取 ``X-Request-ID`` header；``raw_request``
    捕获请求元数据 + body，由 ``acreate_interaction_run`` 内部 ``redact_for_ledger``
    统一脱敏后入库。

    Args:
        request: 已通过 AccessTokenAuthentication 认证的 DRF 请求。
        source: 入口来源标识（如 ``"mcp"`` / ``"skill"``）。

    Returns:
        同步创建落库的 ``InteractionRun``（供后续子事件挂载）。
    """
    # PAT 路径：request.auth 是 AccessToken，取其 token_hash（只存 hash，绝不明文）。
    # JWT 路径（CookieJWTAuthentication）：request.auth 是已验证的 JWT，无 token_hash →
    # 退化为基于已认证用户的稳定非敏感标识 user:<id>，保住审计连续性（绝不记明文/原始 JWT）。
    token_fingerprint = getattr(request.auth, "token_hash", "") or (
        f"user:{request.user.id}"
        if getattr(request, "user", None) is not None and request.user.is_authenticated
        else ""
    )

    requested_run_id = (
        request.META.get("HTTP_X_FRIDAY_RUN_ID")
        or request.META.get("HTTP_X_FRIDAY_WORKFLOW_RUN_ID")
        or ""
    )
    if requested_run_id:
        existing_run = await InteractionRun.objects.filter(
            run_id=requested_run_id,
            token_fingerprint=token_fingerprint,
            status=InteractionRun.Status.RUNNING,
        ).afirst()
        if existing_run is not None:
            await _record_skill_step_header(existing_run, request)
            return existing_run

    raw_request: dict[str, Any] = {
        "method": request.method,
        "path": request.path,
    }
    # body / 解析后入参一并留痕；明文 token/secret 由 ledger 写库前脱敏兜底。
    try:
        data = request.data
    except Exception:
        data = None
    if data:
        raw_request["data"] = data

    # 容器任务关联键（103-02 AGENT-02）：容器知识 MCP 转调携带 X-Friday-Session-Id
    # （dispatch 链 task_id 即 subagent session_id），非空时入 raw_request，
    # run/task 即可按 InteractionRun.raw_request__task_session_id 关联查询
    # （RetrievalTrace 经 run 外键天然可达，不重复写）。观测面复用：容器转调走
    # /api/mcp/tools/* 已进 McpToolView._record（RequestMetric source=mcp，
    # labels 含 call_source/run_id），QPS/错误率/时长零新建。
    task_session_id = request.META.get("HTTP_X_FRIDAY_SESSION_ID", "")
    if task_session_id:
        raw_request["task_session_id"] = task_session_id

    run = await acreate_interaction_run(
        token_fingerprint=token_fingerprint,
        source=source,
        request_id=request.META.get("HTTP_X_REQUEST_ID", ""),
        raw_request=raw_request,
    )
    await _record_skill_step_header(run, request)
    return run


async def _record_skill_step_header(run: InteractionRun, request: Request) -> None:
    step = request.META.get("HTTP_X_FRIDAY_SKILL_STEP", "")
    if not step:
        return
    await arecord_event(
        run,
        InteractionEvent.EventType.SKILL_STEP,
        {
            "step": step,
            "path": request.path,
            "method": request.method,
        },
    )
