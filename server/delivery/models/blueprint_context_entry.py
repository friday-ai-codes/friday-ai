"""蓝图会话级共享上下文总线条目（Phase 113，DESIGN §5.6）。

- **append-only**：只追加、不就地改写（生命周期只允许 ``status`` 由 ``active`` 走向
  ``superseded``）；同一会话内 ``seq`` 单调递增即读取序，``since_seq`` 增量拉取靠它。
- **唯一 writer = ``BlueprintContextService``**（INV-6）：MCP view / 回调 / adapter 一律
  零裸 ORM 写；本模型层**零业务方法**，写入不得旁路。
- ``content`` 是半可信 JSON（容器上报的调研结论/接口契约），**入库前已由 service 递归
  脱敏**（`_redact_json`），模型层不再校验也不再脱敏。
- **不复用 ``ProjectMemory``**：那是项目级长期记忆（打包预算 30 条），高频会话写入会
  污染它；有长期价值的条目经 distill 管道产 ``ProjectMemoryDraft``（113-06），人工
  confirm 才生效。
"""

import uuid

from django.db import models


class ContextEntryKind(models.TextChoices):
    """总线条目种类（CONTEXT 锁定六值，不增不减）。"""

    FINDING = "finding", "调研发现"
    API_SURFACE = "api_surface", "接口面"
    CONTRACT = "contract", "跨仓契约"
    DECISION = "decision", "决策"
    DEPENDENCY_CLAIM = "dependency_claim", "依赖等待声明"
    QUESTION = "question", "待澄清问题"


class ContextEntryStatus(models.TextChoices):
    """条目状态：append-only 表只允许 active → superseded 单向收敛。"""

    ACTIVE = "active", "生效中"
    SUPERSEDED = "superseded", "已废弃"


class BlueprintContextEntry(models.Model):
    """蓝图会话级共享上下文总线条目（append-only，DESIGN §5.6）。"""

    objects: "models.Manager[BlueprintContextEntry]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 会话边界即隔离边界：所有查询必先按它切片，故它是每个复合索引的最左列
    convergence_session = models.ForeignKey(
        "delivery.ConvergenceSession",
        on_delete=models.CASCADE,
        related_name="blueprint_context_entries",
    )
    # distill 沉淀要按项目产 ProjectMemory 草案，冗余存 project 免二跳。
    # 可空：ConvergenceSession 无 project FK，项目归属靠 conversation/work_item 多跳
    # best-effort 反查（见 architect_merge_adapter._maybe_bind_plan_to_project），
    # 解析不到时宁可留空也不伪造归属（沉淀侧再解析一次即可）。
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="blueprint_context_entries",
    )
    # 前缀约定：repo:{id}.api_surface / contract:{name} / decision:{thread_id} /
    # dependency:{from}->{to}；前缀查走复合索引左前缀 range scan
    key = models.CharField(max_length=200)
    # max_length=24：dependency_claim 长 17 字符
    kind = models.CharField(max_length=24, choices=ContextEntryKind.choices)
    # 产出仓（可空：contract 类条目可能不属单仓）；kind 过滤后基数已低，不单独建索引
    repository_id = models.CharField(max_length=64, blank=True, default="")
    # 半可信正文，service 已递归脱敏；模型层不校验
    content = models.JSONField(default=dict)
    # 产出方标识：容器 subagent session_id 或 system
    produced_by = models.CharField(max_length=64, default="system")
    # **会话内**单调，由 service 锁父 ConvergenceSession 行分配；不用全局 AutoField ——
    # 跨会话空洞会让 since_seq 增量语义失效
    seq = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=ContextEntryStatus.choices,
        default=ContextEntryStatus.ACTIVE,
    )
    # 观测规范：绑定触发用户；无触发用户记 system
    initiated_by_user_id = models.CharField(max_length=64, default="system")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_blueprint_context_entry"
        verbose_name = "蓝图上下文总线条目"
        verbose_name_plural = "蓝图上下文总线条目"
        # append-only 顺序：会话内单调序即读取序
        ordering = ["seq"]
        indexes = [
            # ① since_seq 增量拉取驱动：filter(session, seq__gt=N).order_by("seq")
            models.Index(fields=["convergence_session", "seq"]),
            # ② key 前缀查驱动：filter(session, key__startswith=…) 走左前缀 range scan
            models.Index(fields=["convergence_session", "key"]),
            # ③ 环检测/分类取驱动：filter(session, kind=dependency_claim, status=active)
            models.Index(fields=["convergence_session", "kind", "status"]),
        ]
        constraints = [
            # seq 唯一性兜底（并发分配主手段是锁父会话行，这里是最后一道防线）
            models.UniqueConstraint(
                fields=["convergence_session", "seq"],
                name="uq_blueprint_context_session_seq",
            ),
        ]

    def __str__(self) -> str:
        return f"BlueprintContextEntry({self.id}, {self.kind}/{self.key}#{self.seq})"
