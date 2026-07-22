# Phase 103 AGENT-01：AccessToken 加 kind（personal/task）+ session_id（任务 token 关联）。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('access_tokens', '0002_accesstoken_note_accesstoken_token_suffix'),
    ]

    operations = [
        migrations.AddField(
            model_name='accesstoken',
            name='kind',
            field=models.CharField(choices=[('personal', 'Personal'), ('task', 'Task')], db_index=True, default='personal', max_length=16),
        ),
        migrations.AddField(
            model_name='accesstoken',
            name='session_id',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]
