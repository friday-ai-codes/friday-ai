"""access_tokens app models —— Friday Access Token。

外部 MCP/Skill 调用的统一鉴权凭证（contract single token：有效即全权限，
不做 scope / project / allowlist 分权）。

明文绝不落盘（contract / contract）：仅在 create 响应一次性返回明文，DB 只存
``token_hash``（复用 ``runners.models.hash_token`` 同一 sha256 算法）+ ``token_prefix``
（明文前 12 字符，供 UI 识别）+ 元数据。
"""

import secrets
import uuid

from django.db import models
from django.utils import timezone

# 复用 runners 同一 sha256 哈希（contract 锁定，禁止重写）。
from runners.models import hash_token

# 明文 token 前缀，对齐 GitHub PAT 习惯，便于日志/密钥扫描器识别。
PAT_PREFIX = "friday_pat_"


def generate_pat() -> str:
    """生成 Friday Access Token 明文（friday_pat_ 前缀 + 256bit 高熵随机串）。"""
    return f"{PAT_PREFIX}{secrets.token_urlsafe(32)}"


class AccessToken(models.Model):
    """Friday Access Token —— 外部入口唯一鉴权凭证。

    生命周期：创建（一次性明文）→ 使用（节流更新 last_used_at）→ 软吊销
    （revoked_at，保留审计记录不物理删除）。过期策略：``expires_at=None`` 表示
    永不过期。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    # sha256(明文) hex，唯一索引供 O(1) 精确匹配；绝不存明文（contract）。
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    # 明文前 12 字符，供 UI 识别（非敏感，不可反推明文）。
    token_prefix = models.CharField(max_length=20, default="")
    # 可选备注；空串=历史 token 无备注。
    note = models.CharField(max_length=500, blank=True, default="")
    # 明文后 4 字符，与 token_prefix 对称形成 friday_pat_xxx…abcd 指纹（非敏感）。
    # max_length=8 留头部冗余，实际仅存 4 字符。
    token_suffix = models.CharField(max_length=8, default="")
    # token 种类（Phase 103 AGENT-01）：
    #   - personal：用户手动创建的长期 PAT（默认，存量行为零变化——认证类
    #     AccessTokenAuthentication 不读本字段，前缀闸门 + sha256 查表逻辑不变）。
    #   - task：派发编码任务时按 session 铸造的短 TTL token（services.mint_task_token），
    #     expires_at = 任务 timeout + 余量，任务终态按 session_id 幂等吊销。
    # 兼容承诺：存量行未迁移 kind 恒为 personal；认证/序列化/吊销 API 均不区分 kind。
    kind = models.CharField(
        max_length=16,
        choices=[("personal", "Personal"), ("task", "Task")],
        default="personal",
        db_index=True,
    )
    # 任务 token 关联的 subagent session_id（kind=task 时非空；personal token 恒 None）。
    # 终态吊销按 (kind="task", session_id) 精确定位（services.arevoke_task_tokens）。
    session_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="access_tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # null = 永不过期。
    expires_at = models.DateTimeField(null=True, blank=True)
    # 软吊销时间戳；非 null 即视为已吊销。
    revoked_at = models.DateTimeField(null=True, blank=True)
    # 最近一次成功认证时间（节流更新，best-effort）。
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "access_tokens"
        indexes = [
            models.Index(fields=["created_by", "-created_at"]),
        ]
        ordering = ["-created_at"]

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and timezone.now() > self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired

    def __str__(self) -> str:
        return f"AccessToken {self.name} ({'valid' if self.is_valid else 'invalid'})"
