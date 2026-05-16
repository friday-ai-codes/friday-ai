"""Phase：IndexHistory 增加跨仓 join 可观测字段。
- cross_repo_match_count: 最近一次 offline join 匹配数（PositiveIntegerField）
- cross_repo_built_at: 最近一次 offline join 完成时间（DateTimeField nullable）
注意：创建此 migration 后需手动执行：
 cd server && python manage.py migrate repositories
"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("repositories", "0022_indexhistory_graph_fields"),
 ]
 operations = [
 migrations.AddField(
 model_name="indexhistory",
 name="cross_repo_match_count",
 field=models.PositiveIntegerField(
 default=0,
 help_text="最近一次 cross_repo offline join 产生的匹配记录总数",
 ),
 ),
 migrations.AddField(
 model_name="indexhistory",
 name="cross_repo_built_at",
 field=models.DateTimeField(
 blank=True,
 null=True,
 help_text="最近一次 cross_repo offline join 完成时间",
 ),
 ),
 ]
