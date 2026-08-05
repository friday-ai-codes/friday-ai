"""容器 SDK 会话留痕列（Phase 120，REDO-03）。

纯追加三列、均有默认值 ⇒ 已有行零回填风险（空串/NULL 等价于「没有可续的上下文」，
与改动前行为逐字一致：`build_repo_resume_env` 读不到 transcript 就返回空 env、容器全新执行）。
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subagent", "0014_alter_subagentsession_task_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="subagentsession",
            name="sdk_session_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="容器内 agent SDK 的会话 id；re-dispatch 时注入 resume 续跑",
                max_length=128,
                verbose_name="SDK 会话 ID",
            ),
        ),
        migrations.AddField(
            model_name="subagentsession",
            name="sdk_transcript",
            field=models.TextField(
                blank=True,
                default="",
                help_text="jsonl 原文（容器 ephemeral，落库才能跨容器续跑）；超上限则丢弃只留 id",
                verbose_name="SDK 会话 transcript",
            ),
        ),
        migrations.AddField(
            model_name="subagentsession",
            name="sdk_session_saved_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="SDK 会话留痕时间"),
        ),
    ]
