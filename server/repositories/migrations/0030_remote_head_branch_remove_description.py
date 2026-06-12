"""仓库简介（description）移除 + 远端 HEAD 分支缓存字段。

描述统一来源于 AI 生成的 ai_summary（PageIndex / repo_summary 流程），
手动维护的简介字段下线；remote_head_branch 由 ls-remote --symref 探测缓存，
供前端在分支选择器与标签上展示 HEAD。
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repositories", "0029_pageindex_tree_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="repository",
            name="description",
        ),
        migrations.AddField(
            model_name="repository",
            name="remote_head_branch",
            field=models.CharField(
                blank=True,
                default="",
                help_text="远端仓库 HEAD 指向的分支名，由 ls-remote --symref 探测缓存",
                max_length=100,
            ),
        ),
    ]
