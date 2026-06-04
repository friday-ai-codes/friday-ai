"""单 token MCP/Skill 外部入口集成 helper（供 work-item 复用）。
把「认证 + 顶层 run 创建」收敛成一处薄封装，让后续 work-item 的 MCP/Skill view
不必各自拼装 ledger 调用：
- ``ACCESS_TOKEN_AUTH`` / ``AccessTokenAuthentication``：约定后续 view 把
 ``authentication_classes`` 指向 Friday Access Token 认证类。有效 token 即放行
 （ single token，无 scope 分权）；认证类是创建 run 之前的唯一关卡
 （威胁 T-：未认证请求不可能拿到 ``request.auth`` 进而建 run）。
- ``begin_interaction_run``：异步入口，在请求通过认证后同步创建顶层
 ``InteractionRun``（ 保证可追踪），``token_fingerprint`` 取
 ``request.auth.token_hash``（绝不取明文，），``raw_request`` 经
 ``acreate_interaction_run`` 内部统一脱敏后入库。
约定用法（work-item 的 MCP/Skill view）:
 from interactions.entry import AccessTokenAuthentication, begin_interaction_run
 class SomeMcpView(APIView):
 authentication_classes = [AccessTokenAuthentication]
 permission_classes = [AllowAny] # token-only 访问，认证类已是唯一关卡
 async def post(self, request):
 run = await begin_interaction_run(request, source="mcp")
 ... # 工具调用 + record_event / record_tool_call 挂到该 run
"""
from __future__ import annotations
from typing import Any
from rest_framework.request import Request
# re-export 认证类，方便后续 view 直接 `from interactions.entry import ...`。
from access_tokens.authentication import AccessTokenAuthentication
from interactions.ledger import acreate_interaction_run
from interactions.models import InteractionRun
# 认证类点路径常量，便于 DRF settings / 字符串引用场景复用。
ACCESS_TOKEN_AUTH = "access_tokens.authentication.AccessTokenAuthentication"
__all__ = [
 "ACCESS_TOKEN_AUTH",
 "AccessTokenAuthentication",
 "begin_interaction_run",
]
async def begin_interaction_run(request: Request, *, source: str) -> InteractionRun:
 """通过认证后创建顶层 InteractionRun（异步入口，）。
 ``request.auth`` 由 ``AccessTokenAuthentication`` 注入（AccessToken 实例）。
 ``token_fingerprint`` 取其 ``token_hash``——只存 hash，绝不回写明文；``request_id`` 取 ``X-Request-ID`` header；``raw_request``
 捕获请求元数据 + body，由 ``acreate_interaction_run`` 内部 ``redact_for_ledger``
 统一脱敏后入库。
 Args:
 request: 已通过 AccessTokenAuthentication 认证的 DRF 请求。
 source: 入口来源标识（如 ``"mcp"`` / ``"skill"``）。
 Returns:
 同步创建落库的 ``InteractionRun``（供后续子事件挂载）。
 """
 token_fingerprint = getattr(request.auth, "token_hash", "")
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
 return await acreate_interaction_run(
 token_fingerprint=token_fingerprint,
 source=source,
 request_id=request.META.get("HTTP_X_REQUEST_ID", ""),
 raw_request=raw_request,
 )
