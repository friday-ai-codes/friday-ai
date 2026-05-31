"""Settings views."""
from uuid import UUID
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from permissions.api_permissions import IsSuperUser
from .models import ProviderCredential, SettingKeys, SystemSetting
from .serializers import (
 SystemSettingCreateSerializer,
 SystemSettingSerializer,
 SystemSettingUpdateSerializer,
)
class SettingsListCreateView(APIView):
 """List and create system settings."""
 permission_classes = [IsSuperUser]
 async def get(self, request):
 settings = [s async for s in SystemSetting.objects.all]
 serializer = SystemSettingSerializer(settings, many=True)
 return Response(serializer.data)
 async def post(self, request):
 serializer = SystemSettingCreateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 key = serializer.validated_data["key"]
 if await SystemSetting.objects.filter(key=key).aexists:
 return Response(
 {"detail": f"设置 '{key}' 已存在"},
 status=status.HTTP_409_CONFLICT,
 )
 value = serializer.validated_data.get("value")
 setting = await SystemSetting.objects.acreate(
 key=key,
 value=value,
 is_encrypted=False,
 description=serializer.validated_data.get("description"),
 )
 return Response(
 SystemSettingSerializer(setting).data,
 status=status.HTTP_201_CREATED,
 )
class SettingsDetailView(APIView):
 """Get, update, and delete a system setting."""
 permission_classes = [IsSuperUser]
 async def get(self, request, key):
 try:
 setting = await SystemSetting.objects.aget(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(SystemSettingSerializer(setting).data)
 async def put(self, request, key):
 serializer = SystemSettingUpdateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 setting, created = await SystemSetting.objects.aget_or_create(key=key)
 value = serializer.validated_data.get("value")
 setting.value = value
 setting.is_encrypted = False
 if "description" in serializer.validated_data:
 setting.description = serializer.validated_data["description"]
 await setting.asave
 return Response(SystemSettingSerializer(setting).data)
 async def delete(self, request, key):
 try:
 setting = await SystemSetting.objects.aget(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 await setting.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
class FeishuIMTestView(APIView):
 """Test Feishu IM configuration by sending a test message."""
 permission_classes = [IsSuperUser]
 async def post(self, request):
 receive_id = request.data.get("receive_id") or request.data.get("user_id")
 receive_id_type = request.data.get("receive_id_type", "open_id")
 message = request.data.get("message", "这是一条测试消息，来自 Friday AI Agent 配置测试。")
 if not receive_id:
 return Response(
 {"success": False, "message": "请提供接收者 ID"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if receive_id_type not in ("open_id", "chat_id", "user_id"):
 return Response(
 {"success": False, "message": "receive_id_type 必须是 open_id、chat_id 或 user_id"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 app_id = request.data.get("app_id")
 app_secret = request.data.get("app_secret")
 if not app_id:
 try:
 setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_ID)
 app_id = setting.value
 except SystemSetting.DoesNotExist:
 pass
 if not app_secret:
 try:
 setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_SECRET)
 app_secret = setting.value
 except SystemSetting.DoesNotExist:
 pass
 if not app_id or not app_secret:
 return Response(
 {"success": False, "message": "飞书 IM 配置不完整，请填写 App ID 和 App Secret"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 from services.feishu_im import FeishuIMClient
 client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
 result = await client.send_message(
 receive_id=receive_id,
 receive_id_type=receive_id_type,
 msg_type="text",
 content={"text": message},
 )
 message_id = result.get("message_id", "")
 return Response({
 "success": True,
 "message": "测试消息发送成功",
 "message_id": message_id,
 })
 except Exception as e:
 return Response({
 "success": False,
 "message": f"发送失败: {e!s}",
 })
# ============================================================================
# Phase：ProviderCredential 健康检查端点
# ============================================================================
class ProviderCredentialTestConnectionView(APIView):
 """POST /api/providers/credentials/{credential_id}/test-connection/
 对指定 ProviderCredential 触发一次健康检查；上游 5s httpx timeout；
 同次往返原子写回 last_health_check_at/status/error 三字段；
 Ollama 路径额外写 available_models（ 协同）。
 权限：本 phase 用 IsAuthenticated；Phase 升级到
 IsSuperUserOrProjectAdmin + ProjectScopedQuerysetMixin 过滤。
 """
 permission_classes = [IsAuthenticated]
 async def post(self, request, credential_id: UUID): # type: ignore[no-untyped-def]
 from services.provider_health import health_check
 try:
 cred = await ProviderCredential.objects.aget(id=credential_id)
 except ProviderCredential.DoesNotExist:
 return Response(
 {"detail": "Credential not found."},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 可选：按指定模型测试（不传则使用 credential.default_model）
 body = request.data or {}
 override_model = body.get("model") if isinstance(body, dict) else None
 result = await health_check(cred, override_model=override_model)
 # 健康检查完成后 aupdate 已写回三字段；重新读取最新 last_health_check_at
 refreshed = await ProviderCredential.objects.aget(id=credential_id)
 return Response({
 "ok": result.ok,
 "status": result.status,
 "latency_ms": result.latency_ms,
 "error": result.error,
 "last_check_at": (
 refreshed.last_health_check_at.isoformat
 if refreshed.last_health_check_at
 else None
 ),
 # 仅 Ollama 路径非 None；其他 Provider 保持 null
 "available_models": result.available_models,
 })
# ============================================================================
# Phase / /：ProviderCredential CRUD ViewSet
# ============================================================================
import structlog
from adrf.viewsets import ModelViewSet as AsyncModelViewSet
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from identity.credential_access import (
 CredentialScopeViolation,
 validate_credential_scope,
)
from system.permissions import ProviderCredentialPermission
from system.serializers import (
 ProviderCredentialCreateSerializer,
 ProviderCredentialSerializer,
 ProviderCredentialUpdateSerializer,
 ProviderTypeMetaSerializer,
)
_viewset_logger = structlog.get_logger(__name__)
class ProviderCredentialViewSet(AsyncModelViewSet):
 """Provider 凭证 CRUD ViewSet（Phase / / ）。
 三层防御：
 - 层 1：ProviderCredentialPermission（request + object 级权限判定）
 - 层 2：get_queryset 显式过滤（scope ∪ 用户项目 + query_params）
 - 层 3：perform_acreate / perform_aupdate 内调 validate_credential_scope 服务
 端点（挂 /api/providers/credentials/）：
 - GET /api/providers/credentials/ list（支持 scope/space_id/is_active/include_inactive 过滤）
 - POST /api/providers/credentials/ create（Pydantic credential_schema 校验 + Fernet 加密）
 - GET /api/providers/credentials/{id}/ retrieve（派生 api_key_last4 + has_api_key，不回显明文）
 - PATCH /api/providers/credentials/{id}/ partial_update（config 留空 = 保持原值）
 - PUT /api/providers/credentials/{id}/ update
 - DELETE /api/providers/credentials/{id}/ destroy（硬删）
 保留 Phase 既有 ProviderCredentialTestConnectionView（test-connection 端点不动）。
 @action 扩展（toggle-active / refresh-models / types）归 Plan。
 """
 queryset = ProviderCredential.objects.all
 permission_classes = [IsAuthenticated, ProviderCredentialPermission]
 def get_serializer_class(self) -> type:
 """按 action 分派 Read / Create / Update Serializer。"""
 if self.action in ("create", "acreate"):
 return ProviderCredentialCreateSerializer
 if self.action in ("update", "partial_update", "aupdate", "apartial_update"):
 return ProviderCredentialUpdateSerializer
 return ProviderCredentialSerializer
 def get_queryset(self): # type: ignore[no-untyped-def]
 """ 层 2 queryset 过滤 + 查询参数解析。
 过滤顺序：
 1. 非 superuser 限 scope='system' ∪ 用户成员项目的 scope='project'
 2. 可选 scope=system|project 精确过滤
 3. 可选 space_id=<uuid> 精确过滤（scope=project）
 4. include_inactive=true 时保留 is_active=false；默认仅 is_active=true
 5. 显式 is_active=true|false 覆盖 include_inactive
 """
 qs = super.get_queryset
 user = self.request.user
 if not getattr(user, "is_authenticated", False):
 return qs.none
 # 非 superuser：限 system ∪ 成员项目
 if not user.is_superuser:
 from permissions.services import PermissionService
 user_project_ids = list(
 PermissionService.get_user_projects(user).values_list("id", flat=True)
 )
 qs = qs.filter(
 Q(scope="system")
 | Q(scope="project", scope_id__in=user_project_ids)
 )
 # query_params 过滤
 params = self.request.query_params
 scope = params.get("scope")
 space_id = params.get("space_id")
 # UAT 第 3 项 hotfix follow-up：
 # scope=any + space_id=<uuid> 返回 system ∪ 指定空间（chat 路径需要）。
 # 旧 scope=system / scope=project / 不传三种语义保持不变。
 if scope == "any":
 if space_id:
 qs = qs.filter(
 Q(scope="system") | Q(scope="project", scope_id=space_id)
 )
 else:
 qs = qs.filter(scope="system")
 elif scope in ("system", "project"):
 qs = qs.filter(scope=scope)
 if scope == "project" and space_id:
 qs = qs.filter(scope_id=space_id)
 elif space_id:
 # 旧行为：仅传 space_id 不传 scope → 当成 scope=project（保持兼容）
 qs = qs.filter(scope="project", scope_id=space_id)
 #：默认过滤 is_active=True；include_inactive=true 关闭
 include_inactive = params.get("include_inactive", "false").lower == "true"
 is_active_param = params.get("is_active")
 if is_active_param is not None:
 qs = qs.filter(is_active=is_active_param.lower == "true")
 elif not include_inactive:
 qs = qs.filter(is_active=True)
 return qs.order_by("-updated_at")
 async def perform_acreate(self, serializer) -> None: # type: ignore[no-untyped-def]
 """保存前做 scope 校验+ serializer.save async wrap。
 流程：
 1. 非 superuser 请求 scope='project' 凭证 → 校验用户对 target project 是否有 MEMBER+ 权限
 2. 通过后 sync_to_async(serializer.save) 入库（serializer 继承 rest_framework 不支持 asave）
 3. 结构化日志记录 provider_credential_created 事件
 """
 scope = serializer.validated_data.get("scope")
 scope_id = serializer.validated_data.get("scope_id")
 if (
 scope == "project"
 and scope_id is not None
 and not self.request.user.is_superuser
 ):
 from permissions.models import ProjectRole
 from permissions.services import PermissionService
 from projects.models import Project
 target_project = await sync_to_async(
 lambda: Project.objects.filter(id=scope_id).first
 )
 if target_project is None:
 raise ValidationError({"scope_id": "项目不存在"})
 has_access = await sync_to_async(PermissionService.has_project_access)(
 self.request.user, target_project, ProjectRole.MEMBER
 )
 if not has_access:
 raise PermissionDenied(
 "您不是该项目的 MEMBER+，无法为项目创建凭证"
 )
 await sync_to_async(serializer.save)
 _viewset_logger.info(
 "provider_credential_created",
 provider_type=serializer.validated_data.get("provider_type"),
 scope=scope,
 scope_id=str(scope_id) if scope_id else None,
 user_id=str(self.request.user.id),
 )
 async def perform_aupdate(self, serializer) -> None: # type: ignore[no-untyped-def]
 """更新前 scope 校验（若 scope 被修改）+ save + 结构化日志。
 若 PATCH body 不含 scope/scope_id 字段，说明 scope 不变，跳过 validate_credential_scope；
 若含字段，按更新后值重新校验（使用 credential_access 服务保持与节点端语义一致）。
 """
 instance = serializer.instance
 new_scope = serializer.validated_data.get("scope", instance.scope)
 new_scope_id = serializer.validated_data.get("scope_id", instance.scope_id)
 if new_scope == "project" and not self.request.user.is_superuser:
 # 只有 scope/scope_id 发生变动时才重跑 project_access 校验
 if (
 "scope" in serializer.validated_data
 or "scope_id" in serializer.validated_data
 ):
 from permissions.models import ProjectRole
 from permissions.services import PermissionService
 from projects.models import Project
 target_project = await sync_to_async(
 lambda: Project.objects.filter(id=new_scope_id).first
 )
 if target_project is None:
 raise ValidationError({"scope_id": "项目不存在"})
 has_access = await sync_to_async(
 PermissionService.has_project_access
 )(self.request.user, target_project, ProjectRole.MEMBER)
 if not has_access:
 raise PermissionDenied(
 "您不是该项目的 MEMBER+，无法迁移凭证到该项目"
 )
 # 附加 credential_access 服务校验：确保 scope/scope_id 自洽
 # 构造一个快照凭证实例（避免使用旧的 instance 字段组合）
 snapshot_scope = new_scope
 snapshot_scope_id = new_scope_id
 if snapshot_scope == "project":
 try:
 # 用已存在的 instance 做模板，临时赋值 scope/scope_id 供 validate 使用
 instance.scope = snapshot_scope
 instance.scope_id = snapshot_scope_id
 await validate_credential_scope(
 instance,
 str(snapshot_scope_id) if snapshot_scope_id else None,
 )
 except CredentialScopeViolation as exc:
 raise ValidationError({"scope_id": str(exc)}) from exc
 await sync_to_async(serializer.save)
 _viewset_logger.info(
 "provider_credential_updated",
 credential_id=str(serializer.instance.id),
 user_id=str(self.request.user.id),
 )
 async def perform_adestroy(self, instance) -> None: # type: ignore[no-untyped-def]
 """硬删除凭证 + 结构化日志。"""
 credential_id = str(instance.id)
 await sync_to_async(instance.delete)
 _viewset_logger.info(
 "provider_credential_deleted",
 credential_id=credential_id,
 user_id=str(self.request.user.id),
 )
 # ------------------------------------------------------------------
 # Phase @action 扩展： toggle + refresh-models
 # ------------------------------------------------------------------
 @action(detail=True, methods=["patch"], url_path="toggle-active")
 async def toggle_active( # type: ignore[no-untyped-def]
 self, request: Request, pk=None
 ) -> Response:
 """ 软禁用 toggle：反转 is_active 并返回新值。
 aresolve_or_error 在 _fetch_credential_by_id / _fetch_system_default_credential
 里均 filter(is_active=True)，本 action 切到 False 后下一次凭证解析自动跳过该凭证；
 不做硬删，保留配置 + available_models 等历史状态，便于随时恢复。
 """
 credential = await self.aget_object
 credential.is_active = not credential.is_active
 await sync_to_async(credential.save)(
 update_fields=["is_active", "updated_at"]
 )
 _viewset_logger.info(
 "provider_credential_toggle_active",
 credential_id=str(credential.id),
 is_active=credential.is_active,
 user_id=str(request.user.id),
 )
 return Response({"is_active": credential.is_active})
 @action(detail=True, methods=["post"], url_path="set-default")
 async def set_default( # type: ignore[no-untyped-def]
 self, request: Request, pk=None
 ) -> Response:
 """把当前凭证设为同 (scope, scope_id, provider_type) 维度的默认凭证。
 替代 name='default' 魔法约定（Quick 问题①）。service 层主动保证
 唯一：先把同组其他行 is_default 清零，再把当前行置 True；DB 端
 uniq_default_provider_per_scope_type partial unique 约束兜底竞态。
 权限：system 级写动作仅 superuser（与 Create/Update 的 校验一致）；
 project 级由 ProviderCredentialPermission 对象级权限保证。
 """
 credential = await self.aget_object
 if credential.scope == "system" and not request.user.is_superuser:
 raise PermissionDenied("仅系统管理员可设置系统级默认凭证")
 @sync_to_async
 def _set_default_atomic -> None:
 from django.db import transaction
 with transaction.atomic:
 # 清零同组其他默认凭证（含已禁用的，保证维度内唯一）
 ProviderCredential.objects.filter(
 scope=credential.scope,
 scope_id=credential.scope_id,
 provider_type=credential.provider_type,
 is_default=True,
 ).exclude(id=credential.id).update(is_default=False)
 credential.is_default = True
 credential.save(update_fields=["is_default", "updated_at"])
 await _set_default_atomic
 _viewset_logger.info(
 "provider_credential_set_default",
 credential_id=str(credential.id),
 scope=credential.scope,
 provider_type=credential.provider_type,
 user_id=str(request.user.id),
 )
 return Response({"is_default": True})
 @action(detail=True, methods=["post"], url_path="refresh-models")
 async def refresh_models( # type: ignore[no-untyped-def]
 self, request: Request, pk=None
 ) -> Response:
 """：按 provider_type 拉取模型清单 → 写回 available_models。
 fetch_models_for_credential 内部按 5 Provider 分派 httpx 调 /models 端点；
 失败时返回空 list 并把脱敏错误写入 credential.last_health_check_error
 （不更新 last_health_check_status——避免污染健康检查语义）。
 本 action 统一负责持久化 available_models + last_health_check_error。
 T- 纵深防御：在 fetch 内部 try/except 之外，view 层追加兜底脱敏，
 防止未来 fetch 重构成抛异常语义时，原始 exception message（可能含 api_key
 明文）直接冒泡到 HTTP 响应或 DB。用 redact_secrets_in_text 保证即便上游
 error 携带 sk-ant-* / sk-* / AIza* / Bearer * 等凭证也会替换为
 ***REDACTED*** 后再响应并入库（W4 修复核心）。
 """
 from common.logging import redact_secrets_in_text
 from services.provider_health import (
 ERROR_TRUNCATE_LIMIT,
 fetch_models_for_credential,
 )
 credential = await self.aget_object
 try:
 models_list = await fetch_models_for_credential(credential)
 except Exception as exc: # noqa: BLE001 —— 纵深防御兜底
 redacted = redact_secrets_in_text(str(exc))[:ERROR_TRUNCATE_LIMIT]
 credential.last_health_check_error = redacted
 await sync_to_async(credential.save)(
 update_fields=["last_health_check_error", "updated_at"],
 )
 _viewset_logger.warning(
 "provider_credential_refresh_models_failed",
 credential_id=str(credential.id),
 error_type=type(exc).__name__,
 user_id=str(request.user.id),
 )
 return Response(
 {
 "available_models": credential.available_models or,
 "error": redacted,
 },
 status=502,
 )
 credential.available_models = models_list
 await sync_to_async(credential.save)(
 update_fields=[
 "available_models",
 "last_health_check_error",
 "updated_at",
 ],
 )
 _viewset_logger.info(
 "provider_credential_refresh_models",
 credential_id=str(credential.id),
 model_count=len(models_list),
 user_id=str(request.user.id),
 )
 return Response({"available_models": models_list})
# ============================================================================
# Phase：ProviderTypesView —— 5 Provider 元信息 + 动态 JSON Schema
# ============================================================================
class ProviderTypesView(APIView):
 """GET /api/providers/types/ —— schema-driven 前端数据源。
 返回 5 Provider 元信息列表，每项含 credential_schema_json_schema 字段
 （来源：PROVIDER_REGISTRY[type].credential_schema.model_json_schema）。
 前端 ProviderCredentialForm.vue 据此动态渲染表单字段；新增 Provider 时仅需
 更新后端 PROVIDER_REGISTRY，前端无需改代码（ schema-driven）。
 权限：IsAuthenticated（T- accept 依据：types 端点是 public meta，
 不包含任何凭证数据，仅泄漏"系统支持哪些 Provider"这一非敏感事实）。
 """
 permission_classes = [IsAuthenticated]
 async def get(self, request: Request) -> Response: # type: ignore[no-untyped-def]
 from services.provider_config import PROVIDER_REGISTRY
 data: list[dict[str, object]] =
 for provider_type, meta in PROVIDER_REGISTRY.items:
 data.append({
 "provider_type": provider_type.value,
 "display_name": meta.display_name,
 "langchain_prefix": meta.langchain_prefix,
 "api_format": meta.api_format.value,
 "credential_type": meta.credential_type.value,
 "default_base_url": meta.default_base_url,
 # PROVIDER_REGISTRY 无类型级默认模型；返回空串保持前端契约稳定，
 # 前端 ChatInput 的真正 fallback 取凭证自身的 cred.default_model。
 "default_model": "",
 "supports_thinking": meta.supports_thinking,
 "supports_reasoning": meta.supports_reasoning,
 "supports_vision": meta.supports_vision,
 "supports_function_calling": meta.supports_function_calling,
 "supports_streaming": meta.supports_streaming,
 "credential_schema_json_schema": (
 meta.credential_schema.model_json_schema
 ),
 })
 serializer = ProviderTypeMetaSerializer(data, many=True)
 return Response(serializer.data)
# ============================================================================
# Phase 通用设置：SystemInfoView（版本 / 环境变量 / 镜像 / 备份）
# ============================================================================
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
class SystemInfoView(APIView):
 """GET /api/system/info/ — 系统元信息（版本、环境变量、镜像、数据库）。
 权限：仅 superuser（与 SettingsListCreateView 同级）。
 """
 permission_classes = [IsSuperUser]
 async def get(self, request) -> Response: # type: ignore[no-untyped-def]
 return Response({
 "version": self._get_version,
 "changelog_url": "/CHANGELOG.md",
 "environment": self._get_safe_env,
 "image": self._get_image_info,
 "database": self._get_database_info,
 "python_version": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}.{__import__('sys').version_info.micro}",
 "django_version": __import__('django').get_version,
 })
 def _get_version(self) -> dict[str, str]:
 """优先从 git tag 读取版本号，回退到 pyproject.toml。"""
 import subprocess
 import tomllib
 version = "unknown"
 # 1) 尝试 git describe（最近 tag）
 try:
 result = subprocess.run(
 ["git", "describe", "--tags", "--abbrev=0"],
 cwd=settings.BASE_DIR,
 capture_output=True,
 text=True,
 check=True,
 )
 version = result.stdout.strip.lstrip("v")
 except Exception:
 # 2) 回退到 pyproject.toml
 try:
 pyproject = Path(settings.BASE_DIR) / "pyproject.toml"
 with pyproject.open("rb") as f:
 data = tomllib.load(f)
 version = data.get("project", {}).get("version", "unknown")
 except Exception:
 pass
 return {"current": version}
 def _get_safe_env(self) -> dict[str, str]:
 """返回脱敏后的环境变量子集。"""
 keys = [
 "DEBUG",
 "ALLOWED_HOSTS",
 "CORS_ALLOWED_ORIGINS",
 "LANGUAGE_CODE",
 "TIME_ZONE",
 "FRIDAY_RUNNER_IMAGE",
 "DATABASE_URL",
 ]
 result: dict[str, str] = {}
 for key in keys:
 val = os.environ.get(key, "")
 if key == "DATABASE_URL" and val:
 # 脱敏：保留协议和主机，隐藏密码
 try:
 from urllib.parse import urlparse
 parsed = urlparse(val)
 if parsed.password:
 val = val.replace(f":{parsed.password}@", ":***@")
 except Exception:
 val = "***"
 result[key] = val or "(未设置)"
 return result
 def _get_image_info(self) -> dict[str, str]:
 """返回 Task Runner 执行镜像信息。"""
 # Runner 通过 FRIDAY_RUNNER_IMAGE 环境变量配置任务镜像
 # 与 runner/internal/config/config.go GetDefaultImage 语义对齐
 tag = os.environ.get("FRIDAY_RUNNER_IMAGE", "")
 return {
 "task_runner_image": tag or "friday-task:latest",
 }
 def _get_database_info(self) -> dict[str, str]:
 """返回数据库路径和大小。"""
 db_path = ""
 size_str = "unknown"
 engine = settings.DATABASES["default"].get("ENGINE", "")
 if "sqlite" in engine:
 db_path = str(settings.DATABASES["default"].get("NAME", ""))
 try:
 size = Path(db_path).stat.st_size
 size_str = f"{size / 1024 / 1024:.2f} MB"
 except Exception:
 pass
 return {"engine": engine, "path": db_path, "size": size_str}
class SystemBackupView(APIView):
 """GET /api/system/backup/ — 下载 SQLite 数据库备份。
 POST /api/system/restore/ — 上传备份文件恢复数据库。
 仅支持 SQLite；其他数据库类型返回 400。
 """
 permission_classes = [IsSuperUser]
 async def get(self, request) -> Response: # type: ignore[no-untyped-def]
 engine = settings.DATABASES["default"].get("ENGINE", "")
 if "sqlite" not in engine:
 return Response(
 {"detail": "仅 SQLite 数据库支持备份下载"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 db_path = Path(settings.DATABASES["default"].get("NAME", ""))
 if not db_path.exists:
 return Response(
 {"detail": "数据库文件不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 创建临时副本（避免锁定生产数据库）
 tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
 shutil.copy2(db_path, tmp.name)
 tmp.close
 timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
 filename = f"friday_backup_{timestamp}.db"
 def _cleanup:
 try:
 Path(tmp.name).unlink(missing_ok=True)
 except Exception:
 pass
 response = FileResponse(
 open(tmp.name, "rb"),
 as_attachment=True,
 filename=filename,
 content_type="application/octet-stream",
 )
 # 响应结束后清理临时文件
 response.close = lambda: (_cleanup, None) # type: ignore[method-assign]
 return response
 async def post(self, request) -> Response: # type: ignore[no-untyped-def]
 engine = settings.DATABASES["default"].get("ENGINE", "")
 if "sqlite" not in engine:
 return Response(
 {"detail": "仅 SQLite 数据库支持恢复"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 file_obj = request.FILES.get("file")
 if not file_obj:
 return Response(
 {"detail": "请上传备份文件"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 验证 SQLite 格式
 tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
 for chunk in file_obj.chunks:
 tmp.write(chunk)
 tmp.close
 try:
 conn = sqlite3.connect(tmp.name)
 cursor = conn.cursor
 cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
 tables = [t[0] for t in cursor.fetchall]
 conn.close
 # 校验关键表是否存在（至少要有 django_migrations）
 if "django_migrations" not in tables:
 Path(tmp.name).unlink(missing_ok=True)
 return Response(
 {"detail": "无效的数据库备份文件（缺少 django_migrations 表）"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except Exception as e:
 Path(tmp.name).unlink(missing_ok=True)
 return Response(
 {"detail": f"文件格式校验失败: {e!s}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 db_path = Path(settings.DATABASES["default"].get("NAME", ""))
 backup_old = db_path.with_suffix(f".db.bak_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
 try:
 # 先备份当前数据库
 shutil.copy2(db_path, backup_old)
 # 替换为新数据库
 shutil.copy2(tmp.name, db_path)
 except Exception as e:
 # 恢复失败则回滚
 if backup_old.exists:
 shutil.copy2(backup_old, db_path)
 Path(tmp.name).unlink(missing_ok=True)
 return Response(
 {"detail": f"恢复失败: {e!s}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
 finally:
 Path(tmp.name).unlink(missing_ok=True)
 return Response({"detail": "数据库恢复成功", "restored_tables": len(tables)})
