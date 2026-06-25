"""Spaces app views."""

from __future__ import annotations

import structlog
from adrf.views import APIView
from adrf.viewsets import ModelViewSet
from asgiref.sync import sync_to_async
from django.db.models import Count, Prefetch
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from common.encryption import encrypt_value
from permissions.api_permissions import IsProjectAdmin, IsSuperUser
from permissions.models import ProjectMembership, ProjectRole
from permissions.services import PermissionService
from repositories.models import AuthType, GitCredential, Repository

from .models import (
    Project,
    ProjectRepository,
    generate_webhook_token,
)
from .serializers import (
    FeishuConfigCreateSerializer,
    FeishuConfigSerializer,
    FeishuIMConfigCreateSerializer,
    FeishuIMConfigSerializer,
    FeishuIMTestSerializer,
    GitCredentialSerializer,
    RepositoryCreateSerializer,
    RepositorySerializer,
    RepositoryWithSpacesSerializer,
    SpaceCreateSerializer,
    SpaceRepositoryCreateSerializer,
    SpaceRepositorySerializer,
    SpaceRepositoryUpdateSerializer,
    SpaceSerializer,
    SpaceUpdateSerializer,
    WebhookTokenSerializer,
    WebhookTokenUpdateSerializer,
)

logger = structlog.get_logger(__name__)


