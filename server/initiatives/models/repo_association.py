"""业务级「项目↔仓库关联」与 per-repo 容器校验任务模型（Phase 88，REPO-01/02）。

立 v0.16.0「智能业务关联仓库」交付的持久化地基（D-05 净新增模型）：

- **``RepoAssociation``**：业务级「项目↔仓库关联」真相源。现状缺口——只有分支级
  ``ProjectBranch`` / 项目级 ``ProjectRelation`` / 空间级 ``Space.repositories``，
  **无**业务级 project↔repo 关联模型。``status`` 状态机
  ``proposed → confirmed → verifying → verified|rejected`` 承载整条交互回路：
  D-01（选仓提案）→ D-03（用户确认）→ D-02（逐仓深验）→ 终态/回退（mismatch 可回退）。
  ``project`` 必填锚定业务，``work_item`` 可选挂跟踪（D-06），``repository`` 指被关联仓，
  ``score``/``confidence``/``routed_reason``/``matched_node_paths`` 来自 ``RepoRouterV2`` 候选。
- **``RepoVerifyTask``**：per-repo 容器深验任务（D-02），逐字镜像
  ``delivery.RepoResearchTask``/``PartialPlan`` 形状（status 5 态 + ``subagent_session``
  SET_NULL dispatch 后回填 + ``attempt`` 重试 + ``error`` 结构化诊断），并加 ``verdict``
  JSON 承载容器 explore 产出的适配性裁决（server 解析）。

设计要点（守 INV-6 精神）：状态变更/落库**只经 ``RepoAssociationService``**（88-02 落地），
本模型层**不写**任何 create/save/状态变更/校验业务方法；旁路写表由 INV-6 grep 守护断言。
跨 app FK 一律字符串前向引用避免 import 环（对齐 ``RepoResearchTask`` 用
``"repositories.Repository"`` / ``"subagent.SubAgentSession"`` / ``"delivery.WorkItem"`` 范式）。
"""

from __future__ import annotations

import uuid

from django.db import models


class RepoAssociationStatus(models.TextChoices):
    """业务↔仓库关联状态枚举（覆盖 propose→confirm→verify→终态/回退整条回路）。"""

    PROPOSED = "proposed", "已提案"
    CONFIRMED = "confirmed", "已确认"
    VERIFYING = "verifying", "校验中"
    VERIFIED = "verified", "已验证"
    REJECTED = "rejected", "已拒绝"


class RepoAssociation(models.Model):
    """业务级「项目↔仓库关联」+ 状态机（D-05，镜像 RepoResearchTask 的 INV-6 范式）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 锚定业务的项目（必填）；删项目级联删其仓库关联
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="repo_associations",
    )
    # 可选挂 work_item 跟踪（D-06）；删 work_item 不删关联（SET_NULL）
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # 被关联仓（跨 app 真实 FK，repositories 是稳定基础 app）；related_name="+" 不污染反查
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=RepoAssociationStatus.choices,
        default=RepoAssociationStatus.PROPOSED,
    )
    # 来自 RepoRouterV2 候选的综合打分 / 置信档 / 路由理由 / 命中能力树节点
    score = models.FloatField(default=0.0)
    confidence = models.CharField(max_length=16, blank=True, default="")
    routed_reason = models.TextField(blank=True, default="")
    source = models.CharField(max_length=32, default="router_v2")
    matched_node_paths = models.JSONField(default=list, blank=True)
    initiated_by_user_id = models.CharField(max_length=64, blank=True, default="system")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_repo_association"
        verbose_name = "项目仓库关联"
        verbose_name_plural = "项目仓库关联"
        unique_together = (("project", "repository"),)
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["repository"]),
        ]

    def __str__(self) -> str:
        return f"RepoAssociation({self.id}, {self.status})"


class RepoVerifyTaskStatus(models.TextChoices):
    """RepoVerifyTask 子任务级状态枚举（5 态，逐字镜像 RepoResearchTaskStatus）。"""

    PENDING = "pending", "待派发"
    RUNNING = "running", "校验中"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"
    STALE = "stale", "已过期"


class RepoVerifyTask(models.Model):
    """per-repo 容器深验任务 + verdict（D-02，逐字镜像 RepoResearchTask 形状）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次关联编排；删关联级联删其校验子任务（一关联多 per-repo 校验任务）
    association = models.ForeignKey(
        RepoAssociation,
        on_delete=models.CASCADE,
        related_name="verify_tasks",
    )
    # 被校验仓（跨 app 真实 FK）；related_name="+" 不污染 Repository 反查
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # dispatch 容器后回填；删容器会话不删 task（SET_NULL，镜像 RepoResearchTask）
    subagent_session = models.ForeignKey(
        "subagent.SubAgentSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=RepoVerifyTaskStatus.choices,
        default=RepoVerifyTaskStatus.PENDING,
    )
    # 单仓重试计数（fail-soft 隔离重试）
    attempt = models.IntegerField(default=0)
    # 失败结构化诊断
    error = models.JSONField(default=dict, blank=True)
    # 容器 explore 产出的适配性裁决（server 解析）；schema:
    # {fit, confidence, summary, evidence_files, mismatch_reasons}
    verdict = models.JSONField(default=dict, blank=True)
    initiated_by_user_id = models.CharField(max_length=64, blank=True, default="system")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_repo_verify_task"
        verbose_name = "仓库校验子任务"
        verbose_name_plural = "仓库校验子任务"
        indexes = [
            models.Index(fields=["association", "status"]),
            models.Index(fields=["repository"]),
        ]

    def __str__(self) -> str:
        return f"RepoVerifyTask({self.id}, {self.status})"
