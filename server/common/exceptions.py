"""Common exceptions."""
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler
def custom_exception_handler(exc, context):
 """统一异常处理器，输出规范化错误响应。
 同时处理 TriggerError 继承体系，输出统一的触发器错误响应：
 - TriggerValidationError -> 400 Bad Request
 - TriggerAuthError -> 401 Unauthorized
 - TriggerError (base) -> 500 Internal Server Error
 """
 response = exception_handler(exc, context)
 if response is not None:
 # 429 限流：替换 DRF 默认机器翻译为更友好的文案
 if isinstance(exc, Throttled):
 wait = getattr(exc, "wait", None)
 if wait:
 response.data = {
 "detail": f"操作太快了，请 {int(wait)} 秒后再试"
 }
 else:
 response.data = {"detail": "操作太快了，请稍后再试"}
 return response
 # 确保包含 detail 字段，便于前端统一展示错误
 if "detail" not in response.data and isinstance(response.data, dict):
 if len(response.data) == 1:
 key = list(response.data.keys)[0]
 value = response.data[key]
 if isinstance(value, list) and len(value) == 1:
 response.data = {"detail": str(value[0])}
 return response
 # Handle TriggerError hierarchy (check subclasses before parent)
 if isinstance(exc, TriggerValidationError):
 return Response(
 {
 "error": str(exc),
 "code": "TRIGGER_VALIDATION_ERROR",
 "details": getattr(exc, "details", {}),
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 if isinstance(exc, TriggerAuthError):
 return Response(
 {
 "error": str(exc),
 "code": "TRIGGER_AUTH_ERROR",
 "details": getattr(exc, "details", {}),
 },
 status=status.HTTP_401_UNAUTHORIZED,
 )
 if isinstance(exc, TriggerError):
 return Response(
 {
 "error": str(exc),
 "code": "TRIGGER_ERROR",
 "details": getattr(exc, "details", {}),
 },
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 return response
class FridayException(Exception):
 """Base exception for Friday."""
 pass
class ConfigurationError(FridayException):
 """Configuration error."""
 pass
class FeishuConfigurationError(ConfigurationError):
 """Feishu configuration error."""
 pass
class TriggerError(FridayException):
 """Base exception for all trigger-related errors.
 All trigger-specific exceptions should inherit from this class.
 """
 pass
class TriggerValidationError(TriggerError):
 """Validation failures in trigger processing.
 Raised when trigger context validation fails, such as:
 - Missing required fields
 - Invalid data format
 - Workflow not found or inactive
 """
 pass
class TriggerAuthError(TriggerError):
 """Authentication/authorization failures in trigger processing.
 Raised when authentication or authorization fails, such as:
 - Invalid webhook signature
 - Invalid or expired token
 - Insufficient permissions
 """
 pass
class TriggerParseError(TriggerError):
 """Payload parsing failures in trigger nodes.
 Raised when a trigger node cannot extract required data
 from the raw_payload. Used by BaseTriggerNode to wrap
 parse_payload exceptions.
 """
 pass
