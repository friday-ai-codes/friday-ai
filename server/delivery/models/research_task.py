"""并行调研子任务与单仓结构化产物模型（DOMAIN §6 / §7 / §12，Phase 39）。

立 v0.7 方案编排「map 段」的数据底座：

- **``RepoResearchTask``**：每仓一个并行调研子任务，子任务级状态机
  ``pending → running → done|failed|stale``（DOMAIN §6/§14）。``session`` 归属一次
  ``PlanSession`` 编排，``repository`` 指向被调研仓（跨 app 真实 FK——repositories 是稳定
  基础 app），``subagent_session`` 在 dispatch 容器后回填（删容器会话不删 task）。
  ``attempt`` 计数承载单仓重试（RESEARCH-02），``routed_confidence`` 来自 Phase 38
  routing，``error`` 落结构化失败诊断。
- **``PartialPlan``**：单仓调研产物（§7 PartialPlan schema 存 ``content``）；``valid`` 失效位
  承载重索引 stale（RESEARCH-03），``content_hash`` 由 service 计算（内容相等可去重）。

设计要点（守 INV-6 精神）：状态变更/落库**只经 ``ResearchService``**（39-02），本模型层
**不写**任何 create/save/状态变更/校验业务方法；旁路写表由 INV-6 grep 守护断言。
跨 app FK 用字符串前向引用避免 import 环（对齐 ``PlanSession`` 用 "delivery.WorkItem"
字符串引用范式）。
"""

import uuid

from django.db import models


class RepoResearchTaskStatus(models.TextChoices):
    """RepoResearchTask 子任务级状态枚举（5 态，逐字对齐 DOMAIN §6/§14）。"""

    PENDING = "pending", "待派发"
    RUNNING = "running", "调研中"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"
    STALE = "stale", "已过期"


class RepoResearchTask(models.Model):
    """每仓并行调研子任务（子任务级状态机 + 可靠恢复底座，DOMAIN §6/§14）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其调研子任务
    session = models.ForeignKey(
        "delivery.ConvergenceSession",
        on_delete=models.CASCADE,
        related_name="research_tasks",
    )
    # 被调研仓（跨 app 真实 FK，repositories 是稳定基础 app）；related_name="+" 不污染
    # Repository 反查
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # dispatch 容器后回填；删容器会话不删 task（SET_NULL）
    subagent_session = models.ForeignKey(
        "subagent.SubAgentSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=RepoResearchTaskStatus.choices,
        default=RepoResearchTaskStatus.PENDING,
    )
    # 来自 Phase 38 routing 的 high/medium/low
    routed_confidence = models.CharField(max_length=16, blank=True, default="")
    # 重试计数（RESEARCH-02 单仓重试）
    attempt = models.IntegerField(default=0)
    # 失败结构化诊断
    error = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_repo_research_task"
        verbose_name = "仓库调研子任务"
        verbose_name_plural = "仓库调研子任务"
        indexes = [
            models.Index(fields=["session", "status"]),
            models.Index(fields=["repository"]),
        ]

    def __str__(self) -> str:
        return f"RepoResearchTask({self.id}, {self.status})"


class PartialPlan(models.Model):
    """单仓结构化调研产物（§7 PartialPlan schema + stale 失效位，DOMAIN §7）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    research_task = models.ForeignKey(
        RepoResearchTask,
        on_delete=models.CASCADE,
        related_name="partial_plans",
    )
    # §7 PartialPlan schema：repository_id / research_summary / proposed_changes[] /
    # candidate_files[] / api_contracts_exposed[] / dependencies_on_other_repos[]
    # —— 校验/写入归 39-02 ResearchService，模型层不校验。
    content = models.JSONField(default=dict)
    # RESEARCH-03 stale 失效位（仓库重索引置 False）
    valid = models.BooleanField(default=True)
    invalidated_reason = models.CharField(max_length=64, blank=True, default="")
    # sha256 hex，由 service 本地计算
    content_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_partial_plan"
        verbose_name = "单仓调研产物"
        verbose_name_plural = "单仓调研产物"
        indexes = [
            models.Index(fields=["research_task", "valid"]),
        ]

    def __str__(self) -> str:
        return f"PartialPlan({self.id}, valid={self.valid})"
