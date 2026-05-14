"""代码关系图谱数据模型。
- `ChunkRegistry`：chunk_id ↔ Qdrant point_id 同源映射，承载 content_hash 与
 归属仓库 / file_path / chunk_index，indexer 用 `update_or_create` 写入。
- `ChunkEdge`：chunk 间的 6 类关系边（CALL / IMPORT / SAME_FILE / TEST_OF /
 CO_CHANGED / SEMANTIC），承载 weight + builder-specific metadata。
- `EdgeType`：6 类 TextChoices 枚举，Phase EdgeBuilder 与 Phase MCP tool
 都会 import 引用。
"""
from __future__ import annotations
import uuid
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint
__all__ = ["ChunkRegistry", "ChunkEdge", "EdgeType"]
class EdgeType(models.TextChoices):
 """ChunkEdge 6 类关系边枚举（per 字面 value 大写下划线）。"""
 CALL = "CALL", "Call"
 IMPORT = "IMPORT", "Import"
 SAME_FILE = "SAME_FILE", "Same File"
 TEST_OF = "TEST_OF", "Test Of"
 CO_CHANGED = "CO_CHANGED", "Co-Changed"
 SEMANTIC = "SEMANTIC", "Semantic"
class ChunkRegistry(models.Model):
 """chunk_id 同源映射注册表（Qdrant point_id ↔ ChunkRegistry.chunk_id 1:1）。
 PK 直接使用 `chunk_id`（UUIDField），与 Qdrant point ID 完全对齐，省一次 join；
 indexer 通过 `update_or_create(chunk_id=...)` 写入，重切分场景同 chunk_id 触发
 update 而非 create（per / / ）。
 """
 chunk_id = models.UUIDField(primary_key=True, editable=False)
 content_hash = models.CharField(max_length=64, help_text="sha256 hex of chunk content")
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="chunk_registry_entries",
 )
 file_path = models.CharField(max_length=512)
 chunk_index = models.PositiveIntegerField
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 verbose_name = "Chunk 注册表"
 verbose_name_plural = "Chunk 注册表"
 indexes = [
 models.Index(
 fields=["repository", "file_path"],
 name="idx_chunk_reg_repo_file",
 ),
 ]
 def __str__(self) -> str:
 return f"ChunkRegistry({self.chunk_id} @ {self.file_path}:{self.chunk_index})"
class ChunkEdge(models.Model):
 """chunk 间关系边（6 类语义 + weight + metadata）。
 - `source_chunk_id` / `target_chunk_id` 不做 FK（per ）：允许跨仓 / chunk
 未写入 ChunkRegistry 时柔性引用，孤儿引用由 Phase reconcile 命令兜底。
 - `repository` 语义为「源 chunk 所在仓库」，跨仓 CO_CHANGED 边的目标仓库 ID
 存 `metadata.target_repository_id`（per ）。
 - weight 双重校验：模型层 `MinValueValidator/MaxValueValidator` + DB 层
 `CheckConstraint`（per ）。
 - 唯一约束 `(source_chunk_id, target_chunk_id, edge_type)` —— edge_type 必须
 进 unique，避免同对节点不同语义边互相覆盖（per ）。
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 source_chunk_id = models.UUIDField(db_index=False)
 target_chunk_id = models.UUIDField(db_index=False)
 edge_type = models.CharField(max_length=20, choices=EdgeType.choices)
 weight = models.FloatField(
 validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
 )
 metadata = models.JSONField(default=dict, blank=True)
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="chunk_edges",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 verbose_name = "Chunk 边"
 verbose_name_plural = "Chunk 边"
 constraints = [
 UniqueConstraint(
 fields=["source_chunk_id", "target_chunk_id", "edge_type"],
 name="uniq_chunkedge_triple",
 ),
 CheckConstraint(
 condition=Q(weight__gte=0.0) & Q(weight__lte=1.0),
 name="chunkedge_weight_range",
 ),
 #：DB 层兜底 edge_type 枚举，避免 Phase EdgeBuilder 绕过
 # full_clean 时（如 bulk_create / 直接 Manager.create）typo 静默落库；
 # 与 chunkedge_weight_range 同模式（双保险），满足 ROADMAP 成功条件 #4。
 CheckConstraint(
 condition=Q(edge_type__in=EdgeType.values),
 name="chunkedge_edge_type_valid",
 ),
 ]
 indexes = [
 models.Index(fields=["target_chunk_id"], name="idx_chunkedge_target"),
 models.Index(
 fields=["repository", "source_chunk_id"],
 name="idx_chunkedge_fanout",
 ),
 models.Index(
 fields=["repository", "edge_type", "-weight"],
 name="idx_chunkedge_topk",
 ),
 ]
 def __str__(self) -> str:
 return (
 f"ChunkEdge({self.source_chunk_id} -[{self.edge_type}:{self.weight:.2f}]-> "
 f"{self.target_chunk_id})"
 )
