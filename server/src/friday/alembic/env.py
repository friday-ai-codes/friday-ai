"""Alembic 迁移环境配置。
支持同步模式运行迁移（SQLite 需要同步模式）。
"""
from logging.config import fileConfig
from alembic import context
from friday.config import get_settings
# 导入所有模型以确保它们被注册到 SQLModel.metadata
from friday.models import ( # noqa: F401
 GitCredential,
 Project,
 ProjectRepository,
 Repository,
 Task,
 WebhookLog,
 WorkItemLog,
)
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel
# Alembic Config 对象
config = context.config
# 配置日志
if config.config_file_name is not None:
 fileConfig(config.config_file_name)
# 获取应用配置
settings = get_settings
# 设置 target_metadata 为 SQLModel 的 metadata
target_metadata = SQLModel.metadata
# 数据库 URL（使用同步驱动）
# SQLite 不支持 aiosqlite 在 Alembic 中运行，需要用同步驱动
database_url = f"sqlite:///{settings.SQLITE_PATH}"
def run_migrations_offline -> None:
 """以 'offline' 模式运行迁移。
 在这种模式下，只生成 SQL 语句，不需要实际连接数据库。
 """
 context.configure(
 url=database_url,
 target_metadata=target_metadata,
 literal_binds=True,
 dialect_opts={"paramstyle": "named"},
 # 启用批量迁移（SQLite 需要）
 render_as_batch=True,
 )
 with context.begin_transaction:
 context.run_migrations
def run_migrations_online -> None:
 """以 'online' 模式运行迁移。
 使用同步引擎连接数据库并执行迁移。
 """
 connectable = create_engine(
 database_url,
 poolclass=pool.NullPool,
 )
 with connectable.connect as connection:
 context.configure(
 connection=connection,
 target_metadata=target_metadata,
 # 启用批量迁移（SQLite 不支持 ALTER TABLE，需要用批量模式）
 render_as_batch=True,
 )
 with context.begin_transaction:
 context.run_migrations
if context.is_offline_mode:
 run_migrations_offline
else:
 run_migrations_online
