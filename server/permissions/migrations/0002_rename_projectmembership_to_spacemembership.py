"""Phase 76：成员模型 ProjectMembership→SpaceMembership、FK project→space 重命名。

数据零丢失命门：db_table ``project_memberships`` 显式保持；``RenameModel`` 不改表名。
顺序命门（SQLite）：RenameModel 后先 RemoveConstraint/RemoveIndex（引用旧字段），
再 RenameField，最后 Add*；否则 RenameField 表重建会重建引用 ``project`` 的旧约束/索引。
"""

from __future__ import annotations

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("permissions", "0001_initial"),
        ("projects", "0010_rename_project_to_space"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ProjectMembership", new_name="SpaceMembership"
        ),
        migrations.AlterModelOptions(
            name="spacemembership",
            options={"verbose_name": "空间成员", "verbose_name_plural": "空间成员"},
        ),
        migrations.RemoveConstraint(
            model_name="spacemembership", name="unique_user_project"
        ),
        migrations.RemoveIndex(
            model_name="spacemembership", name="project_mem_project_ce1662_idx"
        ),
        migrations.RenameField(
            model_name="spacemembership", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="spacemembership",
            name="user",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="space_memberships",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="spacemembership",
            name="space",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="memberships",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="spacemembership",
            index=models.Index(
                fields=["space", "role"], name="project_mem_space_i_12c6a6_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="spacemembership",
            constraint=models.UniqueConstraint(
                fields=("user", "space"), name="unique_user_project"
            ),
        ),
    ]
