"""认证端点速率限制。

设计要点（防爆破而不误伤共享出口 IP 的团队）：

- ``LoginRateThrottle``：按「IP + 用户名」计数，登录成功后由视图调用 ``reset()``
  清空计数——只有针对单一账号的连续失败（爆破）会被拦截，正常登录、
  多人共享出口 IP、频繁切换账号都不受影响；
- ``LoginIPRateThrottle``：纯 IP 维度的宽松兜底，防脚本在单 IP 上批量扫描多账号；
- ``RefreshRateThrottle``：Token 刷新端点 IP 级限速。

所有 cache key 必须带 scope 前缀（``cache_format``）：早期实现直接用裸 IP 作
key，导致 login / refresh 两个桶共用同一条计数记录——页面刷新触发的 token
refresh 会消耗登录配额，用户"只是切换个用户"就被 429。

注意：``get_ident()`` 对 ``X-Forwarded-For`` 的信任由 DRF ``NUM_PROXIES``
控制（见 settings.REST_FRAMEWORK），未配置时整条 XFF 都会进 key，
攻击者伪造头即可换桶绕过限流。
"""

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class LoginRateThrottle(SimpleRateThrottle):
    """登录端点「IP + 用户名」级速率限制（只惩罚连续失败）。"""

    scope = "auth_login"

    def get_cache_key(self, request: Request, view: APIView | None) -> str | None:
        username = ""
        data = request.data
        if isinstance(data, dict):
            # 截断到 Django username 最大长度，避免超长输入撑爆 cache key
            username = str(data.get("username", ""))[:150].strip().lower()
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{self.get_ident(request)}:{username}",
        }

    def reset(self, request: Request) -> None:
        """登录成功后清空当前「IP + 用户名」的计数。

        使限流语义变为"只统计连续失败"：成功一次即证明持有正确凭证，
        之前的失败记录不再有爆破意义。
        """
        key = self.get_cache_key(request, None)
        if key:
            self.cache.delete(key)


class LoginIPRateThrottle(SimpleRateThrottle):
    """登录端点纯 IP 维度的宽松兜底限速（防单 IP 批量扫描多账号）。"""

    scope = "auth_login_ip"

    def get_cache_key(self, request: Request, view: APIView | None) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class RefreshRateThrottle(SimpleRateThrottle):
    """Token 刷新端点 IP 级速率限制。"""

    scope = "auth_refresh"

    def get_cache_key(self, request: Request, view: APIView | None) -> str | None:
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
