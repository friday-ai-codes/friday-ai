"""数据库层面保证最多只有一个 is_superuser=True 的账号（WR-01 修复）。

使用 partial unique index（SQLite 3.8.9+ / Postgres 均支持），
确保在 READ COMMITTED 下的并发创建也被数据库约束拦截：
两个并发请求以不同用户名各自尝试 create_superuser 时，
后提交者会触发 IntegrityError，由 SetupInitView 调用方兜底返回 409。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_backfill_user_source"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_single_superuser
            ON users (is_superuser)
            WHERE is_superuser = TRUE;
            """,
            reverse_sql="DROP INDEX IF EXISTS accounts_user_single_superuser;",
        ),
    ]
