"""Base class for trigger nodes."""

from abc import abstractmethod
from datetime import datetime, timezone
from typing import ClassVar, Literal

import structlog

from common.exceptions import TriggerParseError
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
)

logger = structlog.get_logger()


class BaseTriggerNode(BaseNode):
    """Abstract base class for all trigger nodes.

    Provides:
    - Common logging for trigger events
    - Exception wrapping with TriggerParseError
    - Standard output structure with base fields

    Subclasses implement parse_payload() to extract type-specific data.
    """

    category: ClassVar[NodeCategory] = NodeCategory.TRIGGER
    execution_mode: ClassVar[Literal["server_local", "runner_dispatched"]] = "server_local"
    inputs: ClassVar[list[NodePort]] = []  # Triggers have no input ports

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """Template method: log trigger, parse payload, wrap errors.

        Subclasses should NOT override this method. Instead, implement
        parse_payload() to provide type-specific extraction logic.
        """
        raw_payload = context.input_data.get("raw_payload", context.input_data)

        logger.info(
            "trigger_node_execute",
            trigger_type=self.node_type,
            payload_size=len(str(raw_payload)),
            execution_id=context.execution_id,
        )

        try:
            # Call subclass implementation
            parsed_data = await self.parse_payload(context)

            # Build output with base fields + parsed data
            output = {
                "trigger_type": self.node_type,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "raw_payload": raw_payload,
            }

            # Add source info if available
            if context.workflow_execution:
                output["source_id"] = str(context.workflow_execution.workflow_id)

            # Merge parsed data (data key contains type-specific fields)
            output.update(parsed_data)

            logger.debug(
                "trigger_node_complete",
                trigger_type=self.node_type,
                output_keys=list(output.keys()),
            )

            return NodeResult(status="completed", output=output)

        except TriggerParseError:
            # Already wrapped, re-raise
            raise
        except Exception as e:
            logger.error(
                "trigger_parse_failed",
                trigger_type=self.node_type,
                error=str(e),
                execution_id=context.execution_id,
            )
            raise TriggerParseError(f"Failed to parse {self.node_type} payload: {e}") from e

    @abstractmethod
    async def parse_payload(self, context: ExecutionContext) -> dict:
        """Extract structured data from raw_payload.

        Subclasses implement this to parse type-specific payload format.

        Args:
            context: Execution context with input_data containing raw_payload

        Returns:
            dict with parsed data. Should include 'data' key for type-specific
            fields. May also include source_id, source_name if known.

        Raises:
            TriggerParseError: When critical fields are missing or invalid.
            Other exceptions are caught by execute() and wrapped.

        Notes:
            - Critical fields: raise TriggerParseError on failure
            - Optional fields: use default values, log warning
            - Always access raw_payload via context.input_data.get("raw_payload", {})
        """
        pass
