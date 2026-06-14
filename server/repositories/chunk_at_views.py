"""`file:line → chunk_id` 反查 REST 端点（Phase 25 IDX-02 后半，per 25-02 plan Task 2）。

``GET /api/repositories/<id>/chunk-at/?path=&line=``：返回覆盖 ``path:line`` 的 chunk(s)。

安全语义（复用 ``services.chunk_lookup.find_chunk_at`` 的 fail-closed）：
- ``permission_classes=[IsAuthenticated]``：未认证 401/403（T-25-06）。
- 被排除文件与「无命中」对外**不可区分**——两者统一返回 ``{"chunks": []}`` 200，
  避免存在性泄漏（T-25-05）。
- ``path``/``line`` 缺失或 ``line`` 非正整数 → 400（不触 service，T-25-07）。
"""

from __future__ import annotations

from adrf.views import APIView
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from repositories.models import Repository
from services.chunk_lookup import find_chunk_at


class ChunkAtView(APIView):
    """`file:line → chunk_id` 反查端点。"""

    permission_classes = [IsAuthenticated]

    async def get(self, request, repository_id):
        await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        path = request.query_params.get("path")
        if not path:
            return Response(
                {"error": "缺少必填参数 path"}, status=status.HTTP_400_BAD_REQUEST
            )

        line_raw = request.query_params.get("line")
        if line_raw is None or line_raw == "":
            return Response(
                {"error": "缺少必填参数 line"}, status=status.HTTP_400_BAD_REQUEST
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

        branch_name = request.query_params.get("branch_name", "")

        # 被排除文件与无命中均返回空 chunks（fail-closed 由 find_chunk_at 保证，不泄漏存在性）
        chunks = await find_chunk_at(
            str(repository_id), path, line, branch_name=branch_name
        )
        return Response({"path": path, "line": line, "chunks": chunks})
