"""Runner WebSocket token 认证中间件。"""

from urllib.parse import parse_qs

from .models import Runner, hash_token


async def _get_runner_by_token(token: str) -> Runner | None:
    try:
        return await Runner.objects.aget(token_hash=hash_token(token), is_active=True)
    except Runner.DoesNotExist:
        return None


class RunnerTokenAuthMiddleware:
    """从 query string 提取 token 认证 Runner，注入 scope["runner"]。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)

        params = parse_qs(scope.get("query_string", b"").decode())
        token = params.get("token", [None])[0]
        scope["runner"] = await _get_runner_by_token(token) if token else None
        return await self.app(scope, receive, send)
