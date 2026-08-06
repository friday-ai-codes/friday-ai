"""ConvergenceSession：通用 AI 收敛回路持久化状态机（Chassis v2 · P2）。

把方案专属的 ``PlanSession``（8 态写死阶段）泛化为**进程无关**的收敛会话：

- ``status``：**通用运行时语义**枚举（``created | running | waiting_clarification |
  waiting_event | done | failed``）——不再是方案专属阶段；阶段身份由 ``current_stage``
  承载，运行时态由 ``status`` 承载（两者正交）。
- ``process_type``：注册于 ``services.process_runtime`` ``ProcessTypeRegistry`` 的流程类型
  （如 ``technical_plan`` / ``echo``），决定 stage graph 与产物类型。
- ``current_stage``：stage graph 内当前 stage key（取代写死阶段枚举）；转移目标从 stage
  graph 查（见 ``ConvergenceSessionService``）。
- ``stage_state``：阶段中间产物 JSON 袋（取代 ``decomposition``/``routing``/``recall_context``
  等散字段——这些现为 ``stage_state`` 的键）。
- ``current_artifact_version``：FK → ``delivery.ArtifactVersion``，指向当前产物版本（取代
  方案专属软引用 ``current_plan_version``）。

设计要点：
- **状态全持久化**：``status`` + ``current_stage`` + ``stage_state`` 全落 DB 行，
  ``ProcessEngine`` 可从任意状态 resume（不依赖内存态）；不可恢复错误落结构化 ``error``。
- **状态变更单一入口**：``status`` / ``current_stage`` 只经 ``ConvergenceSessionService``
  改（INV-6 精神），模型层不写业务 create/save / 状态变更逻辑。
"""

import uuid

from django.conf import settings
from django.db import models


class ConvergenceSessionStatus(models.TextChoices):
    """通用收敛会话运行时态（与阶段身份 ``current_stage`` 正交）。"""

    CREATED = "created", "已创建"
    RUNNING = "running", "运行中"
    WAITING_CLARIFICATION = "waiting_clarification", "等待澄清"
    WAITING_EVENT = "waiting_event", "等待事件"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"


class ConvergenceSessionEntrypoint(models.TextChoices):
    """收敛会话入口枚举（区分多入口共用底层时的来源）。"""

    WORKFLOW = "workflow", "工作流"
    CHAT = "chat", "对话"
    MCP = "mcp", "MCP"
    WEBHOOK = "webhook", "Webhook"
    TOOL_INVOKE = "tool_invoke", "工具调用"


class ConvergenceSession(models.Model):
    """通用 AI 收敛回路会话（Chassis v2 收敛引擎状态脊柱）。"""

    objects: "models.Manager[ConvergenceSession]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 流程类型（注册于 ProcessTypeRegistry，开放枚举）
    process_type = models.CharField(max_length=40, verbose_name="流程类型")

    # INV-2：chat 自然语言需求允许无 work_item（null）；删 WorkItem 不删 session
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="convergence_sessions",
    )
    entrypoint = models.CharField(
        max_length=16,
        choices=ConvergenceSessionEntrypoint.choices,
    )
    status = models.CharField(
        max_length=24,
        choices=ConvergenceSessionStatus.choices,
        default=ConvergenceSessionStatus.CREATED,
    )

    # stage graph 内当前 stage key（取代写死阶段枚举）
    current_stage = models.CharField(max_length=40, blank=True, default="")

    # 阶段中间产物袋（取代 decomposition/routing/recall_context 等散字段）
    stage_state = models.JSONField(default=dict, blank=True)

    # 当前产物版本（取代方案专属软引用 current_plan_version）
    current_artifact_version = models.ForeignKey(
        "delivery.ArtifactVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # chat 入口发起编排时的会话软引用（chat.Conversation.id，UUID）；workflow 入口为空。
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)

    # 工作流入口挂起 → 容器/澄清回调 resume 钥匙（workflows.NodeExecution.id 软引用）。
    node_execution_id = models.UUIDField(null=True, blank=True, db_index=True)

    # 不可恢复错误结构化落地
    error = models.JSONField(default=dict, blank=True)

    # 发起编排的用户（召回 stage 作权限 actor，为空走 fail-closed 空召回）
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # 观测：触发用户 id 字符串（后台任务/外部触发归因，无则 "system"）
    initiated_by_user_id = models.CharField(max_length=64, blank=True, default="")

    # ── 驱动租约（同一会话同时只允许一个驱动者跑 stage handler）──────────────
    #
    # 为什么要落在**列**上而不是内存锁或 stage_state 里：驱动者分散在多个入口（durable
    # worker、容器回调 barrier、动作端点、僵尸会话扫描），跨进程/跨副本，进程内的
    # asyncio.Lock 拦不住；而 `stage_state` 会被各 stage handler 整桶覆写，租约放进去会被
    # 无声抹掉。列 + 单条 UPDATE 的 CAS 是唯一对所有入口都成立的判据。
    #
    # ⚠️ `drive_lease_until` 是**自愈用的兜底过期时间**，不是「驱动最多跑这么久」：持有者
    # 崩溃/被杀时租约靠它过期，否则会话永久卡死。正常释放走 finally。
    drive_lease_owner = models.CharField(max_length=64, blank=True, default="")
    drive_lease_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    event_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery_convergence_session"
        verbose_name = "收敛会话"
        verbose_name_plural = "收敛会话"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["process_type", "status"]),
            models.Index(fields=["work_item", "status"]),
            # 抢占 SQL 的 WHERE 走 (id, drive_lease_until)，id 已是主键，这条只为过期扫描。
            models.Index(fields=["drive_lease_until"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.process_type}:{self.entrypoint}:{self.current_stage}/{self.status}:{self.id}"

    # ---- stage_state 便捷只读视图（写入恒经 ConvergenceSessionService.transition(stage_state=)） ----
    # technical_plan process 沿用既有 stage_state 键（decomposition/routing/recall_context），
    # 以下属性让既有 adapter 读取点零改动复用（INV-6：仍只读，绝不旁路写）。

    @property
    def decomposition(self) -> dict:
        return (self.stage_state or {}).get("decomposition") or {}

    @property
    def routing(self) -> dict:
        return (self.stage_state or {}).get("routing") or {}

    @property
    def recall_context(self) -> list:
        return (self.stage_state or {}).get("recall_context") or []

    @property
    def classification(self) -> dict:
        """feature list 入口的功能点新增/改造分类结果；其余入口恒为空 dict。"""
        return (self.stage_state or {}).get("classification") or {}
