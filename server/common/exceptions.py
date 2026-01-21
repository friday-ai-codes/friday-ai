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
