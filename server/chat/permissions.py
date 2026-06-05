"""Chat API 权限控制：鉴权开关。

ChatAuthPermission 实现可配置的鉴权开关：
- 开关关闭（默认）：所有请求放行，无需认证
- 开关打开：需要 Chat Key 或 JWT 认证
"""

from rest_framework.permissions import BasePermission

from system.models import SettingKeys, SystemSetting


class ChatAuthPermission(BasePermission):
    """Chat API 鉴权开关权限。

    检查 SystemSetting 中 CHAT_AUTH_ENABLED 的值：
    - 不存在或值不是 true/1/yes → 全开放
    - 值为 true/1/yes → 需要认证（chat-key 或 JWT）

    注意：has_permission() 是同步方法（DRF BasePermission 要求），
    在 async view 中 DRF/adrf 会自动用 sync_to_async 包装。
    """

    # 认为"开启"的值集合
    _TRUTHY_VALUES = frozenset({"true", "1", "yes"})

    def has_permission(self, request, view) -> bool:
        """检查请求是否有权限访问。"""
        # 检查鉴权开关
        auth_enabled = self._is_auth_enabled()
        if not auth_enabled:
            return True

        # 开关打开：检查认证状态
        # Chat Key 认证通过
        if getattr(request, "auth", None) == "chat-key":
            return True

        # JWT 认证通过
        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            return True

        return False

    def _is_auth_enabled(self) -> bool:
        """检查鉴权开关是否开启。"""
        try:
            setting = SystemSetting.objects.get(key=SettingKeys.CHAT_AUTH_ENABLED)
        except SystemSetting.DoesNotExist:
            return False

        if not setting.value:
            return False

        return setting.value.strip().lower() in self._TRUTHY_VALUES
