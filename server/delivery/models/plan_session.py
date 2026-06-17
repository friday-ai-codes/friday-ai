"""PlanSession：方案编排持久化状态机（DOMAIN §6 / §12.7 / §14，ORCH-02）。

一次「需求 → 主方案」编排会话的操作态聚合，落 ``delivery`` app（与 WorkItem/
TechnicalPlan 同 app）。状态机按 DOMAIN §14 转移表推进：

    decomposing → routing → recalling → clarifying → researching → merging
                                                                  → done / failed

设计要点：
- **状态全持久化**：status + 中间产物 JSON（decomposition/error）全落 DB 行，
  engine 可从任意 status resume（不依赖内存态）；不可恢复错误落结构化 ``failed``。
- **状态变更单一入口**：status 只经 ``PlanSessionService.transition`` 改（INV-6 精神），
  模型层不写业务 create/save / 状态变更逻辑。
- **current_plan_version 软引用**：存 Phase 37 canonical ``PlanVersion.id``（UUID），
  **不建 FK** —— 避免 36↔37 迁移硬耦合（per 36-CONTEXT 决策），Phase 37 建表后
  由 service 写入/读取。
"""

import uuid

from django.conf import settings
from django.db import models


class PlanSessionStatus(models.TextChoices):
    """PlanSession 状态枚举（8 态，逐字对齐 DOMAIN §6/§14）。"""

    DECOMPOSING = "decomposing", "拆分中"
    ROUTING = "routing", "路由中"
    RECALLING = "recalling", "召回中"
    CLARIFYING = "clarifying", "澄清中"
    RESEARCHING = "researching", "并行调研中"
    MERGING = "merging", "融合中"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"


class PlanSessionEntrypoint(models.TextChoices):
    """PlanSession 入口枚举（工作流 / Chat，区分两入口共用底层时的来源）。"""

    WORKFLOW = "workflow", "工作流"
    CHAT = "chat", "对话"


class PlanSession(models.Model):
    """方案编排会话（v0.7 编排状态脊柱）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # INV-2：chat 自然语言需求允许无 work_item（null）；删 WorkItem 不删 session
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plan_sessions",
    )
    entrypoint = models.CharField(
        max_length=16,
        choices=PlanSessionEntrypoint.choices,
    )
    status = models.CharField(
        max_length=16,
        choices=PlanSessionStatus.choices,
        default=PlanSessionStatus.DECOMPOSING,
    )

    # 软引用：存 Phase 37 canonical PlanVersion.id（UUID），不建 FK（避免 36↔37 迁移耦合）
    current_plan_version = models.UUIDField(null=True, blank=True)

    # chat 入口发起编排时的会话软引用（chat.Conversation.id，UUID）；沿用 current_plan_version
    # 「软引用不建跨 app FK」哲学，避免 delivery→chat 硬耦合。workflow 入口为空。
    # 用途：会话列表反查「该会话是否产出了 SDD spec」（has_sdd_spec 徽标）。
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)

    # 中间产物（拆分结果：前后端/业务线/模块）
    decomposition = models.JSONField(default=dict)
    # 路由候选仓结果（Phase 38-02 写入：候选 + confidence + router_version + auto_selected）
    routing = models.JSONField(default=dict, blank=True)
    # 召回上下文（Phase 38-03 写入精简命中列表 [{entity_id, kind, title, score}]；
    # default=list 与持久化形状一致——空态与有值态顶层同为 list，避免下游消费类型漂移 WR-01）
    recall_context = models.JSONField(default=list, blank=True)
    # 不可恢复错误结构化落地
    error = models.JSONField(default=dict, blank=True)

    # 发起编排的用户（召回 stage 作权限 actor，为空走 fail-closed 空召回）；
    # null=True 满足系统/无交互用户场景，related_name="+" 不建反向访问器避免污染 user 模型
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    event_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery_plan_session"
        verbose_name = "方案编排会话"
        verbose_name_plural = "方案编排会话"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["work_item", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.entrypoint}:{self.status}:{self.id}"
