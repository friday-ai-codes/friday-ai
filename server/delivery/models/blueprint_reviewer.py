"""蓝图方案评审人名单模型（Phase 111，DESIGN §6.4）。

任何成员在蓝图上执行过「确认」类动作（仓库确认门确认、终审通过/驳回）即自动
进入名单；``first_action`` 只在首插时留痕（重复确认不覆盖），也可手动增补
（``first_action="manual_add"``）。名单用于操作留痕/署名与后续通知送达。

设计要点（守 INV-6 精神）：唯一 writer = ``BlueprintLifecycleService``
（``aget_or_create`` upsert）；本模型层零业务方法，旁路写表由
``test_blueprint_inv6_guard`` 源码扫描锁死。
"""

import uuid

from django.conf import settings
from django.db import models


class BlueprintReviewer(models.Model):
    """蓝图 ↔ 用户 的方案评审人关联（artifact+user 唯一）。"""

    objects: "models.Manager[BlueprintReviewer]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(
        "delivery.Artifact",
        on_delete=models.CASCADE,
        related_name="blueprint_reviewers",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    # 首次确认动作留痕（取值示例 repo_confirmation/final_approve/final_reject/manual_add，
    # 开放字符串）；aget_or_create 保证只在首插写入
    first_action = models.CharField(max_length=32)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_blueprint_reviewer"
        verbose_name = "蓝图评审人"
        verbose_name_plural = "蓝图评审人"
        constraints = [
            models.UniqueConstraint(
                fields=["artifact", "user"],
                name="uq_blueprint_reviewer_artifact_user",
            ),
        ]

    def __str__(self) -> str:
        return f"BlueprintReviewer({self.artifact_id}, {self.user_id})"
