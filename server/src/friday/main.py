"""Friday AI Dev Agent - FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import get_settings
from .database import close_db, init_db
from .routes import projects_router, tasks_router, webhook_router
settings = get_settings
@asynccontextmanager
async def lifespan(app: FastAPI):
 """Application lifespan manager."""
 # Startup
 await init_db
 yield
 # Shutdown
 await close_db
app = FastAPI(
 title=settings.APP_NAME,
 description="AI-powered development automation agent",
 version="0.1.0",
 lifespan=lifespan,
)
# Register routers
app.include_router(projects_router)
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
