# commit 历史索引增量边界字段迁移（Phase 25 IDX-01）。
#
# 仅 AddField，nullable，不回填历史数据（per D-04 向后兼容）：既有 row boundary=NULL，
# 首次 index_commits 走首轮 bounded 全量。本字段独立于 last_indexed_commit_sha
# （代码 chunk 索引边界），承载 commit 历史索引专用边界。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0034_sensitive_file_suggestion"),
    ]

    operations = [
        migrations.AddField(
            model_name="repository",
            name="commit_index_boundary_sha",
            field=models.CharField(
                blank=True,
                help_text="commit 历史索引已推进到的 commit SHA（增量边界）；NULL=未索引过 commit 历史",
                max_length=40,
                null=True,
            ),
        ),
    ]
