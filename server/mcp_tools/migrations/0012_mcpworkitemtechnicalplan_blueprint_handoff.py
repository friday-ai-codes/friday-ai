from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_tools", "0011_learningcase_auto_extract"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpworkitemtechnicalplan",
            name="blueprint_artifact_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="mcpworkitemtechnicalplan",
            name="approved_blueprint_version_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="mcpworkitemtechnicalplan",
            name="approved_blueprint_version_no",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="mcpworkitemtechnicalplan",
            name="approved_blueprint_content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
