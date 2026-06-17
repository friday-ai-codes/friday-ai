from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0017_repocodingtask'),
    ]

    operations = [
        migrations.AddField(
            model_name='ingestrun',
            name='batch_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
