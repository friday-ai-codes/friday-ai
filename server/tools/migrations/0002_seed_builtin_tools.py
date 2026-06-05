"""Seed builtin tools into RemoteTool table."""

from django.db import migrations


def seed_builtin_tools(apps, schema_editor):
    RemoteTool = apps.get_model("tools", "RemoteTool")
    RemoteTool.objects.get_or_create(
        name="fetch_feishu_document",
        defaults={
            "description": "读取飞书云文档内容，返回 Markdown 格式",
            "source": "builtin",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "项目 UUID",
                    },
                    "document_id": {
                        "type": "string",
                        "description": "文档 ID（从 URL 提取，如 doxcnXXXX 或完整 URL）",
                    },
                },
                "required": ["project_id", "document_id"],
            },
            "timeout": 30,
            "is_active": True,
            "config": {
                "handler": "agents.tools.feishu_doc_tools.fetch_feishu_document"
            },
        },
    )


def reverse(apps, schema_editor):
    RemoteTool = apps.get_model("tools", "RemoteTool")
    RemoteTool.objects.filter(name="fetch_feishu_document").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tools", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_builtin_tools, reverse),
    ]
