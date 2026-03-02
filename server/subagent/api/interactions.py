"""InteractionLog API views — 节点调试面板的数据源。"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from adrf.views import APIView
from subagent.models import InteractionLog
from .serializers import InteractionAnswerSerializer, InteractionLogSerializer
class NodeInteractionLogsView(APIView):
 """获取某个 node execution 关联的所有 InteractionLog。
 GET /api/containers/node-executions/<node_execution_id>/interactions/
 """
 permission_classes = [IsAuthenticated]
 async def get(self, request, node_execution_id: str) -> Response:
 logs = [
 log async for log in InteractionLog.objects.filter(
 session__node_execution_id=node_execution_id,
 ).select_related("session").order_by("asked_at")
 ]
 data = InteractionLogSerializer(logs, many=True).data
 return Response(data)
class InteractionAnswerView(APIView):
 """通过 Web 端提交 InteractionLog 的回答。
 POST /api/containers/interactions/<interaction_id>/answer/
 """
 permission_classes = [IsAuthenticated]
 async def post(self, request, interaction_id: int) -> Response:
 ser = InteractionAnswerSerializer(data=request.data)
 ser.is_valid(raise_exception=True)
 try:
 interaction = await InteractionLog.objects.select_related("session").aget(id=interaction_id)
 except InteractionLog.DoesNotExist:
 return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
 if interaction.answered_at is not None:
 return Response({"detail": "Already answered"}, status=status.HTTP_409_CONFLICT)
 answer = ser.validated_data["answer"]
 answer_source = ser.validated_data["answer_source"]
 from subagent.question_handler import handle_container_answer_enhanced
 await handle_container_answer_enhanced(
 session_id=interaction.session.session_id,
 question_id=interaction.question_id,
 answer=answer,
 answer_source=answer_source,
 )
 # 重新获取以确保 session FK 已加载（arefresh_from_db 不加载 FK）
 interaction = await InteractionLog.objects.select_related("session").aget(
 id=interaction_id
 )
 data = InteractionLogSerializer(interaction).data
 return Response(data)
class AgentSessionAnswerView(APIView):
 """通过 Web 端回答 AgentSession 的提问（AIAgentBaseNode 场景）。
 POST /api/containers/agent-sessions/<session_id>/answer/
 """
 permission_classes = [IsAuthenticated]
 async def post(self, request, session_id: str) -> Response:
 ser = InteractionAnswerSerializer(data=request.data)
 ser.is_valid(raise_exception=True)
 from agents.models import AgentSession
 try:
 session = await AgentSession.objects.aget(session_id=session_id)
 except AgentSession.DoesNotExist:
 return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
 if session.status != AgentSession.Status.SUSPENDED:
 return Response({"detail": "Session not suspended"}, status=status.HTTP_409_CONFLICT)
 answer = ser.validated_data["answer"]
 from tasks.agent_tasks import schedule_resume_agent_session
 schedule_resume_agent_session(session_id, answer)
 return Response({"status": "ok", "session_id": session_id})
