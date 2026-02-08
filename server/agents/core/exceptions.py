"""
Agent framework exceptions.
Provides a hierarchy of exceptions for the agent system:
- AgentError: Base exception for all agent-related errors
- ToolExecutionError: Raised when a tool fails during execution
- ToolValidationError: Raised when tool arguments fail JSON Schema validation
- MaxIterationsError: Raised when the agent loop exceeds the maximum iteration count
"""
class AgentError(Exception):
 """Base exception for all agent-related errors."""
 def __init__(self, message: str, details: dict | None = None) -> None:
 super.__init__(message)
 self.message = message
 self.details = details or {}
 def __str__(self) -> str:
 if self.details:
 return f"{self.message} | Details: {self.details}"
 return self.message
class ToolExecutionError(AgentError):
 """Raised when a tool fails during execution."""
 def __init__(
 self,
 message: str,
 tool_name: str,
 tool_call_id: str = "",
 details: dict | None = None,
 ) -> None:
 super.__init__(message, details)
 self.tool_name = tool_name
 self.tool_call_id = tool_call_id
class ToolValidationError(AgentError):
 """Raised when tool arguments fail JSON Schema validation."""
 def __init__(
 self,
 message: str,
 tool_name: str,
 validation_errors: list[str] | None = None,
 details: dict | None = None,
 ) -> None:
 super.__init__(message, details)
 self.tool_name = tool_name
 self.validation_errors = validation_errors or
class MaxIterationsError(AgentError):
 """Raised when the agent loop exceeds the maximum iteration count."""
 def __init__(
 self,
 message: str,
 iterations: int,
 max_iterations: int,
 details: dict | None = None,
 ) -> None:
 super.__init__(message, details)
 self.iterations = iterations
 self.max_iterations = max_iterations
