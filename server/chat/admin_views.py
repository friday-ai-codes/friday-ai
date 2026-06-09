"""管理员只读会话后台 views（ADMVW-01/02/03）。

物理分离、显式管理员授权的会话管理后台后端。**全新、平行**于 Phase 8 锁定的
``/api/chat/conversations/`` 路径，绝不复用或改写其 owner gate（ISO-03 不回退）。

授权 / 认证纪律（见 09-RESEARCH §Pattern 1/2 + Pitfall 2）：
    - ``permission_classes = [IsSuperUser]``：服务端唯一可信授权点；非管理员 → 403。
    - **不覆盖** ``authentication_classes``：沿用 settings 默认
      ``[AccessTokenAuthentication, CookieJWTAuthentication]``，强制登录、拒匿名。
      **严禁**复用 chat 路径的 ``OptionalJWTAuthentication`` / ``ChatAuthPermission``
      （那是开放模式认证，会放行匿名 / X-Chat-Key）。

只读纪律（ADMVW-02，见 §Pattern 2）：
    - detail / list view **只定义 get**，fork view 只定义 post。
    - 不实现 patch / delete / send / stream —— 非法方法由 DRF 自动 405。

async 序列化纪律（Pitfall 1）：service 层已 select_related 预取关联对象，
``.data`` 一律用 ``sync_to_async`` 包裹，避免 async 上下文 SynchronousOnlyOperation。
"""

from __future__ import annotations

import uuid

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser

from .conversation_service import ConversationService
from .models import Conversation
from .serializers import (
    AdminConversationListSerializer,
    ConversationDetailSerializer,
    ConversationMessageSerializer,
)

logger = structlog.get_logger(__name__)


class AdminConversationListView(APIView):
    """管理员跨用户会话列表（只读，ADMVW-01）。

    GET /api/admin/conversations/?owner_id=&q=
    沿用默认认证类（要求登录、拒匿名）；IsSuperUser 仅做属性判定，无 ORM 触发。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request):
        """跨用户列出全部会话（含 owner + message_count）。"""
        owner_id = request.query_params.get("owner_id") or None
        # User.id 是 UUIDField：非 UUID 的 owner_id 会在 ORM 查询求值阶段抛
        # ValueError → 500。query param 没有 <uuid:...> 路由转换器兜底，故在此
        # 显式校验，非法值返回 400（清晰报错），而非让其穿透成 500（WR-01）。
        if owner_id is not None:
            try:
                owner_id = str(uuid.UUID(owner_id))
            except (ValueError, TypeError, AttributeError):
                return Response(
                    {"error": "owner_id 格式无效（需为 UUID）"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        q = request.query_params.get("q") or ""
        conversations = await ConversationService.admin_list_conversations(
            owner_id=owner_id,
            q=q,
        )
        data = await sync_to_async(
            lambda: AdminConversationListSerializer(conversations, many=True).data
        )()
        return Response(data)


class AdminConversationDetailView(APIView):
    """管理员只读会话详情 + 消息（ADMVW-01/02）。

    GET /api/admin/conversations/<uuid>/
    **只定义 get**——patch/delete/post 未实现 → DRF 自动 405（只读，ADMVW-02）。
    管理员访问不存在的会话 → 普通 404（Pitfall 3：非 403-everything）。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request, conversation_id):
        """跨用户取会话详情含消息（无 owner 过滤）。"""
        try:
            result = await ConversationService.admin_get_with_messages(
                str(conversation_id),
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        conversation = result["conversation"]
        messages = result["messages"]

        # 复用 ConversationDetailSerializer（会话标量字段）+ ConversationMessageSerializer
        # （消息嵌套）。不直接给实例赋值 conversation.messages（Django 禁止对反向 FK
        # 直接赋值），改为分别序列化后合并 —— 与既有 ConversationDetailView 同源范式。
        def _serialize() -> dict:
            data = ConversationDetailSerializer(conversation).data
            data["messages"] = ConversationMessageSerializer(
                messages, many=True
            ).data
            return data

        data = await sync_to_async(_serialize)()
        return Response(data)


class AdminConversationForkView(APIView):
    """管理员 fork-to-own（ADMVW-03）。

    POST /api/admin/conversations/<uuid>/fork/
    把任意会话整份复制为一份归属当前管理员（created_by=admin, status=DRAFT）的
    新会话，返回 {"conversation_id": <new>}。源会话不变。不存在 → 404。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request, conversation_id):
        """深拷贝会话 + 全部消息，归属当前管理员。"""
        try:
            result = await ConversationService.admin_fork_to_own(
                str(conversation_id),
                request.user,
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result, status=status.HTTP_201_CREATED)
