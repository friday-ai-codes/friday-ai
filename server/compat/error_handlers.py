"""OpenAI 协议兼容层错误翻译工具（，T-）。
把内部异常翻译为 OpenAI {error:{message,type,code}} 格式，
不泄露 stack trace（ASVS V8.3 数据保护要求）。
"""
from __future__ import annotations
import structlog
from rest_framework.response import Response
logger = structlog.get_logger(__name__)
def openai_error_response(
 message: str,
 type_: str = "server_error",
 code: str = "internal_error",
 http_status: int = 500,
) -> Response:
 """把异常翻译为 OpenAI {error:{message,type,code}} 格式。
 遵循 ASVS V8.3：不泄漏 stack trace，仅返回三字段结构。
 """
 logger.warning("compat_error_response", message=message, type_=type_, code=code)
 return Response(
 {"error": {"message": message, "type": type_, "code": code}},
 status=http_status,
 )
