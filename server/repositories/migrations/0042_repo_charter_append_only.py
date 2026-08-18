# Generated manually for append-only RepoCharter (CHARTER-COMPAT-01: AddField only).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0041_merge_20260802_0303"),
    ]

    operations = [
        migrations.AddField(
            model_name="repocharter",
            name="appendices",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="repocharter",
            name="baseline_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="repocharter",
            name="baseline_locked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="repocharter",
            name="change_proposals",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
