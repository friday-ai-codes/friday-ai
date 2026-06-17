from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0022_codingplan_canonical_plan_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="is_archived",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
