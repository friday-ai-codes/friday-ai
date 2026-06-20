from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('repositories', '0037_graphfileindex'),
    ]

    operations = [
        migrations.AddField(
            model_name='corpustreesnapshot',
            name='source_hash',
            field=models.CharField(
                blank=True,
                default='',
                help_text='构建时全仓输入（id/ai_summary/facets）指纹，供 run_page_index 按 hash 跳过重建',
                max_length=64,
            ),
        ),
    ]
