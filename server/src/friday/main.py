"""Friday AI Dev Agent - FastAPI application entry point."""
from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI
from .config import get_settings
from .database import close_db, init_db
from .logging import configure_logging
from .routes import (
 logs_router,
 projects_router,
 repositories_router,
 tasks_router,
 webhook_router,
)
settings = get_settings
# 配置日志系统（必须在任何日志调用之前）
configure_logging(debug=settings.DEBUG)
logger = structlog.get_logger(__name__)
@asynccontextmanager
async def lifespan(app: FastAPI):
 """Application lifespan manager."""
 # Startup
 logger.info("Starting Friday server...")
 await init_db
 logger.info("Friday server started successfully", port=settings.PORT)
 yield
 # Shutdown
 logger.info("Shutting down Friday server...")
 await close_db
 logger.info("Friday server shutdown complete")
app = FastAPI(
 title=settings.APP_NAME,
 description="AI-powered development automation agent",
 version="0.1.0",
 lifespan=lifespan,
)
# Register routers
app.include_router(logs_router)
app.include_router(projects_router)
app.include_router(repositories_router)
app.include_router(tasks_router)
app.include_router(webhook_router)
@app.get("/health")
async def health_check:
 """Health check endpoint."""
 return {"status": "ok", "app": settings.APP_NAME}
@app.get("/")
async def root:
 """Root endpoint with API info."""
 return {
 "name": settings.APP_NAME,
 "version": "0.1.0",
 "docs": "/docs",
 }
