"""Phase: 扩 EdgeType TextChoices 加 IMPLEMENTS（per / ）。
仅扩 ChunkEdge.edge_type field 的 choices，无 schema 变更（per ）。
复用既有 idx_chunkedge_target + idx_chunkedge_type 索引，覆盖新 type 自动。
"""
from django.db import migrations, models
class Migration(migrations.Migration):
 dependencies = [
 ("code_relations", "0005_chunkregistry_last_built_at"),
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
 ],
 max_length=20,
 verbose_name="边类型",
 ),
 ),
 ]
