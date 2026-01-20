"""add_users_table
Revision ID: a1b2c3d4e5f6
Revises: ef3fc1fb8927
Create Date: 2026-01-19 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel
from passlib.context import CryptContext
# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ef3fc1fb8927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
# 密码哈希上下文
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
def upgrade -> None:
 """执行升级迁移。"""
 # 创建 users 表
 op.create_table('users',
 sa.Column('id', sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column('username', sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column('hashed_password', sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column('display_name', sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
 sa.Column('is_superuser', sa.Boolean, nullable=False, server_default='0'),
 sa.Column('created_at', sa.DateTime, nullable=False),
 sa.Column('updated_at', sa.DateTime, nullable=False),
 sa.PrimaryKeyConstraint('id')
 )
 # 创建索引
 op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
 # 插入默认管理员用户
 # 默认密码: admin123
 from uuid import uuid4
 from datetime import datetime
 admin_id = str(uuid4)
 hashed_password = pwd_context.hash("admin123")
 now = datetime.utcnow.isoformat
 op.execute(
 f"""
 INSERT INTO users (id, username, hashed_password, display_name, is_active, is_superuser, created_at, updated_at)
 VALUES ('{admin_id}', 'admin', '{hashed_password}', '管理员', 1, 1, '{now}', '{now}')
 """
 )
def downgrade -> None:
 """执行降级回滚。"""
 op.drop_index(op.f('ix_users_username'), table_name='users')
 op.drop_table('users')
