"""MCP read tools 统一错误信封。"""
from __future__ import annotations
from typing import Any
from rest_framework.response import Response
def error_response(error_code: str, detail: Any, *, status_code: int) -> Response:
 """返回 MCP tool 统一错误体。"""
 return Response(
 {"error_code": error_code, "detail": detail},
 status=status_code,
 )
