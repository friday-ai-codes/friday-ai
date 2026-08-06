from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0035_convergencesession_drive_lease_owner_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifactversion",
            name="version_label",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
