"""SubAgent API views for callback handling.
Provides:
- SubAgentCallbackView: Callback handler for SubAgent completion
"""
import json
from typing import Any
import structlog
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from tasks.agent_tasks import schedule_resume_agent_session
logger = structlog.get_logger(__name__)
class SubAgentCallbackView(APIView):
 """Receive SubAgent task completion callbacks.
 When SubAgent completes a task, it POSTs to this endpoint
 to notify the main Agent and resume execution.
 POST /api/subagent/callback/
 """
 permission_classes = [AllowAny] # Internal network, can add signature verification later
 def post(self, request: Request) -> Response:
 """Handle SubAgent completion callback.
 Request body:
 {
 "task_id": "task-...",
 "main_session_id": "sess-...",
 "status": "completed" | "error",
 "output": {...},
 "error": "..." (optional)
 }
 Response:
 {
 "status": "accepted"
 }
 """
 data = request.data
 task_id = data.get("task_id", "")
 main_session_id = data.get("main_session_id", "")
 status = data.get("status", "")
 output = data.get("output")
 error = data.get("error")
 log = logger.bind(
 task_id=task_id,
 main_session_id=main_session_id,
 )
 log.info("subagent_callback_received", status=status)
 if not main_session_id:
 log.warning("subagent_callback_missing_session")
 return Response({"status": "error", "message": "Missing main_session_id"}, status=400)
 # Construct user response (SubAgent result as JSON)
 if status == "completed":
 user_response = json.dumps({
 "status": "success",
 "task_id": task_id,
 "output": output,
 }, ensure_ascii=False)
 else:
 user_response = json.dumps({
 "status": "error",
 "task_id": task_id,
 "error": error or "SubAgent execution failed",
 }, ensure_ascii=False)
 # Schedule agent resume in background
 schedule_resume_agent_session(main_session_id, user_response)
 log.info("subagent_callback_processed", resume_scheduled=True)
 return Response({"status": "accepted"})
