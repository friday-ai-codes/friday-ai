"""Common exceptions."""
from rest_framework.views import exception_handler
def custom_exception_handler(exc, context):
 """Custom exception handler to match FastAPI error format."""
 response = exception_handler(exc, context)
 if response is not None:
 # Ensure 'detail' key exists for consistency with FastAPI
 if "detail" not in response.data and isinstance(response.data, dict):
 if len(response.data) == 1:
 key = list(response.data.keys)[0]
 value = response.data[key]
 if isinstance(value, list) and len(value) == 1:
 response.data = {"detail": str(value[0])}
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
