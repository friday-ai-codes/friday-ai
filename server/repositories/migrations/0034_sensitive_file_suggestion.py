# SensitiveFileSuggestion 建表迁移（Phase 24 Plan 01，EXCL-03）。
#
# 仅 CreateModel：持久化敏感文件 AI 识别建议名单（path/severity/detector/脱敏 reason/
# status + unique(repository, path) upsert 锚点 + (repository, status) 索引）。不回填历史数据。

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('repositories', '0033_cleanup_run'),
    ]

    operations = [
        migrations.CreateModel(
            name='SensitiveFileSuggestion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('path', models.CharField(help_text='相对仓库根的 POSIX 路径（口径与 exclusion.normalize_rel_path 对齐）', max_length=500)),
                ('severity', models.CharField(choices=[('real_secret', '命中真实密钥'), ('likely_sensitive', '疑似敏感'), ('config_review', '待复核配置')], max_length=20)),
                ('detector', models.CharField(choices=[('heuristic', '文件名启发式'), ('content', '内容扫描'), ('llm', 'LLM 分类')], max_length=16)),
                ('reason', models.TextField(help_text='脱敏命中描述：只记命中类型与位置（行号），**绝不**包含密钥本体 / 命中文本原值（DOMAIN §9 D-04，T-24-01）')),
                ('status', models.CharField(choices=[('pending', '待处理'), ('accepted', '已接受'), ('dismissed', '已忽略')], default='pending', max_length=16)),
                ('detected_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('repository', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sensitive_suggestions', to='repositories.repository')),
            ],
            options={
                'verbose_name': '敏感文件建议',
                'verbose_name_plural': '敏感文件建议',
                'db_table': 'repo_sensitive_file_suggestions',
                'indexes': [models.Index(fields=['repository', 'status'], name='idx_repo_sensitive_status')],
                'constraints': [models.UniqueConstraint(fields=('repository', 'path'), name='uq_repo_sensitive_suggestion')],
            },
        ),
    ]
