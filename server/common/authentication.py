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
 """Override header extraction to read from cookie.
 work item expects a ``bytes`` object in the form ``b"Bearer <token>"``.
 We synthesise that from the cookie value so the rest of the
 authentication pipeline works unchanged.
 """
 token = request.COOKIES.get("access_token")
 if token:
 return f"Bearer {token}".encode
 return b""
