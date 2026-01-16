"""SQLModel async database configuration with automatic migration support."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
import structlog
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from .config import get_settings
# 导入所有模型以确保它们被注册到 SQLModel.metadata
from .models import ( # noqa: F401
 GitCredential,
 Project,
 ProjectRepository,
 Repository,
 Task,
 WebhookLog,
 WorkItemLog,
)
settings = get_settings
logger = structlog.get_logger
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
def get_alembic_config -> AlembicConfig:
 """获取 Alembic 配置对象。"""
 # 查找 alembic.ini 的路径
 # 在开发环境中，从 server 目录运行
 # 在 Docker 中，从 /app 目录运行
 possible_paths = [
 Path(__file__).parent.parent.parent.parent / "alembic.ini", # 开发环境
 Path("/app/alembic.ini"), # Docker 环境
 Path("alembic.ini"), # 当前目录
 ]
 alembic_ini_path = None
 for path in possible_paths:
 if path.exists:
 alembic_ini_path = path
 break
 if alembic_ini_path is None:
 raise FileNotFoundError(f"Cannot find alembic.ini in any of: {possible_paths}")
 alembic_cfg = AlembicConfig(str(alembic_ini_path))
 # 设置脚本位置（支持包内和包外两种模式）
 script_location = Path(__file__).parent / "alembic"
 alembic_cfg.set_main_option("script_location", str(script_location))
 return alembic_cfg
def run_migrations -> None:
 """同步运行数据库迁移到最新版本。
 使用 Alembic 的 command.upgrade 函数执行迁移。
 这个函数是同步的，应该在服务启动时调用。
 """
 logger.info("Running database migrations...")
 try:
 alembic_cfg = get_alembic_config
 logger.info("Alembic config loaded, starting upgrade to head...")
 command.upgrade(alembic_cfg, "head")
 logger.info("Database migrations completed successfully")
 except Exception as e:
 logger.error("Database migration failed", error=str(e))
 raise
 raise
async def check_database_exists -> bool:
 """检查数据库文件是否存在。"""
 db_path = Path(settings.SQLITE_PATH)
 return db_path.exists
async def check_alembic_version_table_exists -> bool:
 """检查 alembic_version 表是否存在。"""
 async with engine.begin as conn:
 result = await conn.execute(
 text(
 "SELECT name FROM sqlite_master "
 "WHERE type='table' AND name='alembic_version'"
 )
 )
 return result.fetchone is not None
async def stamp_head_if_needed -> None:
 """如果数据库已存在但没有 alembic 版本记录，则检查是否需要标记为 head。
 警告：自动 stamp 可能导致问题。如果旧数据库 schema 与当前模型不匹配，
 应该手动执行迁移或删除旧数据库重新创建。
 """
 db_exists = await check_database_exists
 if not db_exists:
 logger.info("Database does not exist, will be created by migrations")
 return
 version_table_exists = await check_alembic_version_table_exists
 if version_table_exists:
 logger.info("Alembic version table exists, migrations will run normally")
 return
 # 数据库存在但没有 alembic 版本表
 # 不再自动 stamp，而是警告用户可能需要手动处理
 logger.warning(
 "Existing database without alembic_version table detected. "
 "This may cause issues if the schema does not match. "
 "Consider deleting the old database or running migrations manually."
 )
 # 仍然需要创建 alembic_version 表，但标记为 base (无版本)
 # 这样迁移可以从头运行
 logger.info("Attempting to run migrations from base on existing database")
 # 不进行 stamp，让迁移自己处理
async def init_db -> None:
 """初始化数据库并运行迁移。
 这个函数在服务启动时调用，会：
 1. 确保数据目录存在
 2. 检查是否需要标记现有数据库
 3. 运行 Alembic 迁移
 """
 # 确保数据目录存在
 db_dir = Path(settings.SQLITE_PATH).parent
 db_dir.mkdir(parents=True, exist_ok=True)
 # 如果是现有数据库但没有 alembic 版本表，先标记
 await stamp_head_if_needed
 # 运行迁移（同步操作）
 run_migrations
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
