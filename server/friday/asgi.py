"""
ASGI config for friday project.

It It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

# `server/` 置顶（导入 friday 包时已执行一次，这里显式调用是为可读性）。
# 旧写法是 `if server_dir not in sys.path`——editable 安装的 .pth 早已把它加在末尾，
# 该条件恒假 ⇒ 从不置顶，靠 uvicorn 的 cwd 恰好是 server/ 才没出事。
from friday.path_guard import SERVER_DIR, ensure_server_dir_first

ensure_server_dir_first()

# PYTHONPATH 另有其用：uvicorn --reload 在 macOS 走 multiprocessing spawn，
# 子进程不继承父进程的 sys.path，只能靠环境变量传递。
server_dir = SERVER_DIR
if os.environ.get("PYTHONPATH"):
    if server_dir not in os.environ["PYTHONPATH"]:
        os.environ["PYTHONPATH"] = f"{server_dir}:{os.environ['PYTHONPATH']}"
else:
    os.environ["PYTHONPATH"] = server_dir

from django.core.asgi import get_asgi_application  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from chat.routing import websocket_urlpatterns as chat_ws_patterns  # noqa: E402
from core.middleware import WSSEnforcementMiddleware  # noqa: E402
from initiatives.routing import websocket_urlpatterns as project_ws_patterns  # noqa: E402
from notifications.routing import websocket_urlpatterns as notification_ws_patterns  # noqa: E402
from runners.routing import websocket_urlpatterns as runner_ws_patterns  # noqa: E402
from workflows.routing import websocket_urlpatterns as workflow_ws_patterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": WSSEnforcementMiddleware(
            AuthMiddlewareStack(
                URLRouter(
                    runner_ws_patterns
                    + workflow_ws_patterns
                    + notification_ws_patterns
                    + project_ws_patterns
                    + chat_ws_patterns
                )
            )
        ),
    }
)
