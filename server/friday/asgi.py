"""
ASGI config for friday project.
It exposes the ASGI callable as a module-level variable named ``application``.
For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""
import os
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from workflows import routing
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application
application = ProtocolTypeRouter(
 {
 "http": django_asgi_app,
 "websocket": AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns)),
 }
)
