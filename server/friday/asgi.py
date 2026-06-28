"""
ASGI config for friday project.

It It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
import sys

# Add server directory to sys.path for multiprocessing spawn compatibility
# This is needed because uvicorn --reload uses multiprocessing on macOS
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
# Also set PYTHONPATH env var so subprocess spawns inherit it
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
