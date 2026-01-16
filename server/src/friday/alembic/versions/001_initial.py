"""初始化数据库 schema
Revision ID: 001_initial
Revises:
Create Date: 2026-01-16
这是初始迁移，创建所有表。
对于现有数据库，需要使用 alembic stamp 001_initial 来标记。
"""
from typing import Sequence, Union
import sqlalchemy as sa
import sqlmodel
from alembic import op
# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade -> None:
 """创建所有表。"""
 # 创建 projects 表
 op.create_table(
 "projects",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("name", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("description", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column(
 "feishu_project_key", sqlmodel.sql.sqltypes.AutoString, nullable=True
 ),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.Column("updated_at", sa.DateTime, nullable=False),
 sa.Column(
 "feishu_plugin_id", sqlmodel.sql.sqltypes.AutoString, nullable=True
 ),
 sa.Column(
 "feishu_plugin_secret_encrypted",
 sqlmodel.sql.sqltypes.AutoString,
 nullable=True,
 ),
 sa.Column(
 "feishu_webhook_token", sqlmodel.sql.sqltypes.AutoString, nullable=False
 ),
 sa.PrimaryKeyConstraint("id"),
 )
 op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
 # 创建 repositories 表
 op.create_table(
 "repositories",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("name", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("git_url", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("git_platform", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("default_branch", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("claude_md_path", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("description", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.Column("updated_at", sa.DateTime, nullable=False),
 sa.PrimaryKeyConstraint("id"),
 )
 op.create_index(
 op.f("ix_repositories_name"), "repositories", ["name"], unique=False
 )
 # 创建 project_repositories 关联表
 op.create_table(
 "project_repositories",
 sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("repository_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
 sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
 sa.PrimaryKeyConstraint("project_id", "repository_id"),
 )
 # 创建 git_credentials 表
 op.create_table(
 "git_credentials",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("repository_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("auth_type", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column(
 "ssh_key_encrypted", sqlmodel.sql.sqltypes.AutoString, nullable=True
 ),
 sa.Column("encrypted_token", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("git_user_name", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("git_user_email", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.Column("updated_at", sa.DateTime, nullable=False),
 sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
 sa.PrimaryKeyConstraint("id"),
 sa.UniqueConstraint("repository_id"),
 )
 # 创建 tasks 表
 op.create_table(
 "tasks",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("repository_id", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("work_item_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("feature_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("title", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("description", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("branch_name", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("commit_sha", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("pr_url", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("plan_output", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("status", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.Column("updated_at", sa.DateTime, nullable=False),
 sa.Column("plan_started_at", sa.DateTime, nullable=True),
 sa.Column("plan_completed_at", sa.DateTime, nullable=True),
 sa.Column("execute_started_at", sa.DateTime, nullable=True),
 sa.Column("execute_completed_at", sa.DateTime, nullable=True),
 sa.Column("human_feedback", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("retry_count", sa.Integer, nullable=False),
 sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
 sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
 sa.PrimaryKeyConstraint("id"),
 )
 op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
 op.create_index(
 op.f("ix_tasks_repository_id"), "tasks", ["repository_id"], unique=False
 )
 op.create_index(
 op.f("ix_tasks_work_item_id"), "tasks", ["work_item_id"], unique=False
 )
 # 创建 webhook_logs 表
 op.create_table(
 "webhook_logs",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("event_uuid", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("project_key", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("raw_request", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("status", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
 sa.PrimaryKeyConstraint("id"),
 )
 op.create_index(
 op.f("ix_webhook_logs_created_at"), "webhook_logs", ["created_at"], unique=False
 )
 op.create_index(
 op.f("ix_webhook_logs_event_type"), "webhook_logs", ["event_type"], unique=False
 )
 op.create_index(
 op.f("ix_webhook_logs_event_uuid"), "webhook_logs", ["event_uuid"], unique=False
 )
 op.create_index(
 op.f("ix_webhook_logs_project_id"), "webhook_logs", ["project_id"], unique=False
 )
 op.create_index(
 op.f("ix_webhook_logs_project_key"),
 "webhook_logs",
 ["project_key"],
 unique=False,
 )
 op.create_index(
 op.f("ix_webhook_logs_status"), "webhook_logs", ["status"], unique=False
 )
 # 创建 work_item_logs 表
 op.create_table(
 "work_item_logs",
 sa.Column("id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("task_id", sqlmodel.sql.sqltypes.AutoString, nullable=True),
 sa.Column("work_item_id", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("work_item_type", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("project_key", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("raw_response", sqlmodel.sql.sqltypes.AutoString, nullable=False),
 sa.Column("created_at", sa.DateTime, nullable=False),
 sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
 sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
 sa.PrimaryKeyConstraint("id"),
 )
 op.create_index(
 op.f("ix_work_item_logs_created_at"),
 "work_item_logs",
 ["created_at"],
 unique=False,
 )
 op.create_index(
 op.f("ix_work_item_logs_project_id"),
 "work_item_logs",
 ["project_id"],
 unique=False,
 )
 op.create_index(
 op.f("ix_work_item_logs_project_key"),
 "work_item_logs",
 ["project_key"],
 unique=False,
 )
 op.create_index(
 op.f("ix_work_item_logs_task_id"), "work_item_logs", ["task_id"], unique=False
 )
 op.create_index(
 op.f("ix_work_item_logs_work_item_id"),
 "work_item_logs",
 ["work_item_id"],
 unique=False,
 )
def downgrade -> None:
 """删除所有表（回滚到空数据库）。"""
 # 按照依赖顺序反向删除
 op.drop_table("work_item_logs")
 op.drop_table("webhook_logs")
 op.drop_table("tasks")
 op.drop_table("git_credentials")
 op.drop_table("project_repositories")
 op.drop_table("repositories")
 op.drop_table("projects")
