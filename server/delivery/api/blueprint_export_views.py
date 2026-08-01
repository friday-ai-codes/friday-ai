"""蓝图飞书导出面 REST（Phase 116-05，VIEW-05）。

两个端点（``IsAuthenticated`` **+ 项目范围闸**）：

- ``GET  artifacts/<uuid>/blueprint/export-feishu/availability/`` —— 三判据探测
  ``{available, reason}``（前端据此**隐藏按钮**而不是点了才报错）
- ``POST artifacts/<uuid>/blueprint/export-feishu/``               —— 导出为飞书云文档

⭐ **授权判据不是「登录了」**：两端点入口一律过
:func:`delivery.api.blueprint_review_views._aassert_project_scope`——**import 复用同源
实现，绝不造第四份**。导出会把整份蓝图正文送到外部文档系统，越权导出即项目技术细节
外泄；非成员一律**中性 404 且与「artifact 不存在」逐字相同**（``_ARTIFACT_MISSING_DETAIL``
一并 import 是硬要求，否则存在性仍可被枚举）。

**为什么新建文件**：``blueprint_doc_views`` 是只读供数面、``blueprint_review_views`` 是
人审动作面；导出是「把蓝图送出系统边界」的第三类职责（外部依赖 + 上游失败分档 + 留痕），
混进任一既有文件都会让那个文件的模块契约失焦。两个既有文件本 plan **零改动**。

⭐ **留痕的两个禁区**：

- ⛔ **绝不写 ``ArtifactVersion.content``**：``_content_hash`` 是整份 content 的 canonical
  JSON sha256，把 ``exported_at`` 写进 content 会让**每次导出翻一个版本**，版本历史被刷
  成噪声、diff 面被污染（114-04 已为时间戳立过同款纪律）。
- ⛔ **绝不把导出事件加进 ``BLUEPRINT_EVENTS``**：那个 frozenset 被 ``len == 21`` 双断言
  锁死，且它同时是 115 ``blueprint/events/`` 端点的过滤集合——加进去既转红，又会把导出
  记录混进「阶段进展时间线」。

⇒ 留痕落 **Interaction Ledger** + 一条**独立 caller 事件**。

**观测口径**：蓝图正文、上游响应体一律不进日志（只记长度与关联键）；异常文本必经
``redact_secrets_in_text``。⭐ **业务主体绝不包进 best-effort**——上游失败要如实回错
（400 / 502 + 中性 detail），⛔ 不静默 200 空结构（115-MJ-04 的反面教材）；只有观测与
留痕另包一层 ``try/except`` 吞掉。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from adrf.views import APIView
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.logging import redact_secrets_in_text

# ⭐ MJ-03 的范围闸语义**只能有一份实现**：复制会产生可漂移的副本 ⇒ 直接 import 私有
# 符号并在此登记。``_ARTIFACT_MISSING_DETAIL`` 一并 import 是硬要求：本模块「artifact
# 不存在」的 404 必须与闸内产出的非成员 404 **逐字相同**。
from delivery.api.blueprint_review_views import (
    _ARTIFACT_MISSING_DETAIL,
    _aassert_project_scope,
    _ablueprint_project_id,
    _aload_artifact,
)

logger = structlog.get_logger(__name__)

_COMPONENT = "blueprint_export_api"

# 中性上游失败文案（⛔ 两档都不含上游 body：它可能带 token / 内部 URL / 账号信息）
_EXPORT_CONFIG_DETAIL = {"detail": "飞书导出不可用：请检查空间的导出文件夹与飞书应用凭证配置"}
_UPSTREAM_UNAVAILABLE_DETAIL = {"detail": "飞书文档服务暂时不可用，请稍后重试"}
_VERSION_MISSING_DETAIL = {"detail": "版本不存在或不属于该 artifact"}
_VERSION_INVALID_DETAIL = {"detail": "version_id 格式无效（需为 UUID）"}

# 异常原文进日志前的截断上界（脱敏之后仍截断：上游报错可能整段回显请求体）
_ERROR_TEXT_CHARS = 500

# Interaction Ledger 的入口来源标识
_LEDGER_SOURCE = "blueprint_export"


def _is_uuid(value: Any) -> bool:
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _log(event: str, request: Any, artifact_id: Any, started: float, **fields: Any) -> None:
    """端点级 caller 事件（只记标量与关联键；**蓝图正文与上游 body 都不进来**）。"""
    logger.info(
        event,
        category="caller",
        component=_COMPONENT,
        artifact_id=str(artifact_id),
        initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        **fields,
    )


# ── availability 三判据（镜像 chat 面，但 space 从 meta.project_id 反查）──────


async def _aspace_for_artifact(artifact: Any) -> Any:
    """蓝图 → 项目 → **空间**。

    ⚠️ 与 ``chat.views.FeishuExportAvailabilityView`` 的关键差异：那边从 ``?space_id=``
    取（调用方可控），这边**只从蓝图自身的 ``meta.project_id`` 反查**——范围闸认的是
    同一个 project_id，导出面必须与它同源，否则会出现「闸放行项目 A、文档写进空间 B」。
    """
    project_id = await _ablueprint_project_id(artifact)
    if not _is_uuid(project_id):
        return None
    from initiatives.models import Project

    project = await Project.objects.select_related("space").filter(id=project_id).afirst()
    return getattr(project, "space", None) if project is not None else None


async def _aexport_availability(artifact: Any) -> tuple[Any, bool, str | None]:
    """三判据 → ``(space, available, reason)``（判据链逐条镜像 chat 面）。"""
    space = await _aspace_for_artifact(artifact)
    if space is None:
        return None, False, "no_space"
    if not space.feishu_doc_folder_token:
        return space, False, "no_folder_token"
    if space.feishu_app_id and space.feishu_app_secret_encrypted:
        return space, True, None

    from agents.tools.feishu_doc_tools import _aget_system_feishu_credentials_for_doc

    credentials = await _aget_system_feishu_credentials_for_doc()
    if credentials:
        return space, True, None
    return space, False, "no_credentials"


# ── 版本装配 ────────────────────────────────────────────────────────────────


async def _aload_version(artifact_id: Any, version_id: Any = None) -> Any:
    """取要导出的版本；``version_id`` 缺省取**最新**一版。

    ⛔ **不读 ``Artifact.current_version``**（STATE 114-04 的既有纪律）；带 ``version_id``
    时**必须同时约束 ``artifact_id``**，否则可用自己有权限的 artifact 拼别人的 version。
    """
    from delivery.models import ArtifactVersion

    queryset = ArtifactVersion.objects.filter(artifact_id=artifact_id)
    if version_id:
        return await queryset.filter(id=version_id).afirst()
    return await queryset.order_by("-version_no").afirst()


# ── 上游失败分档（⛔ 如实回错，⛔ 不回显上游 body）──────────────────────────


def _classify_upstream_error(exc: BaseException) -> tuple[dict, int]:
    """飞书上游异常 → ``(中性 detail, 状态码)``。

    分档依据（``services/feishu_doc.py:27-53`` 逐类核过）：

    - ``PermissionDeniedError``（``PERMISSION_CODES``）/ ``DocumentNotFoundError``
      （``NOT_FOUND_CODES``）/ 客户端构造期的 ``ValueError``（凭证缺失）⇒ **配置类**，
      重试也不会好 ⇒ **400**；
    - ``RateLimitError``（``99991400`` / ``rate limit``）与其余 ``FeishuDocAPIError``
      ⇒ **上游不可用/限流/超时**，稍后重试可能成功 ⇒ **502**。
    """
    from services.feishu_doc import (
        DocumentNotFoundError,
        PermissionDeniedError,
        RateLimitError,
    )

    if isinstance(exc, (PermissionDeniedError, DocumentNotFoundError, ValueError)):
        return _EXPORT_CONFIG_DETAIL, status.HTTP_400_BAD_REQUEST
    if isinstance(exc, RateLimitError):
        return _UPSTREAM_UNAVAILABLE_DETAIL, status.HTTP_502_BAD_GATEWAY
    return _UPSTREAM_UNAVAILABLE_DETAIL, status.HTTP_502_BAD_GATEWAY


# ── 留痕（Interaction Ledger；⛔ 不写 content、⛔ 不进 BLUEPRINT_EVENTS）──────


async def _arecord_export_ledger(request: Any, payload: dict) -> None:
    """把一次导出写进 Interaction Ledger（best-effort，⛔ 绝不反噬业务）。

    ⭐ 留痕只在**观测层**：写失败吞掉，导出本身已经成功，不能因为记不上账就回错。
    """
    try:
        from interactions.ledger import acreate_interaction_run, arecord_event
        from interactions.models import InteractionEvent, InteractionRun

        user_id = str(getattr(request.user, "id", "") or "")
        run = await acreate_interaction_run(
            token_fingerprint=f"user:{user_id}" if user_id else "",
            source=_LEDGER_SOURCE,
            request_id=str(request.META.get("HTTP_X_REQUEST_ID", "") or ""),
            raw_request={"method": request.method, "path": request.path},
            status=InteractionRun.Status.COMPLETED,
        )
        await arecord_event(run, InteractionEvent.EventType.TOOL_RESULT, payload)
    except Exception:  # noqa: BLE001 —— 观测 best-effort，失败绝不打断主流程
        pass


# ── 1. availability（前端据它隐藏按钮）──────────────────────────────────────


class BlueprintExportAvailabilityView(APIView):
    """GET .../blueprint/export-feishu/availability/ —— ``{available, reason}``。

    ⭐ **两键逐字保持**：前端据此**隐藏导出按钮**（⛔ 不是 disabled + tooltip），键名或
    ``reason`` 取值一改，按钮就会在不可用时照样渲染、用户反复点反复失败（T-116-45）。

    三个 ``reason``：``no_space``（蓝图反查不到项目/空间）/ ``no_folder_token``（空间没配
    导出文件夹）/ ``no_credentials``（空间级与系统级飞书凭证都拿不到）。
    """

    permission_classes = [IsAuthenticated]

    async def get(self, request: Any, artifact_id: Any) -> Response:
        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        _space, available, reason = await _aexport_availability(artifact)
        _log(
            "blueprint_export_availability_read",
            request,
            artifact_id,
            started,
            available=available,
            reason=reason or "",
        )
        return Response({"available": available, "reason": reason})


# ── 2. 导出（上游失败如实回错；留痕不碰 content）─────────────────────────────


class BlueprintExportFeishuView(APIView):
    """POST .../blueprint/export-feishu/ —— 把蓝图导出为一篇飞书云文档。

    可选 body ``{"version_id": "<uuid>"}``（缺省导出最新一版）：非 UUID → **400**；
    不存在或不属于该 artifact → **中性 404**。

    ⭐ **渲染走共享 renderer 并传真实状态**：``render_blueprint_markdown`` 是导出物与
    ``ArtifactTimelineView.current_version_markdown`` 的同一个渲染器（⛔ 不在本文件就地
    拼 markdown——那会让时间线面的空壳留着、两处口径立刻分叉）。未确认的版本导出物**首行
    就带「未经确认」标注**，且没有任何参数能关掉它。

    响应四键：``document_id`` / ``url`` / ``version_no`` / ``exported_at``。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request: Any, artifact_id: Any) -> Response:
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
        from services.process_runtime.blueprint_render import (
            blueprint_status_of,
            render_blueprint_markdown,
        )

        started = time.monotonic()
        artifact = await _aload_artifact(artifact_id)
        if artifact is None:
            return Response(_ARTIFACT_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)
        denied = await _aassert_project_scope(request, artifact)
        if denied is not None:
            return denied

        payload = request.data if isinstance(request.data, dict) else {}
        version_id = str(payload.get("version_id") or "")
        if version_id and not _is_uuid(version_id):
            return Response(_VERSION_INVALID_DETAIL, status=status.HTTP_400_BAD_REQUEST)
        version = await _aload_version(artifact_id, version_id or None)
        if version is None:
            return Response(_VERSION_MISSING_DETAIL, status=status.HTTP_404_NOT_FOUND)

        space, available, reason = await _aexport_availability(artifact)
        if not available:
            # ⛔ 不 500、⛔ 不静默 200 空结构：配置没到位就是一次可解释的 400。
            _log(
                "blueprint_export_feishu_failed",
                request,
                artifact_id,
                started,
                stage="availability",
                reason=reason or "",
            )
            return Response(_EXPORT_CONFIG_DETAIL, status=status.HTTP_400_BAD_REQUEST)

        content = version.content if isinstance(version.content, dict) else {}
        status_value = blueprint_status_of(artifact)
        markdown = render_blueprint_markdown(content, blueprint_status=status_value)
        meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
        title = str(artifact.title or (meta or {}).get("title") or "未命名蓝图")

        # ⭐ 这一段的 try 是**为了分档回错**，不是为了吞掉（115-MJ-04）：业务主体绝不
        # 包进 best-effort，异常原文只经脱敏进日志、⛔ 不进响应体。
        try:
            doc_client = await create_feishu_doc_client_for_project(space)
            result = await doc_client.create_document(
                title=title,
                folder_token=space.feishu_doc_folder_token,
                content=markdown,
            )
        except Exception as exc:
            detail, status_code = _classify_upstream_error(exc)
            logger.warning(
                "blueprint_export_feishu_failed",
                category="caller",
                component=_COMPONENT,
                artifact_id=str(artifact_id),
                initiated_by_user_id=str(getattr(request.user, "id", "") or "system"),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                stage="upstream",
                status_code=status_code,
                # ⚠️ 逐字内联而不是包一层 helper：脱敏守卫（AST 扫描）认的是 error=
                # 实参里**出现脱敏函数名**，包成 helper 会让守卫失明。
                error=redact_secrets_in_text(str(exc))[:_ERROR_TEXT_CHARS],
            )
            return Response(detail, status=status_code)

        document_id = str(result.get("document_id", "") or "")
        doc_url = str(result.get("url", "") or "")
        version_no = int(getattr(version, "version_no", 0) or 0)
        exported_at = timezone.now().isoformat()

        # ⛔ 留痕不写 content：写进去会翻版本、把版本历史刷成噪声（T-116-42）。
        await _arecord_export_ledger(
            request,
            {
                "event": "blueprint_exported_to_feishu",
                "artifact_id": str(artifact_id),
                "version_no": version_no,
                "document_id": document_id,
                "url": doc_url,
                "exported_by": str(getattr(request.user, "id", "") or "system"),
                "exported_at": exported_at,
            },
        )
        _log(
            "blueprint_exported_to_feishu",
            request,
            artifact_id,
            started,
            version_no=version_no,
            document_id=document_id,
            url=doc_url,
            status_label=status_value,
            # 只记长度，⛔ 蓝图正文不进日志
            markdown_len=len(markdown),
        )
        return Response(
            {
                "document_id": document_id,
                "url": doc_url,
                "version_no": version_no,
                "exported_at": exported_at,
            }
        )
