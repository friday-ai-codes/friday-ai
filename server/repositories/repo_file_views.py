"""按 ``path`` + 行区间读源码正文的 SPA 读面（Phase 116-07，VIEW-02）。

``GET /api/repositories/<uuid:repository_id>/file-lines/?path=&line_start=&line_end=&branch_name=``：
返回 ``[line_start, line_end]`` 闭区间的源码正文行，供蓝图引用二级预览渲染**带行号列与行
高亮**的代码片段。115-03 把 ``CitationCodePreview`` 显式降级为「路径 + 行号区间 + citation
的 quote 快照」，缺的正是这个读面；读取实现是 ``services.repo_file_read`` 那**唯一一份**
（与 MCP 的 ``get_repository_file`` 共享，⛔ 不存在第二份排除判定）。

安全语义（⭐ 逐条对齐 ``chunk_at_views.py:5-9`` 的中性口径说明书）：

- ``permission_classes = [IsAuthenticated, RepositoryPermission]``：未认证一律拒（401/403）；
  仓库不存在 / 已删除一律拒。口径按 ``repositories/permissions.py`` 与既有仓库读面实读取得
  （``codegraph/views.py`` 的六个 adrf 读面即 ``[IsAuthenticated, RepositoryPermission]``），
  额外再走一次 ``aget_object_or_404(..., is_deleted=False)``（与 ``chunk-at`` 同口径）。
  ⛔ 不因为「引用预览是只读」就放宽。
- ⭐ **被排除文件 / 文件不存在 / 仓库无镜像三者对外不可区分** —— 统一 **200** +
  ``{path, line_start, line_end, lines: [], truncated: false}``，避免存在性泄漏（与
  ``chunk_at_views`` 的 T-25-05 同源）。⇒ ⛔ **本端点没有任何「未找到」错误分支**、⛔ 不带
  能区分三者的 ``detail``、⛔ 不沿用 MCP 面「把『已被排除策略屏蔽』显式告知调用方」的口径
  （那会让排除策略的存在性可被枚举，且与 115-07 前端「非 200 不进错误分档」的实现冲突）。
  ⚠️ 上面这两条纪律有源码级守卫盯着（见 ``tests/repositories/test_repo_file_read_views.py``），
  ⇒ 本文件里连**说明用**的错误码字面量都不能写。
- 参数缺失或非法 → **400**，且**不触 service**（与 T-25-07 同源）。⚠️ **错误体键是
  ``error``** 而不是 ``detail``（与 ``chunk_at`` 同口径；前端 ``ApiError.detail`` 在响应体无
  ``detail`` 键时会回落成无意义的「请求失败」⇒ ⛔ 任何调用点都不得回显它）。
- ⭐ **区间上界是截断而不是报错**：返回行数超过 ``_MAX_LINES`` 时截断到上界并置
  ``truncated: true``，**状态码仍 200**，⛔ 不 400 —— 引用的行区间来自半可信的 citation
  ``locator``（含 LLM 产出），一个写错的区间不该让整个预览失败；同时这也是 T-116-64 的
  DoS 防线（挡住「一次请求读整个大文件」）。

观测：一条 caller 事件。⛔ **文件路径与源码正文一律不进日志**，只记 ``path_len`` /
``line_start`` / ``line_end`` / ``line_count`` / ``truncated`` / ``duration_ms``；触发用户由
统一中间件注入。观测 best-effort，⛔ 绝不反噬读取主流程。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from adrf.views import APIView
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from repositories.models import Repository
from repositories.permissions import RepositoryPermission
from services.repo_file_read import aread_repository_file

logger = structlog.get_logger(__name__)

_COMPONENT = "repo_file_lines_view"

#: 单次返回行数硬上限。超出即截断并置 ``truncated: true``（⛔ 不 400）。
_MAX_LINES = 400

#: 传给 service 的调用面标识，用于区分排除审计埋点来自哪条链。
_SURFACE = "blueprint_citation_preview"


def _neutral_payload(path: str, line_start: int, line_end: int) -> dict[str, Any]:
    """⭐ 「不可读」的唯一响应体：被排除 / 不存在 / 无镜像三者共用它，⇒ 逐字相同、无存在性预言机。"""
    return {
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "lines": [],
        "truncated": False,
    }


def _parse_positive_int(raw: str | None, field: str) -> tuple[int, Response | None]:
    """把 query 参数解析成正整数；缺失 / 非整数 / 非正一律 400（错误体键是 ``error``）。"""
    if raw is None or raw == "":
        return 0, Response({"error": f"缺少必填参数 {field}"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0, Response({"error": f"{field} 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST)
    if value < 1:
        return 0, Response({"error": f"{field} 必须为正整数"}, status=status.HTTP_400_BAD_REQUEST)
    return value, None


class RepositoryFileLinesView(APIView):
    """按 ``path`` + 行区间读源码正文行（引用二级预览的代码片段数据面）。"""

    permission_classes = [IsAuthenticated, RepositoryPermission]

    async def get(self, request, repository_id):
        started = time.monotonic()
        await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        path = request.query_params.get("path")
        if not path:
            return Response({"error": "缺少必填参数 path"}, status=status.HTTP_400_BAD_REQUEST)

        line_start, err = _parse_positive_int(request.query_params.get("line_start"), "line_start")
        if err is not None:
            return err
        line_end, err = _parse_positive_int(request.query_params.get("line_end"), "line_end")
        if err is not None:
            return err
        if line_end < line_start:
            return Response(
                {"error": "line_end 不得小于 line_start"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        branch_name = request.query_params.get("branch_name", "")

        result = await aread_repository_file(
            str(repository_id),
            path,
            branch_name=branch_name,
            surface=_SURFACE,
            line_start=line_start,
            line_end=line_end,
            max_lines=_MAX_LINES,
        )
        # ⭐ 只有 ok 才带正文；excluded / not_found / unavailable 一律回同一个 200 空结构。
        if result["status"] == "ok":
            payload = {
                "path": path,
                "line_start": line_start,
                "line_end": line_end,
                "lines": result["lines"],
                "truncated": result["truncated"],
            }
        else:
            payload = _neutral_payload(path, line_start, line_end)

        try:
            logger.info(
                "repository_file_lines_read",
                category="caller",
                component=_COMPONENT,
                repository_id=str(repository_id),
                # ⛔ path 原文与源码正文不进日志，只记标量
                path_len=len(str(path)),
                line_start=line_start,
                line_end=line_end,
                line_count=len(payload["lines"]),
                truncated=payload["truncated"],
                usable=result["status"] == "ok",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬读取主流程
            pass

        return Response(payload)
