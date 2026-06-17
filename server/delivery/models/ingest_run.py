"""一键摄取编排单次运行的持久化模型（Phase 32-01，ING-01）。

一键摄取在后台异步执行（32-02 编排），REST 立即返回 ``run_id``，前端经状态端点
（32-03）轮询进度/结果；故每次摄取落一条 ``IngestRun``，承载三步（工作项 / 文档 /
MR diff）的结构化结果供如实展示（不靠静态文案）。

落库范式（对齐 §1.4 best-effort 降级 + ``CleanupRun`` run-state 范式）：

- **append-then-update 单行**：编排逐步刷新 ``steps`` 与终态（running → completed/
  failed），不为每步另立行。
- **best-effort 步级隔离**：任一步失败只落该步 ``steps[*].status="failed"`` + 步级
  ``error``，**不整体回滚**其余步骤（部分摄取 + 结构化结果）。
- ``error`` 为编排级致命失败摘要（best-effort 步级错误落 ``steps``）。

**脱敏契约（T-32-02）**：``error`` / ``steps[*].error`` 为纯文本载体，模型层不做
脱敏；写入侧（32-02 编排）负责落库前脱敏（复用 ``WorkItemService._redact_secrets``
范式）。

``(-started_at)`` 索引供「取最近一次」查询。
"""

import uuid

from django.db import models

_STEP_KEYS = ("work_item", "document", "mr_diff")


def default_steps() -> dict[str, dict[str, str]]:
    """三步初始结构（全 ``pending``），作为 ``steps`` 的可调用默认。

    固定形状 ``{work_item, document, mr_diff}``，每步为
    ``{status, identifier, link, error}``（``status`` ∈ pending/ok/failed/skipped）。
    用可调用 default 避免可变默认在实例间共享。
    """
    return {
        key: {"status": "pending", "identifier": "", "link": "", "error": ""}
        for key in _STEP_KEYS
    }


class IngestRun(models.Model):
    """一键摄取编排的单次运行记录（承载三步结构化结果，供 REST 状态轮询）。

    见模块 docstring：append-then-update 单行、best-effort 步级隔离落 ``steps`` 不
    整体回滚（§1.4）。``status`` 与 32-UI-SPEC ``RunStatus`` 严格对齐（无 ``none``——
    run 必经 run_id 命中）。
    """

    class Status(models.TextChoices):
        """运行状态：进行中 / 完成 / 失败。"""

        RUNNING = "running", "进行中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 批量摄取分组键（同一次「批量摄取」派发的多条 run 共享一个 batch_id）。
    # 单条（旧 /ingest/ 端点）留空——批量为可选分组，不引入新表，聚合状态读时计算。
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    # 原始用户输入，留痕（不可信输入，仅记录；解析见 ingest_parsing）
    board_url = models.TextField(blank=True)
    mr_url = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    # 固定形状 {work_item, document, mr_diff}，每步 {status, identifier, link, error}
    steps = models.JSONField(default=default_steps, blank=True)
    # 看板 URL 解析出的项目，留痕；解析不出留 None（SET_NULL 避免删项目抹 run）
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ingest_runs",
    )
    # 编排级致命失败摘要（已脱敏，best-effort 步级错误落 steps）
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_ingest_run"
        verbose_name = "一键摄取运行记录"
        verbose_name_plural = "一键摄取运行记录"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["-started_at"], name="idx_ingest_run_started"),
        ]

    def __str__(self) -> str:
        return f"IngestRun({self.id}, {self.status})"
