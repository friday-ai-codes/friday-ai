"""parts contract：``Message.parts`` JSONField additive migration。

零 data migration、零破坏性 ALTER：旧消息的 ``parts`` 字段默认 ``[]``，
前端 hydrate adapter（contract）在运行时合成 parts 用于渲染。``content`` /
``tool_calls`` / ``metadata.narrations`` / ``metadata.timeline`` 字段全部
保留，contract 写路径强同源（``content = ''.join(text parts)``）。

注意：本 migration 文件已创建但 **未自动执行**（project instructions 硬约束：模型变更后
留待用户授权才能 migrate）。
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0016_conversation_intent_trace"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="parts",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
