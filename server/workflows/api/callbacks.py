"""Node execution callback API for container-based nodes.
This module provides the callback endpoint that containers call when
execution completes. It updates the node execution status and triggers
the workflow engine to continue.
"""
import structlog
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from workflows.models import CodingTask, NodeExecution, NodeExecutionStatus
logger = structlog.get_logger
