"""
ASGI config for friday project.
It exposes the ASGI callable as a module-level variable named ``application``.
For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application
from channels.auth import AuthMiddlewareStack # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter # noqa: E402
from runners.routing import websocket_urlpatterns as runner_ws_patterns # noqa: E402
from workflows.routing import websocket_urlpatterns as workflow_ws_patterns # noqa: E402
application = ProtocolTypeRouter(
 {
 "http": django_asgi_app,
 "websocket": AuthMiddlewareStack(
 URLRouter(runner_ws_patterns + workflow_ws_patterns)
 ),
 }
)
