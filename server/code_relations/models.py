"""代码关系图谱数据模型。

- `ChunkRegistry`：chunk_id ↔ Qdrant point_id 同源映射，承载 content_hash 与
  归属仓库 / file_path / chunk_index，indexer 用 `update_or_create` 写入。
- `ChunkEdge`：chunk 间的 6 类关系边（CALL / IMPORT / SAME_FILE / TEST_OF /
  CO_CHANGED / SEMANTIC），承载 weight + builder-specific metadata。
- `EdgeType`：6 类 TextChoices 枚举，implementation EdgeBuilder 与 implementation MCP tool
  都会 import 引用。
"""

from __future__ import annotations

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

__all__ = ["ChunkRegistry", "ChunkEdge", "EdgeType"]


class EdgeType(models.TextChoices):
    """ChunkEdge 8 类关系边枚举（per contract 字面 value 大写下划线）。

    implementation 新增 IMPLEMENTS（Go interface 实现关系，per work item）。
    implementation 新增 API_CALLS（跨仓 API 调用关系，per work item）。
    """

    CALL = "CALL", "Call"
    IMPORT = "IMPORT", "Import"
    SAME_FILE = "SAME_FILE", "Same File"
    TEST_OF = "TEST_OF", "Test Of"
    CO_CHANGED = "CO_CHANGED", "Co-Changed"
    SEMANTIC = "SEMANTIC", "Semantic"
    IMPLEMENTS = "IMPLEMENTS", "Implements"
    API_CALLS = "API_CALLS", "API Calls"


class ChunkRegistry(models.Model):
    """chunk_id 同源映射注册表（Qdrant point_id ↔ ChunkRegistry.chunk_id 1:1）。

    PK 直接使用 `chunk_id`（UUIDField），与 Qdrant point ID 完全对齐，省一次 join；
    indexer 通过 `update_or_create(chunk_id=...)` 写入，重切分场景同 chunk_id 触发
    update 而非 create（per contract / contract / contract）。
    """

    chunk_id = models.UUIDField(primary_key=True, editable=False)
    content_hash = models.CharField(max_length=64, help_text="sha256 hex of chunk content")
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="chunk_registry_entries",
    )
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传
    # （配合 generate_chunk_id 的分支命名空间，feature chunk_id 与 base 天然不同）。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    file_path = models.CharField(max_length=512)
    chunk_index = models.PositiveIntegerField()
    # implementation contract：邻居元数据 enrichment 字段——indexer 后续 plan 同步回填，
    # 本 phase 仅声明字段。NULL 表示历史数据未回填，graph_context 渲染时
    # fallback 到无行号格式（plan `_resolve_neighbor_metadata` graceful 处理）。
    line_start = models.PositiveIntegerField(null=True, blank=True)
    line_end = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # rebuild_chunk_edges 断点续跑标记。
    # NULL = 未 backfill；rebuild_chunk_edges 命令完成后 update_at = timezone.now()。
    # context contract 标 implementation 落但实际未落，本 plan 补齐。
    last_built_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "最近一次 rebuild_chunk_edges 完成时间；"
            "NULL 表示未 backfill（implementation）"
        ),
    )

    class Meta:
        verbose_name = "Chunk 注册表"
        verbose_name_plural = "Chunk 注册表"
        # contract: line_end >= line_start DB 层兜底——与 ChunkEdge.weight 双保险
        # 模式（model validator + CheckConstraint）对齐；indexer 后续回填若 bug
        # 写入 line_end < line_start 静默落库，graph_context 渲染时会显示错乱
        # 行号区间。允许任一为 NULL（per contract 历史数据未回填）。
        constraints = [
            CheckConstraint(
                condition=(
                    Q(line_start__isnull=True)
                    | Q(line_end__isnull=True)
                    | Q(line_end__gte=F("line_start"))
                ),
                name="chunkreg_line_range_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["repository", "file_path"],
                name="idx_chunk_reg_repo_file",
            ),
            # 分支隔离复合索引（旧索引保留，新增并存）。
            models.Index(
                fields=["repository", "branch_name", "file_path"],
                name="idx_chunkreg_repo_branch_file",
            ),
        ]

    def __str__(self) -> str:
        return f"ChunkRegistry({self.chunk_id} @ {self.file_path}:{self.chunk_index})"


class ChunkEdge(models.Model):
    """chunk 间关系边（8 类语义 + weight + metadata）。

    - `source_chunk_id` / `target_chunk_id` 不做 FK（per contract）：允许跨仓 / chunk
      未写入 ChunkRegistry 时柔性引用，孤儿引用由 implementation reconcile 命令兜底。
    - `repository` 语义为「源 chunk 所在仓库」（per contract / work item）。
    - `target_repository_id` 跨仓边的 target chunk 所在仓库 ID（implementation
      work item）；单仓边（v24 既有 6 类）为 NULL——backward compatible。
      不做 FK（per contract 柔性引用原则）。
    - weight 双重校验：模型层 `MinValueValidator/MaxValueValidator` + DB 层
      `CheckConstraint`（per contract）。
    - 唯一约束 `(source_chunk_id, target_chunk_id, edge_type)` —— edge_type 必须
      进 unique，避免同对节点不同语义边互相覆盖（per contract）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_chunk_id = models.UUIDField(db_index=False)
    target_chunk_id = models.UUIDField(db_index=False)
    edge_type = models.CharField(max_length=20, choices=EdgeType.choices)
    # 分支隔离维度。"" = base 分支，feature 由 implementation 写入侧透传。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    weight = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    metadata = models.JSONField(default=dict, blank=True)
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="chunk_edges",
    )
    target_repository_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "跨仓边的 target chunk 所在仓库 ID（implementation）。"
            "单仓边（v24 既有 6 类边）为 NULL——backward compatible。"
            "不做 ForeignKey（per contract 柔性引用原则）；与 Repository.id UUID 类型对齐。"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Chunk 边"
        verbose_name_plural = "Chunk 边"
        constraints = [
            # branch_name 进唯一约束（Critical 1 防御性冗余，
            # implementation 写入侧必须同步透传 branch_name，否则跨分支同三元组撞约束）。
            UniqueConstraint(
                fields=["source_chunk_id", "target_chunk_id", "edge_type", "branch_name"],
                name="uniq_chunkedge_triple",
            ),
            CheckConstraint(
                condition=Q(weight__gte=0.0) & Q(weight__lte=1.0),
                name="chunkedge_weight_range",
            ),
            # DB 层兜底 edge_type 枚举，避免 implementation EdgeBuilder 绕过
            # full_clean() 时（如 bulk_create / 直接 Manager.create）typo 静默落库；
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
            # 分支隔离复合索引（旧索引保留，新增并存）。
            models.Index(
                fields=["repository", "branch_name", "source_chunk_id"],
                name="idx_chunkedge_branch_fanout",
            ),
            models.Index(
                fields=["repository", "edge_type", "-weight"],
                name="idx_chunkedge_topk",
            ),
            # created_at 索引：支撑首页 dashboard 的"今日新增"范围统计
            # （created_at >= 今日 AND < 明日）。此前该列无索引，11M 行全表扫描约 1.8s。
            models.Index(fields=["created_at"], name="idx_chunkedge_created"),
        ]

    def __str__(self) -> str:
        return (
            f"ChunkEdge({self.source_chunk_id} -[{self.edge_type}:{self.weight:.2f}]-> "
            f"{self.target_chunk_id})"
        )
