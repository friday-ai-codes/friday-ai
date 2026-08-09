# Generated for Phase 125 review fix WR-02 — ADD COLUMN only.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("codegraph", "0011_symbolcommunity"),
    ]

    operations = [
        migrations.AddField(
            model_name="symbolcommunity",
            name="member_keys",
            field=models.JSONField(default=list),
        ),
    ]
