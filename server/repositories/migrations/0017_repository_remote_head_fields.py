"""Repository 新增 remote_head_sha + remote_head_checked_at 字段（Phase）。"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("repositories", "0016_indexhistory_changed_files"),
 ]
 operations = [
 migrations.AddField(
 model_name="repository",
 name="remote_head_sha",
 field=models.CharField(
 blank=True,
 default="",
 max_length=64,
 help_text="远端仓库 HEAD commit SHA，由 poll_repository_updates 顺手缓存",
 ),
 ),
 migrations.AddField(
 model_name="repository",
 name="remote_head_checked_at",
 field=models.DateTimeField(
 blank=True,
 null=True,
 help_text="最近一次 git ls-remote 执行时间",
 ),
 ),
 ]
