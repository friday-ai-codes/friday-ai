"""Phase: 扩 EdgeType choices 加 API_CALLS。
与 Phase_add_implements_edge_type.py 类似，但同时更新
DB 层 CheckConstraint chunkedge_edge_type_valid（migration 0002 硬编码了 6 个值）。
操作：
1. AlterField 更新 choices（含 API_CALLS）
2. RemoveConstraint 移除旧约束（仅含 CALL/IMPORT/SAME_FILE/TEST_OF/CO_CHANGED/SEMANTIC/IMPLEMENTS）
3. AddConstraint 写入含全部 8 值的新约束
待执行：python manage.py migrate code_relations 0008
"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("code_relations", "0007_chunkedge_target_repository_id"),
 ]
 operations = [
 migrations.AlterField(
 model_name="chunkedge",
 name="edge_type",
 field=models.CharField(
 choices=[
 ("CALL", "Call"),
 ("IMPORT", "Import"),
 ("SAME_FILE", "Same File"),
 ("TEST_OF", "Test Of"),
 ("CO_CHANGED", "Co-Changed"),
 ("SEMANTIC", "Semantic"),
 ("IMPLEMENTS", "Implements"),
 ("API_CALLS", "API Calls"),
 ],
 max_length=20,
 ),
 ),
 migrations.RemoveConstraint(
 model_name="chunkedge",
 name="chunkedge_edge_type_valid",
 ),
 migrations.AddConstraint(
 model_name="chunkedge",
 constraint=models.CheckConstraint(
 condition=models.Q(
 edge_type__in=[
 "CALL",
 "IMPORT",
 "SAME_FILE",
 "TEST_OF",
 "CO_CHANGED",
 "SEMANTIC",
 "IMPLEMENTS",
 "API_CALLS",
 ]
 ),
 name="chunkedge_edge_type_valid",
 ),
 ),
 ]
