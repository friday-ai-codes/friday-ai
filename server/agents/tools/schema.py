"""
JSON Schema validation utilities for tool arguments.
Provides validation of tool arguments against JSON Schema definitions.
"""
from typing import Any
import jsonschema
from jsonschema import ValidationError
def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> tuple[bool, str | None]:
 """
 Validate tool arguments against a JSON Schema.
 Args:
 schema: JSON Schema definition for the tool parameters
 arguments: Arguments to validate
 Returns:
 Tuple of (is_valid, error_message).
 If valid, returns (True, None).
 If invalid, returns (False, human-readable error message).
 """
 try:
 jsonschema.validate(instance=arguments, schema=schema)
 return True, None
 except ValidationError as e:
 # Format a clear error message
 path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
 error_message = f"Validation error at '{path}': {e.message}"
 return False, error_message
def get_default_schema -> dict[str, Any]:
 """
 Get the default JSON Schema for tools with no parameters.
 Returns:
 Empty object schema that accepts no properties.
 """
 return {"type": "object", "properties": {}}
