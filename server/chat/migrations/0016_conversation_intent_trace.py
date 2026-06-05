# Generated for implementation (work item).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0015_codingplan_recommended_repos'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConversationIntentTrace',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'triggering_message_id',
                    models.CharField(
                        blank=True,
                        default='',
                        help_text='触发本次协商的 user message id（字符串化的 UUID）',
                        max_length=64,
                    ),
                ),
                (
                    'clarification_id',
                    models.CharField(
                        db_index=True,
                        help_text='ask_clarification 工具调用产生的 uuid hex',
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    'question',
                    models.TextField(help_text='协商问题原文'),
                ),
                (
                    'options',
                    models.JSONField(
                        default=list,
                        help_text='ClarificationOption 列表（id/label/hint/implies）',
                    ),
                ),
                (
                    'selected_option_id',
                    models.CharField(
                        blank=True,
                        default='',
                        help_text='用户选中的 option.id；若仅自由输入则为空',
                        max_length=64,
                    ),
                ),
                (
                    'freeform_answer',
                    models.TextField(
                        blank=True,
                        default='',
                        help_text='用户自由输入的答复（与 selected_option_id 至少一个非空）',
                    ),
                ),
                (
                    'inferred_state',
                    models.JSONField(
                        default=dict,
                        help_text='implies merge 后注入对话上下文的状态字典',
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    'answered_at',
                    models.DateTimeField(
                        blank=True,
                        help_text='用户提交答复的时间；None 表示尚未回复',
                        null=True,
                    ),
                ),
                (
                    'conversation',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='intent_traces',
                        to='chat.conversation',
                    ),
                ),
                (
                    'resolved_to_plan',
                    models.ForeignKey(
                        blank=True,
                        help_text='本次协商是否最终落到 CodingPlan（evaluation 用）',
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='intent_traces',
                        to='chat.codingplan',
                    ),
                ),
            ],
            options={
                'verbose_name': '意图协商 trace',
                'verbose_name_plural': '意图协商 traces',
                'db_table': 'conversation_intent_traces',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='conversationintenttrace',
            index=models.Index(
                fields=['conversation', '-created_at'],
                name='intent_trace_conv_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='conversationintenttrace',
            index=models.Index(
                fields=['clarification_id'],
                name='intent_trace_clar_id_idx',
            ),
        ),
    ]
