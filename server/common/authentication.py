"""Cookie-based JWT authentication for DRF.
Replaces header-based JWTAuthentication with cookie-based lookup,
eliminating XSS access-token theft while keeping refresh-token rotation.
"""
from __future__ import annotations
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
class CookieJWTAuthentication(JWTAuthentication):
 """Extract the access token from an HTTP-only cookie instead of Authorization header.
 The access token is set by LoginView and RefreshTokenView as
 ``access_token`` cookie with HttpOnly, SameSite, and Secure flags.
 """
 def get_header(self, request: Request) -> bytes:
 """Cookie 优先 + Authorization Bearer 兜底。
 work item 期待 ``bytes``，形如 ``b"Bearer <token>"``。
 优先级：
 1. ``access_token`` cookie（Web UI 主路径，HttpOnly 防 XSS 是首选语义）
 2. ``Authorization: Bearer <token>`` header（外部 SDK / 脚本 / OpenAI compat 客户端
 / 测试 APIClient 均通过 Authorization header 携带 Bearer JWT 访问）
 两条路径走完全相同的验证管线，安全等价；这里只解决"如何从 request 取到 token"。
 """
 token = request.COOKIES.get("access_token")
 if token:
 return f"Bearer {token}".encode
 # 兜底走 SimpleJWT 默认实现，从 Authorization header 读取
 return super.get_header(request)
