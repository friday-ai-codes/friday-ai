"""Accounts permissions: 可复用权限类。"""

from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

User = get_user_model()


class SetupNotInitialized(BasePermission):
    """Fail-closed 门禁：存在任意 superuser 即拒绝（403）。

    供 SetupInitView 与 Phase 2 管理员创建接口共用，
    保证单一门禁来源，防止向导被用于重置/接管已有实例。

    注意：adrf 异步视图中 DRF 依然同步调用 has_permission，
    ORM 查询在此处不需要 sync_to_async 包装。
    """

    message = "系统已初始化，初始化接口已关闭"

    def has_permission(self, request, view) -> bool:
        # adrf 异步视图中 DRF permission check 仍同步调用，此处 ORM 查询安全
        return not User.objects.filter(is_superuser=True).exists()
