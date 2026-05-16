"""Phase: ChunkEdge 新增 target_repository_id 字段。
AddField nullable IntegerField。
v24 既有 6 类边 target_repository_id = NULL（backward compatible）。
不做 ForeignKey（per ChunkEdge 柔性引用原则）。
待执行：python manage.py migrate code_relations 0007
"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("code_relations", "0006_add_implements_edge_type"),
 ]
 operations = [
 migrations.AddField(
 model_name="chunkedge",
 name="target_repository_id",
 field=models.IntegerField(
 blank=True,
 null=True,
 db_index=True,
 help_text=(
 "跨仓边的 target chunk 所在仓库 ID（Phase）。"
 "单仓边（v24 既有 6 类边）为 NULL。"
 ),
 ),
 ),
 ]
