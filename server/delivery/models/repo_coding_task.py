"""多仓 wave 编码子任务模型（DOMAIN §6 / §14，Phase 44 WAVE-01）。

立 v0.8 多仓 wave 编码「操作态脊柱 + 拓扑调度」的数据底座：

- **``RepoCodingTask``**：每仓一个编码子任务，子任务级状态机
  ``pending → running → done|failed``（DOMAIN §6/§14；**不含** ``stale`` ——stale 是调研
  期重索引语义，编码期无）。``plan_version`` 归属一次方案版本（真实 FK，区别于
  ``PlanSession.current_plan_version`` 的软 UUID 引用），``repository`` 指向被编码仓（跨
  app 真实 FK——repositories 是稳定基础 app），``subagent_session`` 在 dispatch 容器后
  回填（删容器会话不删 task）。``wave`` 承载拓扑层级（service 按依赖分层算法写入），
  ``depends_on`` 是有向 DAG 的仓级依赖边（``symmetrical=False`` self-M2M）。
  ``attempt`` 计数承载单仓重试，``error`` 落结构化失败诊断。
  ``produced_artifacts`` / ``follow_openspec`` 为后续 phase 预留扩展位（本 phase 仅立
  字段，不消费）。

设计要点（守 INV-6 精神）：状态变更/落库/wave 推进**只经 ``RepoCodingTaskService``**
（plan 03），本模型层**不写**任何 create/save/状态变更/校验业务方法（仅 ``__str__``）；
旁路写表由 INV-6 grep 守护断言。跨 app FK 用字符串前向引用避免 import 环。
"""

import uuid

from django.db import models


class RepoCodingTaskStatus(models.TextChoices):
    """RepoCodingTask 子任务级状态枚举（4 态，逐字对齐 DOMAIN §6/§14）。

    编码期无重索引语义，故**不含**调研期的 ``stale`` 态。
    """

    PENDING = "pending", "待派发"
    RUNNING = "running", "编码中"
    DONE = "done", "已完成"
    FAILED = "failed", "失败"


class RepoCodingTask(models.Model):
    """每仓 wave 编码子任务（子任务级状态机 + 拓扑调度 + 可靠恢复底座，DOMAIN §6/§14）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 ArtifactVersion（technical_plan 产物版本，真实 FK）；删产物版本级联删其编码子任务。
    # null=True：P2 破坏性重建期由 ArtifactVersion 取代旧 PlanVersion FK，无存量数据，
    # 置空避免迁移 one-off default；实际建任务恒由 RepoCodingTaskService 传入非空版本。
    artifact_version = models.ForeignKey(
        "delivery.ArtifactVersion",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coding_tasks",
    )
    # 被编码仓（跨 app 真实 FK，repositories 是稳定基础 app）；related_name="+" 不污染
    # Repository 反查
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # 拓扑层级（0-based）；由 service 在建任务时按拓扑分层算法计算写入
    wave = models.IntegerField(default=0)
    # 有向 DAG 仓级依赖边（symmetrical=False self-M2M）；正查 depends_on / 反查 dependents
    depends_on = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependents",
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
        choices=RepoCodingTaskStatus.choices,
        default=RepoCodingTaskStatus.PENDING,
    )
    # 上游产物（本 phase 仅立字段，内容提取/下游注入留 Phase 45 ARTIFACT-01/02）
    produced_artifacts = models.JSONField(default=dict, blank=True)
    # SDD 扩展点预留位（本 phase 不消费；v0.9 才注入 openspec system prompt）
    follow_openspec = models.BooleanField(default=False)
    # 重试计数（单仓重试不重跑整 session）
    attempt = models.IntegerField(default=0)
    # 失败结构化诊断
    error = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_repo_coding_task"
        verbose_name = "仓库编码子任务"
        verbose_name_plural = "仓库编码子任务"
        indexes = [
            models.Index(fields=["artifact_version", "wave", "status"]),
            models.Index(fields=["repository"]),
        ]

    def __str__(self) -> str:
        return f"RepoCodingTask({self.id}, w{self.wave}, {self.status})"