class SpaceViewSet(ModelViewSet):
    """ViewSet for Space CRUD operations."""

    queryset = (
        Project.objects.prefetch_related(
            Prefetch(
                "repositories",
                queryset=Repository.objects.filter(is_deleted=False).select_related("credential"),
            ),
            Prefetch(
                "memberships",
                queryset=ProjectMembership.objects.filter(
                    role=ProjectRole.ADMIN
                ).select_related("user"),
                to_attr="admin_memberships",
            ),
        )
        .annotate(execution_count=Count("workflow_executions", distinct=True))
        .all()
    )
    serializer_class = SpaceSerializer

    def get_queryset(self):
        """按用户 membership 过滤空间列表。superuser 看所有。"""
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return qs.none()

        # superuser 看所有
        if user.is_superuser:
            return qs

        # 普通用户按 membership 过滤
        return qs.filter(memberships__user=user).distinct()

    def get_permissions(self):
        """空间增删 → 系统管理员；改 → 空间管理员；其余按默认（成员可见性）。

        - create / destroy：``IsSuperUser``（新建/删除空间是平台级操作，#10）。
        - update / partial_update：``IsProjectAdmin``（object-level，空间管理员可改，
          aget_object 触发 check_object_permissions，#11）。
        - 其余（list/retrieve/config @actions）：默认权限；config @actions 内部已自校验 admin。
        """
        if self.action in ("create", "destroy"):
            return [IsSuperUser()]
        if self.action in ("update", "partial_update"):
            return [IsProjectAdmin()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "create":
            return SpaceCreateSerializer
        if self.action in ["update", "partial_update"]:
            return SpaceUpdateSerializer
        return SpaceSerializer

    async def acreate(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        # KEEP: SpaceCreateSerializer 含 UniqueValidator (feishu_project_key unique=True)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        project = await Project.objects.acreate(**serializer.validated_data)
        # 创建空间后自动为创建者添加 admin membership
        await ProjectMembership.objects.acreate(
            user=request.user,
            project=project,
            role=ProjectRole.ADMIN,
        )
        # KEEP: SpaceSerializer.get_repositories 触发 repositories.filter() DB 查询
        data = await sync_to_async(lambda: SpaceSerializer(project).data)()
        return Response(data, status=status.HTTP_201_CREATED)

    async def perform_aupdate(self, serializer):
        # KEEP: SpaceSerializer 继承自 rest_framework.serializers，不支持 asave()
        await sync_to_async(serializer.save)()

    # === Repository association ===

    @action(detail=True, methods=["get"], url_path="repositories")
    async def list_repositories(self, request, pk=None):
        """List repositories associated with the space."""
        project = await self.aget_object()
        repositories = project.repositories.filter(is_deleted=False).select_related("credential")
        serializer = RepositorySerializer([r async for r in repositories], many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path=r"repositories/(?P<repository_id>[^/.]+)")
    async def link_repository(self, request, pk=None, repository_id=None):
        """Link a repository to the space."""
        project = await self.aget_object()
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        link, created = await ProjectRepository.objects.aget_or_create(
            project=project,
            repository=repository,
        )

        if not created:
            return Response({"message": "Already linked"})

        # 审计：仓库关联空间
        await AuditService.aemit(
            action=taxonomy.ACTION_REPOSITORY_PERMISSION_CHANGED,
            actor=request.user,
            target_type="project_repository",
            target_id=link.id,
            target_repr=f"{repository.name} @ {project.name}",
            after={"repo_id": str(repository.id), "project_id": str(project.id)},
            metadata={"op": "linked"},
            source="api",
        )
        return Response({"message": "Linked successfully"}, status=status.HTTP_201_CREATED)

    @link_repository.mapping.delete
    async def unlink_repository(self, request, pk=None, repository_id=None):
        """Unlink a repository from the space."""
        project = await self.aget_object()
        link = await aget_object_or_404(
            ProjectRepository,
            project=project,
            repository_id=repository_id,
        )
        link_id = link.id
        snapshot = {"repo_id": str(link.repository_id), "project_id": str(link.project_id)}
        await link.adelete()

        # 审计：仓库解绑空间（删前快照）
        await AuditService.aemit(
            action=taxonomy.ACTION_REPOSITORY_PERMISSION_CHANGED,
            actor=request.user,
            target_type="project_repository",
            target_id=link_id,
            target_repr=f"repo:{repository_id} @ {project.name}",
            before=snapshot,
            metadata={"op": "unlinked"},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # === Feishu configuration ===

    @action(detail=True, methods=["get", "put", "delete"], url_path="feishu-config")
    async def feishu_config(self, request, pk=None):
        """Manage Feishu configuration."""
        project = await self.aget_object()

        # 写操作需要 admin+ 权限
        if request.method != "GET":
            if not request.user.is_superuser and not PermissionService.has_project_access(
                request.user, project, ProjectRole.ADMIN
            ):
                return Response(
                    {"detail": "仅空间管理员可修改配置"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        if request.method == "GET":
            return Response(FeishuConfigSerializer(project).data)

        if request.method == "PUT":
            serializer = FeishuConfigCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            project.feishu_plugin_id = serializer.validated_data["plugin_id"]
            project.feishu_plugin_secret_encrypted = encrypt_value(
                serializer.validated_data["plugin_secret"]
            )
            project.feishu_user_key = serializer.validated_data.get("user_key", "")
            await project.asave()

            # 审计：空间飞书插件配置变更——仅记字段名集合 + has_secret，绝不记 secret 值
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
                actor=request.user,
                target_type="project",
                target_id=project.id,
                target_repr=project.name,
                after={
                    "changed": ["feishu_plugin_id", "feishu_plugin_secret", "feishu_user_key"],
                    "redacted": True,
                },
                metadata={"config_subtype": "feishu_plugin"},
                source="api",
            )

            return Response(FeishuConfigSerializer(project).data)

        # DELETE
        project.feishu_plugin_id = None
        project.feishu_plugin_secret_encrypted = None
        project.feishu_user_key = None
        await project.asave()

        # 审计：空间飞书插件配置清空
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
            actor=request.user,
            target_type="project",
            target_id=project.id,
            target_repr=project.name,
            before={
                "changed": ["feishu_plugin_id", "feishu_plugin_secret", "feishu_user_key"],
                "redacted": True,
            },
            metadata={"config_subtype": "feishu_plugin", "op": "cleared"},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="feishu-config/test")
    async def test_feishu_config(self, request, pk=None):
        """Test Feishu configuration."""
        project = await self.aget_object()

        # Check if configured
        if not project.has_feishu_config():
            return Response(
                {
                    "success": False,
                    "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
                    "plugin_token_valid": False,
                    "project_accessible": False,
                }
            )

        # 获取测试配置（如果提供）
        test_plugin_id = request.data.get("plugin_id")
        test_plugin_secret = request.data.get("plugin_secret")
        test_user_key = request.data.get("user_key")

        # 使用传入的临时配置或已保存的配置
        plugin_id = test_plugin_id or project.feishu_plugin_id
        plugin_secret = None
        if test_plugin_secret:
            plugin_secret = test_plugin_secret
        elif project.feishu_plugin_secret_encrypted:
            from common.encryption import decrypt_value

            plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)

        user_key = test_user_key or project.feishu_user_key

        if not plugin_id or not plugin_secret:
            return Response(
                {
                    "success": False,
                    "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
                    "plugin_token_valid": False,
                    "project_accessible": False,
                }
            )

        # 执行实际的飞书 API 测试
        try:
            from feishu.client import FeishuClient

            client = FeishuClient(
                plugin_id=plugin_id,
                plugin_secret=plugin_secret,
                project_key=project.feishu_project_key,
                user_key=user_key,
            )

            test_result = await client.test_connection(project.feishu_project_key)

            return Response(
                {
                    "success": test_result["success"],
                    "message": test_result["message"],
                    "plugin_token_valid": test_result["plugin_token_valid"],
                    "project_accessible": test_result["project_accessible"],
                }
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"测试失败: {str(e)}",
                    "plugin_token_valid": False,
                    "project_accessible": False,
                }
            )

    @action(detail=True, methods=["post"], url_path="refresh-webhook-token")
    async def refresh_webhook_token(self, request, pk=None):
        """Refresh webhook token."""
        project = await self.aget_object()
        # admin+ 权限
        if not request.user.is_superuser and not PermissionService.has_project_access(
            request.user, project, ProjectRole.ADMIN
        ):
            return Response(
                {"detail": "仅空间管理员可刷新 webhook token"},
                status=status.HTTP_403_FORBIDDEN,
            )
        project.feishu_webhook_token = generate_webhook_token()
        await project.asave()

        # 审计：webhook token 刷新——仅记字段名 + has_secret，绝不记 token 值
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
            actor=request.user,
            target_type="project",
            target_id=project.id,
            target_repr=project.name,
            after={"changed": ["feishu_webhook_token"], "redacted": True},
            metadata={"config_subtype": "webhook_token", "op": "refreshed"},
            source="api",
        )
        return Response(
            WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
        )

    @action(detail=True, methods=["put"], url_path="webhook-token")
    async def update_webhook_token(self, request, pk=None):
        """Update webhook token with custom value."""
        project = await self.aget_object()
        # admin+ 权限
        if not request.user.is_superuser and not PermissionService.has_project_access(
            request.user, project, ProjectRole.ADMIN
        ):
            return Response(
                {"detail": "仅空间管理员可修改 webhook token"},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = WebhookTokenUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        if len(token) > 32:
            return Response(
                {"detail": "Token 长度不能超过 32 个字符"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(token) == 0:
            return Response(
                {"detail": "Token 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        project.feishu_webhook_token = token
        await project.asave()

        # 审计：webhook token 自定义更新——仅记字段名 + has_secret，绝不记 token 值
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
            actor=request.user,
            target_type="project",
            target_id=project.id,
            target_repr=project.name,
            after={"changed": ["feishu_webhook_token"], "redacted": True},
            metadata={"config_subtype": "webhook_token", "op": "updated"},
            source="api",
        )
        return Response(
            WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
        )

    # implementation（contract）：claude_config @action 整体硬删。
    # 替代：implementation ProviderCredential viewset（/api/system/provider-credentials/）
    # 及空间级 scope 凭证 API。调用 /api/spaces/<id>/claude-config/ 应返回 404。

    # === Feishu IM App configuration ===

    @action(detail=True, methods=["get", "put", "delete"], url_path="feishu-im-config")
    async def feishu_im_config(self, request, pk=None):
        """Manage Feishu IM App configuration."""
        project = await self.aget_object()

        # 写操作需要 admin+ 权限
        if request.method != "GET":
            if not request.user.is_superuser and not PermissionService.has_project_access(
                request.user, project, ProjectRole.ADMIN
            ):
                return Response(
                    {"detail": "仅空间管理员可修改配置"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        if request.method == "GET":
            return Response(FeishuIMConfigSerializer(project).data)

        if request.method == "PUT":
            serializer = FeishuIMConfigCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            project.feishu_app_id = serializer.validated_data["app_id"]
            project.feishu_app_secret_encrypted = encrypt_value(
                serializer.validated_data["app_secret"]
            )
            await project.asave()

            # 审计：空间飞书 IM 配置变更——仅记字段名 + has_secret，绝不记 app_secret 值
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
                actor=request.user,
                target_type="project",
                target_id=project.id,
                target_repr=project.name,
                after={"changed": ["feishu_app_id", "feishu_app_secret"], "redacted": True},
                metadata={"config_subtype": "feishu_im"},
                source="api",
            )

            return Response(FeishuIMConfigSerializer(project).data)

        # DELETE
        project.feishu_app_id = None
        project.feishu_app_secret_encrypted = None
        await project.asave()

        # 审计：空间飞书 IM 配置清空
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
            actor=request.user,
            target_type="project",
            target_id=project.id,
            target_repr=project.name,
            before={"changed": ["feishu_app_id", "feishu_app_secret"], "redacted": True},
            metadata={"config_subtype": "feishu_im", "op": "cleared"},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="feishu-im-config/test")
    async def test_feishu_im_config(self, request, pk=None):
        """Test Feishu IM configuration by sending a test message."""
        project = await self.aget_object()

        serializer = FeishuIMTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data["user_id"]
        message = serializer.validated_data["message"]

        # 优先使用请求中的临时配置，否则使用已保存的配置
        app_id = request.data.get("app_id") or project.feishu_app_id
        app_secret = request.data.get("app_secret")
        if not app_secret and project.feishu_app_secret_encrypted:
            from common.encryption import decrypt_value

            app_secret = decrypt_value(project.feishu_app_secret_encrypted)

        if not app_id or not app_secret:
            return Response(
                {
                    "success": False,
                    "message": "飞书 IM 配置不完整，请填写 App ID 和 App Secret",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 发送测试消息
        try:
            from services.feishu_im import FeishuIMClient

            client = FeishuIMClient(app_id=app_id, app_secret=app_secret)

            result = await client.send_message(
                receive_id=user_id,
                receive_id_type="open_id",
                msg_type="text",
                content={"text": message},
            )
            message_id = result.get("message_id", "")

            return Response(
                {
                    "success": True,
                    "message": "测试消息发送成功",
                    "message_id": message_id,
                }
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"发送失败: {str(e)}",
                }
            )

    # === Feishu Doc Export configuration ===

    @action(detail=True, methods=["get", "put"], url_path="feishu-doc-config")
    async def feishu_doc_config(self, request, pk=None):
        """管理飞书文档导出配置。"""
        project = await self.aget_object()

        # 写操作需要 admin+ 权限
        if request.method != "GET":
            if not request.user.is_superuser and not PermissionService.has_project_access(
                request.user, project, ProjectRole.ADMIN
            ):
                return Response(
                    {"detail": "仅空间管理员可修改配置"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        if request.method == "GET":
            return Response(
                {
                    "feishu_doc_folder_token": project.feishu_doc_folder_token,
                }
            )

        # PUT
        folder_token = request.data.get("feishu_doc_folder_token", "")
        if len(folder_token) > 200:
            return Response(
                {"detail": "folder_token 长度不能超过 200 个字符"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project.feishu_doc_folder_token = folder_token
        await project.asave(update_fields=["feishu_doc_folder_token", "updated_at"])

        # 审计：空间飞书文档导出配置变更（folder_token 非密钥，记字段名集合）
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_CONFIG_CHANGED,
            actor=request.user,
            target_type="project",
            target_id=project.id,
            target_repr=project.name,
            after={"changed": ["feishu_doc_folder_token"], "redacted": False},
            metadata={"config_subtype": "feishu_doc"},
            source="api",
        )
        return Response(
            {
                "feishu_doc_folder_token": project.feishu_doc_folder_token,
            }
        )


class RepositoryViewSet(ModelViewSet):
    """ViewSet for Repository CRUD operations."""

    queryset = (
        Repository.objects.filter(is_deleted=False)
        .select_related("credential")
        .prefetch_related("projects")
    )
    serializer_class = RepositorySerializer

    def get_serializer_class(self):
        if self.action == "create":
            return RepositoryCreateSerializer
        if self.action == "retrieve":
            return RepositoryWithSpacesSerializer
        return RepositorySerializer

    async def acreate(self, request, *args, **kwargs):
        serializer = RepositoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        access_token = data.pop("access_token")
        git_user_name = data.pop("git_user_name", "Friday Codes AI Agent")
        git_user_email = data.pop("git_user_email", "ai@friday.codes")

        if not access_token.strip():
            return Response(
                {"detail": "Access Token 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create repository
        repository = await Repository.objects.acreate(**data)

        # Create credential
        await GitCredential.objects.acreate(
            repository=repository,
            auth_type=AuthType.ACCESS_TOKEN,
            encrypted_token=encrypt_value(access_token),
            git_user_name=git_user_name,
            git_user_email=git_user_email,
        )

        # KEEP: RepositorySerializer.get_has_credential 触发 credential FK 访问
        resp_data = await sync_to_async(lambda: RepositorySerializer(repository).data)()
        return Response(resp_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "delete"], url_path="credential")
    async def credential(self, request, pk=None):
        """Get or delete credential for repository."""
        repository = await self.aget_object()

        if request.method == "GET":
            # 凭证不存在时返回 null 而不是 404
            credential = await GitCredential.objects.filter(repository=repository).afirst()
            if credential:
                return Response(GitCredentialSerializer(credential).data)
            return Response(None)

        elif request.method == "DELETE":
            credential = await GitCredential.objects.filter(repository=repository).afirst()
            if credential:
                await credential.adelete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


class SetAccessTokenView(APIView):
    """View for setting or updating access token.

    支持创建新凭证或更新已有凭证。
    """

    async def post(self, request, repository_id):
        repository = await aget_object_or_404(Repository, id=repository_id, is_deleted=False)

        token = request.data.get("token")
        if not token:
            return Response(
                {"detail": "Token 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        git_user_name = request.data.get("git_user_name", "Friday Codes AI Agent")
        git_user_email = request.data.get("git_user_email", "ai@friday.codes")

        # 检查凭证是否已存在，存在则更新，不存在则创建
        existing_credential = await GitCredential.objects.filter(repository=repository).afirst()

        if existing_credential:
            # 更新现有凭证
            existing_credential.auth_type = AuthType.ACCESS_TOKEN
            existing_credential.encrypted_token = encrypt_value(token)
            existing_credential.git_user_name = git_user_name
            existing_credential.git_user_email = git_user_email
            await existing_credential.asave()
            return Response(GitCredentialSerializer(existing_credential).data)
        else:
            # 创建新凭证
            credential = await GitCredential.objects.acreate(
                repository=repository,
                auth_type=AuthType.ACCESS_TOKEN,
                encrypted_token=encrypt_value(token),
                git_user_name=git_user_name,
                git_user_email=git_user_email,
            )
            return Response(
                GitCredentialSerializer(credential).data, status=status.HTTP_201_CREATED
            )


class SpaceRepositoryListCreateView(APIView):
    """空间仓库关联：列表（GET）和批量关联（POST）。

    GET  /api/spaces/{space_id}/repositories/ — viewer+ 可查看
    POST /api/spaces/{space_id}/repositories/ — admin+ 可创建
    """

    async def get(self, request: object, space_id: str) -> Response:
        """返回空间关联的仓库列表。"""
        project = await aget_object_or_404(Project, id=space_id)

        # 权限：viewer+ 可查看
        has_access = await sync_to_async(PermissionService.has_project_access)(
            request.user,
            project,
            ProjectRole.VIEWER,
        )
        if not has_access:
            return Response(
                {"detail": "无权访问此空间"},
                status=status.HTTP_403_FORBIDDEN,
            )

        links = ProjectRepository.objects.filter(
            project=project,
        ).select_related("repository")
        data = await sync_to_async(
            lambda: SpaceRepositorySerializer([link for link in links], many=True).data
        )()
        return Response(data)

    async def post(self, request: object, space_id: str) -> Response:
        """批量关联仓库到空间。"""
        project = await aget_object_or_404(Project, id=space_id)

        # 权限：admin+ 可创建
        has_access = await sync_to_async(PermissionService.has_project_access)(
            request.user,
            project,
            ProjectRole.ADMIN,
        )
        if not has_access:
            return Response(
                {"detail": "仅空间管理员可管理仓库关联"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SpaceRepositoryCreateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        repository_ids: list[str] = serializer.validated_data["repository_ids"]
        created: list[dict[str, object]] = []
        skipped: list[str] = []

        for repo_id in repository_ids:
            repo = await Repository.objects.filter(
                id=repo_id,
                is_deleted=False,
            ).afirst()
            if repo is None:
                logger.warning("repo_not_found_skip", repo_id=str(repo_id))
                continue

            link, was_created = await ProjectRepository.objects.aget_or_create(
                project=project,
                repository=repo,
            )
            if was_created:
                data = await sync_to_async(
                    lambda l=link: SpaceRepositorySerializer(l).data  # noqa: E741
                )()
                created.append(data)
                # 审计：批量关联中新建的每个仓库关联
                await AuditService.aemit(
                    action=taxonomy.ACTION_REPOSITORY_PERMISSION_CHANGED,
                    actor=request.user,
                    target_type="project_repository",
                    target_id=link.id,
                    target_repr=f"{repo.name} @ {project.name}",
                    after={"repo_id": str(repo.id), "project_id": str(project.id)},
                    metadata={"op": "linked"},
                    source="api",
                )
            else:
                skipped.append(str(repo_id))

        logger.info(
            "space_repos_linked",
            space_id=str(space_id),
            created=len(created),
            skipped=len(skipped),
        )
        return Response(
            {"created": created, "skipped": skipped},
            status=status.HTTP_201_CREATED,
        )


class SpaceRepositoryDetailView(APIView):
    """空间仓库关联：更新权限（PATCH）和移除关联（DELETE）。

    PATCH  /api/spaces/{space_id}/repositories/{pk}/ — admin+ 可修改
    DELETE /api/spaces/{space_id}/repositories/{pk}/ — admin+ 可删除
    """

    async def _check_admin(self, request: object, project: Project) -> Response | None:
        """检查 admin 权限，无权返回 403 Response，有权返回 None。"""
        has_access = await sync_to_async(PermissionService.has_project_access)(
            request.user,
            project,
            ProjectRole.ADMIN,
        )
        if not has_access:
            return Response(
                {"detail": "仅空间管理员可管理仓库关联"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    async def patch(self, request: object, space_id: str, pk: str) -> Response:
        """更新关联的权限级别。"""
        project = await aget_object_or_404(Project, id=space_id)
        denied = await self._check_admin(request, project)
        if denied:
            return denied

        link = await aget_object_or_404(ProjectRepository, pk=pk, project=project)
        serializer = SpaceRepositoryUpdateSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        old_level = link.permission_level
        link.permission_level = serializer.validated_data["permission_level"]
        await link.asave(update_fields=["permission_level"])

        # 审计：仓库权限级别变更，仅在级别真正变化时 emit（值未变不记，SC-4）
        if old_level != link.permission_level:
            await AuditService.aemit(
                action=taxonomy.ACTION_REPOSITORY_PERMISSION_CHANGED,
                actor=request.user,
                target_type="project_repository",
                target_id=link.id,
                target_repr=f"repo:{link.repository_id} @ {project.name}",
                before={"permission_level": old_level},
                after={"permission_level": link.permission_level},
                source="api",
            )

        data = await sync_to_async(lambda: SpaceRepositorySerializer(link).data)()
        return Response(data)

    async def delete(self, request: object, space_id: str, pk: str) -> Response:
        """移除仓库关联。"""
        project = await aget_object_or_404(Project, id=space_id)
        denied = await self._check_admin(request, project)
        if denied:
            return denied

        link = await aget_object_or_404(ProjectRepository, pk=pk, project=project)
        link_id = link.id
        snapshot = {"repo_id": str(link.repository_id), "project_id": str(link.project_id)}
        await link.adelete()

        logger.info(
            "space_repo_unlinked",
            space_id=str(space_id),
            link_id=str(pk),
        )

        # 审计：移除仓库关联（删前快照）
        await AuditService.aemit(
            action=taxonomy.ACTION_REPOSITORY_PERMISSION_CHANGED,
            actor=request.user,
            target_type="project_repository",
            target_id=link_id,
            target_repr=f"repo:{snapshot['repo_id']} @ {project.name}",
            before=snapshot,
            metadata={"op": "unlinked"},
            source="api",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
