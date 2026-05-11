"""仓库级权限控制：验证 URL 中的 repository_id 存在且未删除。"""
from __future__ import annotations
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView
from repositories.models import Repository
class RepositoryPermission(BasePermission):
 """校验 URL kwarg repository_id 对应的仓库存在且未被删除。
 配合 IsAuthenticated 使用，任意登录用户均可访问存在的仓库。
 未来若需要引入仓库级 ACL，在此处扩展 ownership 检查。
 """
 message = "仓库不存在或无权访问。"
 def has_permission(self, request: Request, view: APIView) -> bool:
 repository_id = view.kwargs.get("repository_id")
 if not repository_id:
 return False
 return Repository.objects.filter(id=repository_id, is_deleted=False).exists
