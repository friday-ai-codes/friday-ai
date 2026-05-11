from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("repositories", "0015_alter_repositorybranchindex_status_upgrading"),
 ]
 operations = [
 migrations.AddField(
 model_name="indexhistory",
 name="changed_files",
 field=models.JSONField(
 blank=True,
 default=dict,
 help_text="增量索引涉及的变更文件路径列表，全量索引时为空",
 ),
 ),
 ]
