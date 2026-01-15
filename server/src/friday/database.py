"""SQLModel async database configuration."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from .config import get_settings
# Import all models to ensure they are registered with SQLModel.metadata
from .models import GitCredential, Project, Task # noqa: F401
settings = get_settings
# Create async engine
engine: AsyncEngine = create_async_engine(
 f"sqlite+aiosqlite:///{settings.SQLITE_PATH}",
 echo=settings.DEBUG,
 future=True,
)
# Async session factory
async_session_maker = async_sessionmaker(
 engine,
 class_=AsyncSession,
 expire_on_commit=False,
)
async def init_db -> None:
 """Initialize database and create all tables."""
 async with engine.begin as conn:
 await conn.run_sync(SQLModel.metadata.create_all)
async def close_db -> None:
 """Close database connections."""
 await engine.dispose
@asynccontextmanager
async def get_session -> AsyncGenerator[AsyncSession, None]:
 """Get database session as async context manager."""
 async with async_session_maker as session:
 try:
 yield session
 await session.commit
 except Exception:
 await session.rollback
 raise
async def get_db -> AsyncGenerator[AsyncSession, None]:
 """FastAPI dependency for database session."""
 async with async_session_maker as session:
 yield session
