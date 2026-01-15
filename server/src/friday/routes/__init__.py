"""Friday API routes."""
from .logs import router as logs_router
from .projects import router as projects_router
from .tasks import router as tasks_router
from .webhook import router as webhook_router
__all__ = ["logs_router", "projects_router", "tasks_router", "webhook_router"]
