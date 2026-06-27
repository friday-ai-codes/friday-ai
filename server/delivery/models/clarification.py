"""Clarification：HITL 澄清问答模型（DOMAIN §6/§12/§14，CLARIFY-01）。

编排在不清晰时发 ``Clarification`` 挂起等用户，回答后仅 ``affected_partials`` 内的
``RepoResearchTask`` 重跑、其余 partial 复用（§14 clarifying 挂起/重跑规则）。

设计要点（守 INV-6 精神）：
- **写入单一入口**：落库/状态变更只经 ``ClarificationService``，模型层**不写**任何
  create/save/answer 业务方法（旁路写表由 INV-6 grep 守护断言）。
- **pending 语义**：clarification pending = 存在 ``answered_at IS NULL`` 的 Clarification
  （由 service/engine 判定，不在模型上加方法）。
- **affected_partials**：M2M 指向回答后须重跑的 ``RepoResearchTask``；``related_name="+"``
  不污染 RepoResearchTask 反查。
"""

import uuid

from django.db import models


class Clarification(models.Model):
    """HITL 澄清问答（§6 字段 + affected_partials 重跑面）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其澄清
    session = models.ForeignKey(
        "delivery.PlanSession",
        on_delete=models.CASCADE,
        related_name="clarifications",
    )
    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    # 回答后哪些 task 须重跑；related_name="+" 不污染 RepoResearchTask 反查
    affected_partials = models.ManyToManyField(
        "delivery.RepoResearchTask",
        blank=True,
        related_name="+",
    )
    # ── CLARIFY-01「轮次容器」新增字段（全 nullable，旧行不强制回填、不破坏 0016 schema）──
    # 多轮序号（支撑 Phase 91 多轮 resume）；首轮可不填，由 service 写入时按 session 已有轮数派生。
    round_no = models.PositiveIntegerField(null=True, blank=True)
    # 容器状态 pending/answered/skipped。**严禁命名 status**：避免与 PlanSession.status
    # 语义混淆、也避免迁移把它误判为状态机字段（状态流转仍只经 PlanSessionService.transition）。
    container_status = models.CharField(max_length=16, null=True, blank=True)
    # CLARIFY-03 携带：标记本轮澄清源自哪个仓的调研（入口无关 helper 透传）。
    origin_repo = models.CharField(max_length=255, null=True, blank=True)
    # 采纳率分析便利的冗余绑定；**canonical 绑定仍是 session.current_plan_version**，
    # 此字段只为按 plan 维度聚合采纳率时省一跳，不作为权威关联。
    plan_version_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_clarification"
        verbose_name = "澄清问答"
        verbose_name_plural = "澄清问答"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        pending = self.answered_at is None
        return f"Clarification({self.id}, pending={pending})"


class ClarificationQuestion(models.Model):
    """结构化澄清的单个问题行（CLARIFY-01 子表，按题承载答案 + 采纳信号）。

    一个 ``Clarification``（轮次容器）下挂多个 ``ClarificationQuestion``，承载多问题 +
    单/多选 + 选项 + 推荐项 + 按题答案 + 持久化采纳信号，便于后续按题 SQL 聚合采纳率。

    设计要点（守 INV-6 精神）：
    - **写入单一入口**：建题/作答只经 ``ClarificationService``，模型层**不写**任何
      create/save/answer 业务方法（旁路写表由 INV-6 grep 守护断言覆盖子模型）。
    - **采纳信号定格**：``recommendation_adopted`` 在作答时一次性算清并持久化，不靠日志
      事后拼、不查询时现算（多选命中语义随推荐演化会漂移）。
    - **async 安全**：所有读写经 service 的 ``sync_to_async`` 同步块，禁裸 lazy-FK。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 归属一个澄清轮次容器；删容器级联删其问题行
    clarification = models.ForeignKey(
        "delivery.Clarification",
        on_delete=models.CASCADE,
        related_name="questions",
    )
    # 同轮内展示/作答顺序（0-based）
    order = models.PositiveIntegerField(default=0)
    question = models.TextField()
    # single（单选）/ multi（多选）。**避开 Python 内建 type**：字段名用 qtype。
    qtype = models.CharField(max_length=8, default="single")
    # 候选项列表 [str]
    options = models.JSONField(default=list)
    # 推荐项：single 存 [str] 或 str / multi 存 list
    recommended = models.JSONField(default=list)
    # CLARIFY-03 携带：该问题源自哪个仓的调研（nullable）
    origin_repo = models.CharField(max_length=255, null=True, blank=True)
    # 答案：single=str / multi=list[str]；未答为 None
    selected = models.JSONField(null=True, blank=True)
    # 自由文本补充答案
    freeform_text = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    # 作答时定格「用户最终选择是否=推荐」；null=未答/无推荐项/纯 freeform（不计入采纳率分母）
    recommendation_adopted = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_clarification_question"
        verbose_name = "澄清问题"
        verbose_name_plural = "澄清问题"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["clarification", "order"]),
        ]

    def __str__(self) -> str:
        answered = self.answered_at is not None
        return f"ClarificationQuestion({self.id}, order={self.order}, answered={answered})"
