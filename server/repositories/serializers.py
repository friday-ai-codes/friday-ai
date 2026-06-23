"""Repositories serializers."""

import fnmatch
import re

from rest_framework import serializers

from services.exclusion import is_redos_risky

from .models import (
    CleanupRun,
    GitCredential,
    GitInstanceCredential,
    GitPlatform,
    RepoExclusionRule,
    Repository,
    SensitiveFileSuggestion,
)

# SSH 仓库地址的两种形态：scp 风格（git@host:group/repo.git）与
# ssh:// 协议（ssh://git@host[:port]/group/repo.git，端口为 ssh 端口需丢弃）。
_SSH_SCP_RE = re.compile(r"^git@([^:/]+):(.+)$")
_SSH_URL_RE = re.compile(r"^ssh://(?:[^@/]+@)?([^:/]+)(?::\d+)?/(.+)$")


def ssh_git_url_to_https(git_url: str) -> str:
    """把 SSH 形式的仓库地址转换为 HTTPS（非 SSH 形式原样返回）。

    任务容器内没有 ssh，git clone SSH 地址必然失败（"cannot run ssh"）；
    Access Token 认证也只兼容 HTTPS。在所有入口做自动转换，
    存量数据由 repositories.0031 迁移统一改写。
    """
    url = git_url.strip()
    match = _SSH_SCP_RE.match(url) or _SSH_URL_RE.match(url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    return url


def validate_https_git_url(git_url: str) -> str:
    """归一化为 HTTPS 仓库地址：SSH 形式自动转换，其余非 http(s) 拒绝。"""
    git_url = ssh_git_url_to_https(git_url)
    if not git_url.startswith(("http://", "https://")):
        raise serializers.ValidationError(
            "当前仅支持 HTTPS 仓库 URL（SSH 地址会自动转换为 HTTPS）。"
        )
    return git_url


class RepositorySerializer(serializers.ModelSerializer):
    """Serializer for Repository model."""

    has_credential = serializers.SerializerMethodField()
    linked_spaces_count = serializers.SerializerMethodField()
    # SDD-02（48-02）：从 facets["methodology"] 派生的只读方法论字段（无 facets 时为 null），
    # 让标准 /repositories 列表/详情也能透出 SDD 标记（不仅限知识树）。
    methodology = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = [
            "id",
            "name",
            "git_url",
            "git_platform",
            "default_branch",
            "base_branch",
            "remote_head_branch",
            "proxy_url",
            "auto_index_enabled",
            "auto_build_graph_enabled",
            "webhook_secret",
            "index_status",
            "last_indexed_at",
            "created_at",
            "updated_at",
            "has_credential",
            "linked_spaces_count",
            "methodology",
            "ai_summary",
            "ai_summary_status",
            "ai_summary_generated_at",
            "ai_summary_error",
            # contract freshness 字段（contract/contract）
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "last_indexed_commit_sha",
            # implementation-01：图谱进度 6 字段（全 read-only，由
            # 后端 indexer / graph_builder 控写；auto_build_graph_enabled
            # implementation 已暴露为 read-write，不在此列）。
            "graph_build_status",
            "graph_stage",
            "current_graph_file",
            "graph_files_processed",
            "graph_files_total",
            "graph_last_built_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "remote_head_branch",
            "webhook_secret",
            "index_status",
            "last_indexed_at",
            "ai_summary",
            "ai_summary_status",
            "ai_summary_generated_at",
            "ai_summary_error",
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "last_indexed_commit_sha",
            "graph_build_status",
            "graph_stage",
            "current_graph_file",
            "graph_files_processed",
            "graph_files_total",
            "graph_last_built_at",
        ]

    def get_has_credential(self, obj: Repository) -> bool:
        # per-repo 显式凭证
        if hasattr(obj, "credential") and obj.credential is not None:
            return True
        # TOKEN-02：经密钥提供方解析也视为「有凭证」——显式 FK 或 host 自动匹配实例池
        if obj.git_instance_credential_id:
            return True
        from repositories.models import GitInstanceCredential
        from services.git_credentials import _extract_git_host

        host = _extract_git_host(obj.git_url)
        if host:
            return GitInstanceCredential.objects.filter(host=host).exists()
        return False

    def get_methodology(self, obj: Repository) -> str | None:
        """从 facets 派生只读 methodology（如 "SDD"）；无 facets 或未打标时为 None。"""
        return (obj.facets or {}).get("methodology")

    def get_linked_spaces_count(self, obj: Repository) -> int:
        """返回关联到此仓库的空间数量。"""
        return obj.projects.count()

    def validate_git_url(self, value: str) -> str:
        return validate_https_git_url(value)


class RepositoryCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating Repository with credential.

    space_ids 必填且至少一个：所有仓库都必须关联到至少一个空间。
    """

    # TOKEN-02：access_token 改为可选——可填自有 token，或经 git_instance_credential_id
    # 选择「密钥提供方」(实例凭证)，或 host 自动匹配实例池。三者皆无时核心 helper 报错。
    access_token = serializers.CharField(write_only=True, required=False, allow_blank=True, default="")
    # TOKEN-01：显式选择密钥提供方（实例凭证）。可空。
    git_instance_credential_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )
    git_user_name = serializers.CharField(default="Friday Codes AI Agent")
    git_user_email = serializers.CharField(default="ai@friday.codes")
    space_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        allow_empty=False,
        error_messages={"empty": "仓库必须至少关联一个空间"},
    )
    # 前端从 test-connection 的 head_branch 带入（display-only 缓存字段）
    remote_head_branch = serializers.CharField(required=False, allow_blank=True, max_length=100)

    class Meta:
        model = Repository
        fields = [
            "name",
            "git_url",
            "git_platform",
            "default_branch",
            "base_branch",
            "remote_head_branch",
            "proxy_url",
            "access_token",
            "git_instance_credential_id",
            "git_user_name",
            "git_user_email",
            "space_ids",
        ]

    def validate_git_url(self, value: str) -> str:
        return validate_https_git_url(value)


class RepositoryWithSpacesSerializer(RepositorySerializer):
    """Serializer for Repository with associated spaces."""

    spaces = serializers.SerializerMethodField()

    class Meta(RepositorySerializer.Meta):
        fields = RepositorySerializer.Meta.fields + ["spaces"]

    def get_spaces(self, obj):
        return [{"id": str(p.id), "name": p.name} for p in obj.projects.all()]


class RepoExclusionRuleSerializer(serializers.ModelSerializer):
    """per-repo 排除规则序列化器（Plan 22-05）。

    保存时 fail-loud 校验（对齐 D-02 / T-22-17）：
    - ``rule_type=regex`` 用 ``re.compile`` 校验语法，非法 → 400 ValidationError（不写库）。
    - ``rule_type=regex`` 额外做 ReDoS 静态启发式（``is_redos_risky``）拒绝嵌套量词模式。
    - pattern 非空 + 长度上限（限制资源占用，**不能**防 ReDoS——见 HI-01；
      ReDoS 由 ``is_redos_risky`` 拒绝嵌套量词把控，长度上限对 ``(a+)+`` 这类短模式无效）。

    ``source`` 可写但默认 ``user``；``source=global + enabled=False`` 为「关闭某条全局
    默认」的 override 标记（视图据此与匹配器同源剔除）。
    """

    class Meta:
        model = RepoExclusionRule
        fields = ["id", "pattern", "rule_type", "enabled", "source", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_pattern(self, value: str) -> str:
        v = (value or "").strip()
        if not v:
            raise serializers.ValidationError("规则模式不能为空")
        if len(v) > 500:
            raise serializers.ValidationError("规则模式过长（最多 500 字符）")
        return v

    def validate(self, attrs: dict) -> dict:
        rule_type = attrs.get("rule_type") or RepoExclusionRule.RuleType.GLOB
        pattern = attrs.get("pattern", "")
        if rule_type == RepoExclusionRule.RuleType.REGEX:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise serializers.ValidationError({"pattern": f"非法正则表达式：{exc}"}) from exc
            # HI-01：拒绝嵌套量词的 ReDoS 高风险模式（长度上限无法防短的灾难性回溯）。
            if is_redos_risky(pattern):
                raise serializers.ValidationError(
                    {"pattern": "正则含嵌套量词，可能触发灾难性回溯（ReDoS），已拒绝"}
                )
        elif rule_type == RepoExclusionRule.RuleType.GLOB:
            # ME-03：glob 也 fail-loud 预校验（fnmatch.translate + re.compile），
            # 避免非法 glob 入库后令该仓库匹配器每次构造都跳过该条/告警。
            try:
                re.compile(fnmatch.translate(pattern))
            except re.error as exc:
                raise serializers.ValidationError({"pattern": f"非法 glob 规则：{exc}"}) from exc
        return attrs


class SensitiveFileSuggestionSerializer(serializers.ModelSerializer):
    """敏感文件 AI 识别建议序列化器（Plan 24-03，EXCL-03）。

    建议由检测器（``services/sensitive_detect.py``）产出，API 层**只读**：所有字段
    ``read_only``，状态仅经专用 accept/dismiss action 变更，不允许直接 PATCH 任意字段
    （越权改 status / 篡改建议，T-24-09 / T-24-10）。

    - ``reason`` 已脱敏：只含命中类型与行号，**绝不**回显密钥本体 / 命中文本原值
      （DOMAIN §9 D-04，T-24-01 / T-24-11）。
    - ``severity`` 取值 ``real_secret`` > ``likely_sensitive`` > ``config_review``，
      列表按此优先级排序（real_secret 优先），供前端高优先展示真实密钥命中。
    """

    class Meta:
        model = SensitiveFileSuggestion
        fields = [
            "id",
            "path",
            "severity",
            "detector",
            "reason",
            "status",
            "detected_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReconcileReportSerializer(serializers.Serializer):
    """对账结果出参（Plan 23-02，EXCL-06 / W3）。

    序列化 ``services.purge_reconcile.ReconcileReport`` 数据类；``degraded`` / ``error``
    必须随响应贯通到前端，使「匹配器构造失败 → 对账不可信」如实可见（W3，不谎报已一致）。
    """

    indexed_count = serializers.IntegerField()
    excluded_paths = serializers.ListField(child=serializers.CharField())
    match_count = serializers.IntegerField()
    suggested_mode = serializers.CharField()
    degraded = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True)


class CleanupRequestSerializer(serializers.Serializer):
    """清理请求入参（Plan 23-02）：``mode`` ∈ {normal, sensitive}，默认 normal。"""

    mode = serializers.ChoiceField(
        choices=["normal", "sensitive"],
        required=False,
        default="normal",
    )


class CleanupRunSerializer(serializers.ModelSerializer):
    """清理运行记录出参（Plan 23-02，W1/W2）。

    ``sensitive`` 原样透传 23-03 ``purge_sensitive_planes`` 返回 dict（含各面计数 +
    unscrubbed + caveat），使后台敏感清理「哪些面未清」如实回流前端，不靠静态文案。
    """

    class Meta:
        model = CleanupRun
        fields = [
            "id",
            "mode",
            "status",
            "match_count",
            "failures",
            "sensitive",
            "started_at",
            "completed_at",
            "error",
        ]
        read_only_fields = fields


class GitCredentialSerializer(serializers.ModelSerializer):
    """Serializer for GitCredential model."""

    has_ssh_key = serializers.SerializerMethodField()
    has_access_token = serializers.SerializerMethodField()

    class Meta:
        model = GitCredential
        fields = [
            "id",
            "repository_id",
            "auth_type",
            "git_user_name",
            "git_user_email",
            "created_at",
            "has_ssh_key",
            "has_access_token",
        ]
        read_only_fields = ["id", "created_at"]

    def get_has_ssh_key(self, obj):
        return bool(obj.ssh_key_encrypted)

    def get_has_access_token(self, obj):
        return bool(obj.encrypted_token)


class GitInstanceCredentialSerializer(serializers.ModelSerializer):
    """实例级 Git 凭证只读序列化器（Plan 26-04，REPO-01，D-04）。

    安全契约：**绝不**包含 ``encrypted_token`` / 任何明文 token 字段；token 是否
    已配置仅以布尔 ``has_token`` 暴露（威胁 T-26-13）。所有 CRUD 响应统一经本序列化器，
    确保 API 出口无明文 token。
    """

    has_token = serializers.SerializerMethodField()

    class Meta:
        model = GitInstanceCredential
        fields = [
            "id",
            "host",
            "provider",
            "label",
            "has_token",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_token(self, obj) -> bool:
        return bool(obj.encrypted_token)


class GitInstanceCredentialWriteSerializer(serializers.Serializer):
    """实例级 Git 凭证写入序列化器（Plan 26-04）。

    - ``access_token`` 为 ``write_only``：仅入站、绝不回显（威胁 T-26-15）；视图侧
      ``encrypt_value`` 加密后存入 ``encrypted_token``（威胁 T-26-14）。
    - ``host`` 归一为小写并去空白，与 ``services.git_credentials._extract_git_host``
      的解析口径一致，确保仓库按 host 命中实例凭证。唯一性由 DB 约束兜底，视图层
      给中文友好报错。
    - 创建时 ``host`` / ``access_token`` 必填（视图校验）；更新（partial）时 ``host``
      可省略、``access_token`` 留空表示「不修改既有 token」。
    """

    host = serializers.CharField(max_length=255, required=False)
    provider = serializers.ChoiceField(
        choices=GitPlatform.choices,
        required=False,
        default=GitPlatform.GITLAB,
    )
    label = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    access_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=True
    )

    def validate_host(self, value: str) -> str:
        v = (value or "").strip().lower()
        if not v:
            raise serializers.ValidationError("Git 实例 host 不能为空")
        return v
