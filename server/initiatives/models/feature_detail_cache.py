"""功能点详情结构化缓存（Step 2 结果持久化）。

点开功能点详情时把其整段原文（``source``）结构化为柔性 sections（功能描述/业务规则/
数据流转/流程图/验收项…）是一次 LLM 调用。原实现**每次点开都现算、不缓存**，体验差且费
token。本表按 ``(project, source_hash)`` 持久化结构化结果：

- **解析阶段预生成**：逐模块解析功能点后 best-effort 预热缓存（点开即时）。
- **点开兜底**：命中缓存直接返回；未命中才生成并写入（此后不再重算）。
- **按内容哈希**：``source`` 原文没变即恒命中，与 feature list 载体（paste/manual/feishu/
  workflow）解耦——无论如何生成的功能点，详情结构只算一次。
"""

from __future__ import annotations

import uuid

from django.db import models


class FeatureDetailCache(models.Model):
    """功能点/模块详情结构化 sections 缓存（按 project + 原文哈希）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="feature_detail_caches",
        verbose_name="项目",
    )
    source_hash = models.CharField(max_length=64, verbose_name="原文 SHA-256")
    sections = models.JSONField(default=list, blank=True, verbose_name="结构化段落")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_feature_detail_cache"
        verbose_name = "功能点详情缓存"
        verbose_name_plural = "功能点详情缓存"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_hash"],
                name="uq_feature_detail_cache_project_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "source_hash"]),
        ]

    def __str__(self) -> str:
        return f"FeatureDetailCache(project={self.project_id}, hash={self.source_hash[:8]})"
