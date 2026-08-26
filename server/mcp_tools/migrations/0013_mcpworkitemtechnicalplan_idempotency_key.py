from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_tools", "0012_mcpworkitemtechnicalplan_blueprint_handoff"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpworkitemtechnicalplan",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=128,
                null=True,
                unique=True,
            ),
        ),
    ]
