"""Phase 76：模型类 Project→Space、ProjectRepository→SpaceRepository 重命名。

数据零丢失命门：db_table（``projects`` / ``project_repositories``）显式保持不变，
``RenameModel`` 因表名相同不产生 ``ALTER TABLE RENAME``；``RenameField`` 为元数据级
列重命名（``project_id`` → ``space_id``）。整体可逆、无数据搬迁。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    # 依赖所有"创建指向 projects.Project 的 FK"的迁移：确保 RenameModel 在这些
    # 跨 app FK 已进入迁移状态后才执行，从而正确改写其 lazy 引用为 projects.space，
    # 避免拓扑排序把本迁移排到 FK 创建之前导致悬空引用（projects.project 不存在）。
    dependencies = [
        ("projects", "0009_remove_v81_legacy_claude_fields"),
        ("agents", "0003_nullable_session_project_user"),
        ("chat", "0025_codingsession_target_branch"),
        ("delivery", "0024_ingestrun_durable_queue"),
        ("feishu", "0004_add_chat_type_to_feishu_bot_message"),
        ("knowledge", "0005_version_toc_tree"),
        ("mcp_tools", "0008_mcpworkitemtechnicalplan_canonical_plan_id"),
        ("permissions", "0001_initial"),
        ("prompts", "0009_resync_plan_generation_clarification"),
        ("runners", "0006_runnertaskassignment_feishu_message_id"),
        ("workflows", "0030_feishu_trigger_token"),
    ]

    operations = [
        migrations.RenameModel(old_name="Project", new_name="Space"),
        migrations.RenameModel(old_name="ProjectRepository", new_name="SpaceRepository"),
        migrations.RenameField(
            model_name="spacerepository", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="space",
            name="repositories",
            field=models.ManyToManyField(
                related_name="spaces",
                through="projects.SpaceRepository",
                to="repositories.repository",
            ),
        ),
        migrations.AlterField(
            model_name="space",
            name="default_provider_credential_id",
            field=models.ForeignKey(
                blank=True,
                help_text="项目级默认 Provider 凭证（contract 四层解析 L3）",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="default_for_spaces",
                to="system.providercredential",
            ),
        ),
    ]
