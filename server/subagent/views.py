"""SubAgent API views for mock execution and callback handling.
Provides:
- MockSubAgentTaskView: Mock endpoint for task submission (development)
- SubAgentCallbackView: Callback handler for SubAgent completion
"""
import json
import time
import uuid
from typing import Any
import httpx
import structlog
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from tasks.agent_tasks import schedule_resume_agent_session
logger = structlog.get_logger(__name__)
def generate_mock_output(task_type: str, request_data: dict[str, Any]) -> dict[str, Any]:
 """Generate mock output based on task type.
 Args:
 task_type: Task type (explore, ask, plan, coding)
 request_data: Original request data
 Returns:
 Mock output matching expected format for each task type
 """
 if task_type == "explore":
 return {
 "structure": {
 "type": "monorepo",
 "directories": ["src/", "tests/", "docs/"],
 "main_language": "Python",
 "frameworks": ["Django", "Vue"],
 },
 "summary": "This is a frontend-backend separated Monorepo project...",
 }
 elif task_type == "ask":
 prompt = request_data.get("prompt", "")
 return {
 "answer": f"Regarding your question '{prompt[:50]}...': This is a mock answer.",
 "confidence": "high",
 }
 elif task_type == "plan":
 return {
 "plan_section": "## Technical Plan\n\n### Implementation Steps\n1. Step one\n2. Step two",
 "estimated_effort": "2 days",
 }
 elif task_type == "coding":
 return {
 "commits": ["abc1234"],
 "branch": request_data.get("target_branch", "feature/mock"),
 "files_changed": 3,
 "summary": "Code changes completed and pushed to remote branch.",
 }
 return {"message": "Unknown task type"}
def mock_subagent_execution(
 task_id: str,
 request_data: dict[str, Any],
 delay_seconds: int = 5,
) -> None:
 """Simulate SubAgent execution and trigger callback.
 This function runs in background (via threading) to simulate
 async SubAgent execution with delay.
 Args:
 task_id: Unique task identifier
 request_data: Original request data
 delay_seconds: Simulated execution time
 """
 log = logger.bind(task_id=task_id)
 log.info("mock_subagent_start", delay=delay_seconds)
 # Simulate execution time
 time.sleep(delay_seconds)
 # Generate mock result
 task_type = request_data.get("task_type", "")
 mock_output = generate_mock_output(task_type, request_data)
 log.info("mock_subagent_complete", task_type=task_type)
 # Trigger callback
 callback_url = request_data.get("callback_url")
 main_session_id = request_data.get("main_session_id", "")
 if callback_url:
 try:
 response = httpx.post(
 callback_url,
 json={
 "task_id": task_id,
 "main_session_id": main_session_id,
 "status": "completed",
 "output": mock_output,
 },
 timeout=10.0,
 )
 log.info(
 "mock_subagent_callback_sent",
 status_code=response.status_code,
 )
 except Exception as e:
 log.error("mock_subagent_callback_failed", error=str(e))
class MockSubAgentTaskView(APIView):
 """Mock SubAgent task submission endpoint.
 Used for development and testing. Real SubAgent container
 will have similar API contract.
 POST /api/subagent/tasks/
 """
 permission_classes = [AllowAny]
 def post(self, request: Request) -> Response:
 """Accept task and simulate async processing.
 Immediately returns task ID, background thread simulates
 delayed execution and triggers callback.
 Request body:
 {
 "session_id": "sub-...",
 "task_type": "explore" | "ask" | "plan" | "coding",
 "repo_url": "https://github.com/...",
 "branch": "main",
 "target_branch": "feature/..." (optional),
 "prompt": "...",
 "context": {...},
 "main_session_id": "sess-...",
 "callback_url": "http://..."
 }
 Response:
 {
 "task_id": "task-...",
 "status": "pending"
 }
 """
 data = request.data
 task_id = f"task-{uuid.uuid4.hex[:8]}"
 log = logger.bind(
 task_id=task_id,
 task_type=data.get("task_type"),
 session_id=data.get("session_id"),
 )
 log.info("mock_subagent_task_received")
 # Schedule background execution via threading
 import threading
 thread = threading.Thread(
 target=mock_subagent_execution,
 args=(task_id, dict(data), 5),
 daemon=True,
 )
 thread.start
 return Response({
 "task_id": task_id,
 "status": "pending",
 })
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
