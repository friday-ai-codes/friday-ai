"""移除「最多一个 superuser」的 partial unique index（放开多超管）。

0006 曾用 partial unique index 强制全系统仅一个 is_superuser=True 账号（WR-01）。
现产品需求改为允许超级管理员在用户管理界面授予/取消他人超管身份，
因此 DROP 该索引以支持存在多个超管。

权衡说明：去掉该索引后，首启向导的并发兜底退化为仅依赖
SetupInitView._atomic_create_superuser 的应用层 ``exists()`` 检查
（仍在 transaction.atomic 内，SQLite 走 WAL 写锁、Postgres 走 READ COMMITTED）。
极端并发首启理论上可能各自建出超管，但这属首启一次性窗口，已由
SETUP-03/04 的 fail-closed 逻辑覆盖主路径。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_add_single_superuser_constraint"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS accounts_user_single_superuser;",
            reverse_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_single_superuser
            ON users (is_superuser)
            WHERE is_superuser = TRUE;
            """,
        ),
    ]
