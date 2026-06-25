"""Provider 凭证 DRF 权限类（implementation contract 层 1）。

contract 双层防御的 request / object 级权限：
- 层 1（本模块）：`has_permission` 拒绝未认证，`has_object_permission` 按 scope 与 HTTP method
  分派 superuser / system 读 / project 读写判定
- 层 2（ViewSet.get_queryset）：queryset 显式过滤 scope ∪ 成员项目，防止列举泄漏"凭证存在"事实
- 层 3（ViewSet.perform_acreate 等）：`validate_credential_scope` 调用，防跨项目写越权

类比范本：`server/workflows/api/permissions.py::WorkflowPermission` work item
差异点：ProviderCredential 非 FK 到 Space（model work item 刻意用 UUIDField），
scope='project' 分支需通过 `obj.scope_id` 加载 Space 再走 PermissionService。
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from permissions.models import SpaceRole
from permissions.services import PermissionService
from system.models import ProviderCredential

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class ProviderCredentialPermission(BasePermission):
    """Provider 凭证 request + object 级权限判定。

    权限矩阵（contract）：
    - 未认证 → False（has_permission 拦截）
    - superuser → 任意操作 True
    - scope='system' + GET/HEAD/OPTIONS → 所有认证用户 True（便于工作流节点 Provider 下拉展示）
    - scope='system' + 写操作 → 仅 superuser True（普通用户由此分支的 False 兜底）
    - scope='project' → 通过 obj.scope_id 加载 Space，按 HTTP method 分 VIEWER/MEMBER 判定
    - 其他 scope 值（未知数据） → False 防御
    """

    message = "您没有权限访问此凭证"

    def has_permission(self, request: Request, view: APIView) -> bool:
        """request 级：仅要求认证；list / create 的数据过滤由 ViewSet.get_queryset 负责。"""
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self, request: Request, view: APIView, obj: ProviderCredential
    ) -> bool:
        """object 级：按 scope + HTTP method 分派到 PermissionService。"""
        user = request.user

        # superuser 早返：覆盖 system/project 所有读写
        if user.is_superuser:
            return True

        if obj.scope == "system":
            # 系统级：所有认证用户可读，写操作仅 superuser（上面早返已处理）
            return request.method in _READ_METHODS

        if obj.scope == "project":
            # project 级：从 scope_id 加载 Space；不在顶层 import Space 避免循环依赖
            from projects.models import Space

            if obj.scope_id is None:
                # 数据不一致：project 级凭证缺 scope_id，按"不可访问"处理
                return False

            project = Space.objects.filter(id=obj.scope_id).first()
            if project is None:
                # 数据不一致或项目已删除；按"不存在"处理，DRF 会转 404
                return False

            if request.method in _READ_METHODS:
                return PermissionService.has_project_access(
                    user, project, SpaceRole.VIEWER
                )
            if request.method in _WRITE_METHODS:
                return PermissionService.has_project_access(
                    user, project, SpaceRole.MEMBER
                )

        # 未知 scope 值防御：不通过
        return False
