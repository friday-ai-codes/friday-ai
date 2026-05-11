"""OpenAI 协议兼容层 Views 占位（任务 3 完整实现）。"""
from adrf.views import APIView
class ChatCompletionsView(APIView):
 """POST /v1/chat/completions — 占位，任务 3 完整实现。"""
 authentication_classes: list =
 permission_classes: list =
 async def post(self, request): # type: ignore[override]
 from rest_framework.response import Response
 return Response({"error": {"message": "not implemented", "type": "server_error", "code": "not_implemented"}}, status=501)
class ModelsView(APIView):
 """GET /v1/models — 占位，任务 3 完整实现。"""
 authentication_classes: list =
 permission_classes: list =
 async def get(self, request): # type: ignore[override]
 from rest_framework.response import Response
 return Response({"error": {"message": "not implemented", "type": "server_error", "code": "not_implemented"}}, status=501)
