"""为 ChunkEdge.created_at 建索引，支撑首页"今日新增"范围统计。

11M 行大表：Postgres 上用 ``CREATE INDEX CONCURRENTLY``（不锁写，避免部署时阻塞
索引写入），故 ``atomic = False``；SQLite/MySQL（dev / 小数据）用普通 CREATE INDEX。

``SeparateDatabaseAndState``：state 侧 ``AddIndex`` 让 Django 模型状态与 Meta.indexes
保持一致（否则下次 makemigrations 会误判需删除）；database 侧按 vendor 走对应 SQL。
"""

from __future__ import annotations

from django.db import migrations, models

_INDEX_NAME = "idx_chunkedge_created"
_TABLE = "code_relations_chunkedge"


def _create_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{_INDEX_NAME}" '
            f'ON "{_TABLE}" ("created_at");'
        )
    else:
        schema_editor.execute(
            f'CREATE INDEX IF NOT EXISTS "{_INDEX_NAME}" ON "{_TABLE}" ("created_at");'
        )


def _drop_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{_INDEX_NAME}";')
    else:
        schema_editor.execute(f'DROP INDEX IF EXISTS "{_INDEX_NAME}";')


class Migration(migrations.Migration):
    # CONCURRENTLY 不能在事务内执行 → 关闭原子性。
    atomic = False

    dependencies = [
        ("code_relations", "0011_branch_name_constraints"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(_create_index, _drop_index)],
            state_operations=[
                migrations.AddIndex(
                    model_name="chunkedge",
                    index=models.Index(fields=["created_at"], name=_INDEX_NAME),
                ),
            ],
        ),
    ]
