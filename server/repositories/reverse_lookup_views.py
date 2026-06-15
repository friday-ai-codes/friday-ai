"""片段→需求反查 REST 端点（Phase 34 RREF-01，per 34-01 plan Task 2）。

``GET /api/repositories/<id>/reverse-lookup/?path=&line=`` 或 ``?chunk_id=``：
反查关联的 work_item / document，返回结构化 ``{chunks, related_work_items,
related_documents, paths}``（与 MCP 工具同形）。

安全语义（复用 ``services.reverse_lookup`` 的 fail-closed，对齐 ChunkAtView）：
- ``permission_classes=[IsAuthenticated]``：未认证 401/403（T-34A-04）。
- 被排除文件与「无命中」对外**不可区分**——两者统一走 service（service 已 fail-closed），
  返回空 chunks/related，不在 view 层区分存在性（T-34A-01）。
- 必须给 ``(path+line)`` 或 ``chunk_id``，否则 400；``line`` 非正整数 → 400（不触 service）。
"""

from __future__ import annotations

import uuid

from adrf.views import APIView
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from repositories.models import Repository
from services.reverse_lookup import reverse_lookup


class ReverseLookupView(APIView):
    """片段→需求反查端点（REST）。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        path = request.query_params.get("path")
        chunk_id = request.query_params.get("chunk_id")
        line_raw = request.query_params.get("line")
        branch_name = request.query_params.get("branch_name", "")

        line: int | None = None
        if path:
            # path 必须配 line（正整数），不触 service 先校验（对齐 ChunkAtView）
            if line_raw is None or line_raw == "":
                return Response(
                    {"error": "提供 path 时必须同时提供 line"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                line = int(line_raw)
            except (TypeError, ValueError):
                return Response(
                    {"error": "line 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST
                )
            if line < 1:
                return Response(
                    {"error": "line 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST
                )
        elif not chunk_id:
            return Response(
                {"error": "必须提供 (path 且 line) 或 chunk_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # chunk_id 必须为合法 UUID（ChunkRegistry.chunk_id 为 UUIDField，畸形值会触
        # ValidationError → 500）；在 view 层 fail 到 400，与 line 校验/MCP 序列化器对齐
        if chunk_id:
            try:
                uuid.UUID(chunk_id)
            except (TypeError, ValueError):
                return Response(
                    {"error": "chunk_id 必须为合法 UUID"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        result = await reverse_lookup(
            str(repository_id),
            file_path=path,
            line=line,
            chunk_id=chunk_id,
            branch_name=branch_name,
        )
        return Response(result, status=status.HTTP_200_OK)
