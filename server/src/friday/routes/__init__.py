"""Friday API routes."""
from .auth import router as auth_router
from .logs import router as logs_router
from .projects import router as projects_router
from .repositories import router as repositories_router
from .settings import router as settings_router
from .tasks import router as tasks_router
from .webhook import router as webhook_router
__all__ = [
 "auth_router",
 "logs_router",
 "projects_router",
 "repositories_router",
 "settings_router",
 "tasks_router",
 "webhook_router",
]
