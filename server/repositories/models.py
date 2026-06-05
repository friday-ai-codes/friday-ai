"""Repositories models: Repository and GitCredential."""

import uuid
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from workflows.models.coding_task import CodingTask


class GitPlatform(models.TextChoices):
    """Git platform choices."""

    GITHUB = "github", "GitHub"
    GITLAB = "gitlab", "GitLab"
    GITEA = "gitea", "Gitea"
    BITBUCKET = "bitbucket", "Bitbucket"


class AuthType(models.TextChoices):
    """Authentication type choices."""

    SSH_KEY = "ssh_key", "SSH Key"
    ACCESS_TOKEN = "access_token", "Access Token"
    DEPLOY_KEY = "deploy_key", "Deploy Key"


class IndexStatus(models.TextChoices):
    """Index status choices."""

    NOT_INDEXED = "not_indexed", "未索引"
    INDEXING = "indexing", "索引中"
    INDEXED = "indexed", "已索引"
    FAILED = "failed", "索引失败"
    CANCELLED = "cancelled", "已停止"


class BranchIndexStatus(models.TextChoices):
    """分支索引状态。"""

    NOT_INDEXED = "not_indexed", "未索引"
    INDEXING = "indexing", "索引中"
    INDEXED = "indexed", "已索引"
    INHERITED = "inherited", "继承自基础分支"
    FAILED = "failed", "索引失败"
    UPGRADING = "upgrading", "升级中"


class TriggerType(models.TextChoices):
    """索引触发类型。"""

    MANUAL = "manual", "手动触发"
    WEBHOOK = "webhook", "Webhook 触发"
    SCHEDULED = "scheduled", "定时触发"


class IndexHistoryStatus(models.TextChoices):
    """索引历史记录状态。"""

    PENDING = "pending", "等待中"
    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已停止"


class GraphBuildStatus(models.TextChoices):
    """GraphRAG 增量构建状态（initial implementation contract）。

    与 IndexHistoryStatus 互相独立——前者描述本次索引对应的 graph
    enrichment 阶段（ChunkEdge 构建 + payload 同步），后者描述整体索引流程。
    """

    PENDING = "pending", "等待中"
    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "已跳过"


class GraphBuildHistoryStatus(models.TextChoices):
    """独立 graph 构建生命周期 4 态（initial implementation-03）。

    与 IndexHistoryStatus / GraphBuildStatus 均独立——本枚举描述顶层
    `services/graph_builder.py` 的构建生命周期；**不引入 pending 态**：
    创建即 RUNNING（per initial implementation CONTEXT 决议），省一态简化测试与未来
    SSE 终止判定，与 ROADMAP success criterion/success criterion 的 4 态对齐。
    """

    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已停止"


class GraphBuildHistoryTrigger(models.TextChoices):
    """独立 graph 构建触发来源 3 态（initial implementation-03）。

    - MANUAL：REST `POST /codegraph/rebuild/` 用户显式触发
    - AUTO_AFTER_INDEX：indexer 主流程在 `_extract_and_write_graph` 前后包裹
    - WEBHOOK：仅占位，initial implementation 范围内无 view 路径产生该值（webhook 接入留 legacy.2+）
    """

    MANUAL = "manual", "手动触发"
    AUTO_AFTER_INDEX = "auto_after_index", "索引完成自动触发"
    WEBHOOK = "webhook", "Webhook 触发"


class RepositoryGraphStatus(models.TextChoices):
    """Repository 上的图谱当前态 5 态（initial implementation-01）。

    与 ``GraphBuildHistoryStatus`` 4 态独立——后者描述 history 行（创建即 RUNNING，
    不引入 pending/idle），前者描述仓库聚合态：必须有 ``IDLE`` 默认值表示"从未
    构建过"或"两次构建之间空闲"。4 个运行态字符串（running/completed/failed/
    cancelled）与 ``GraphBuildHistoryStatus`` 完全对齐，便于 view 层 1:1 映射。

    CONTEXT 决议（initial implementation Grey Area 1）：不引入 pending / skipped。
    """

    IDLE = "idle", "未构建"
    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已停止"


class AISummaryStatus(models.TextChoices):
    """AI 描述生成状态。"""

    NOT_STARTED = "not_started", "未生成"
    PENDING = "pending", "等待中"
    RUNNING = "running", "生成中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "生成失败"


class Repository(models.Model):
    """Repository model for Git repositories."""

    # 反向关系类型声明
    coding_tasks: "QuerySet[CodingTask]"
    credential: "GitCredential"
    index_history: "QuerySet[IndexHistory]"
    file_indexes: "QuerySet[FileIndex]"
    branch_indexes: "QuerySet[RepositoryBranchIndex]"
    graph_build_histories: "QuerySet[GraphBuildHistory]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    git_url = models.CharField(max_length=500)
    git_platform = models.CharField(
        max_length=20,
        choices=GitPlatform.choices,
        default=GitPlatform.GITLAB,
    )
    default_branch = models.CharField(max_length=100, default="main")
    description = models.TextField(blank=True, null=True)
    proxy_url = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="HTTP proxy URL for Git operations (e.g. http://proxy.example.com:8080)",
    )
    base_branch = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="索引基础分支，为空时回退到 default_branch",
    )

    # Index status fields
    index_status = models.CharField(
        max_length=20,
        choices=IndexStatus.choices,
        default=IndexStatus.NOT_INDEXED,
    )
    last_indexed_at = models.DateTimeField(blank=True, null=True)
    index_error = models.TextField(blank=True, null=True)
    # Progress tracking - embedding generation
    index_total_chunks = models.IntegerField(default=0)
    index_processed_chunks = models.IntegerField(default=0)
    # Progress tracking - Qdrant write
    index_write_total = models.IntegerField(default=0)
    index_write_processed = models.IntegerField(default=0)
    # 当前正在执行的索引子阶段（克隆 / 对比 / 解析 / embedding / 写入向量库 / 图谱 / 完成）
    # 为空时由 _compute_index_progress 用进度计数器推断 fallback 阶段
    index_stage = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="索引当前阶段，由 indexer 各阶段开始时 update",
    )
    # 文件级实时进度（contract）：indexer 解析/写入每个文件前都会刷新这几个字段，
    # 供前端"当前正在索引哪个文件 / 已处理 N 个"展示
    current_indexing_file = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        help_text="当前正在索引的文件相对路径，空字符串表示无活动文件",
    )
    indexed_files_processed = models.IntegerField(
        default=0,
        help_text="本次索引已处理的文件数（accumulated counter）",
    )
    indexed_files_total = models.IntegerField(
        default=0,
        help_text="本次索引预计要处理的文件总数（解析阶段确定后写入）",
    )
    # 增量索引与自动触发字段
    last_indexed_commit_sha = models.CharField(max_length=40, blank=True, null=True)
    auto_index_enabled = models.BooleanField(default=False)
    # initial implementation-01：per-repo 自动构图开关，默认 True 保向后兼容。
    # indexer 主流程会在 _extract_and_write_graph 调用前以
    # `settings.ENABLE_CODEGRAPH AND auto_build_graph_enabled` 双重判断决定是否跳过
    # （双重判断落在 plan；本字段在 plan 单独落地）。
    auto_build_graph_enabled = models.BooleanField(
        default=True,
        help_text="是否自动构建图谱（per-repo 开关，AND settings.ENABLE_CODEGRAPH 决定是否跳过）",
    )
    # initial implementation-01：图谱进度 6 字段（与 index_* 字段并行，彻底解耦
    # 索引文案与图谱文案）。由 `services.indexer.update_graph_progress` helper 按
    # `GRAPH_YIELD_EVERY=25` callsite 节流写入；reset/terminal 由
    # `services.graph_builder.build_graph_for_repository` 主入口 + indexer 4 处
    # callsite 外层（auto_after_index 路径）写。
    graph_build_status = models.CharField(
        max_length=20,
        choices=RepositoryGraphStatus.choices,
        default=RepositoryGraphStatus.IDLE,
        help_text="图谱当前态（initial implementation-01）",
    )
    graph_stage = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="图谱构建当前阶段，由 update_graph_progress 实时刷新",
    )
    current_graph_file = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        help_text="当前正在抽取的文件相对路径，空字符串表示无活动文件",
    )
    graph_files_processed = models.IntegerField(
        default=0,
        help_text="本次图谱构建已处理的文件数",
    )
    graph_files_total = models.IntegerField(
        default=0,
        help_text="本次图谱构建预计处理的文件总数",
    )
    graph_last_built_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最近一次终态（COMPLETED/FAILED/CANCELLED）时间戳",
    )
    webhook_secret = models.CharField(max_length=100, blank=True, null=True)

    # Soft delete fields
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Hash 新鲜度字段（initial implementation contract）
    remote_head_sha = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="远端仓库 HEAD commit SHA，由 poll_repository_updates 顺手缓存",
    )
    remote_head_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="最近一次 git ls-remote 执行时间",
    )

    # STALE commit 差值（initial implementation contract）
    behind_commits = models.IntegerField(
        null=True,
        blank=True,
        help_text="本地索引落后远端的 commit 数，null 表示尚未计算",
    )
    behind_commits_calculated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="behind_commits 最近一次计算时间",
    )

    # AI 描述生成字段（initial implementation）
    ai_summary = models.TextField(null=True, blank=True)
    ai_summary_status = models.CharField(
        max_length=20,
        choices=AISummaryStatus.choices,
        default=AISummaryStatus.NOT_STARTED,
    )
    ai_summary_generated_at = models.DateTimeField(null=True, blank=True)
    ai_summary_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "repositories"
        verbose_name = "仓库"
        verbose_name_plural = "仓库"

    def __str__(self):
        return self.name

    def soft_delete(self) -> None:
        """Mark the repository as deleted."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    async def asoft_delete(self) -> None:
        """Mark the repository as deleted (async version)."""
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        await self.asave(update_fields=["is_deleted", "deleted_at"])


class IndexHistory(models.Model):
    """索引操作历史记录，追踪每次索引的完整元数据。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="index_history",
    )
    trigger_type = models.CharField(max_length=20, choices=TriggerType.choices)
    status = models.CharField(
        max_length=20,
        choices=IndexHistoryStatus.choices,
        default=IndexHistoryStatus.PENDING,
    )
    from_sha = models.CharField(max_length=40, blank=True, null=True)
    to_sha = models.CharField(max_length=40, blank=True, null=True)
    files_added = models.IntegerField(default=0)
    files_modified = models.IntegerField(default=0)
    files_deleted = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    summary_text = models.TextField(blank=True, null=True, help_text="人可读的差异摘要文本")
    # contract（修订 2026-05-11）：contract 变更文件列表持久化
    # 结构：{"added": ["path/to/file.py", ...], "modified": [...], "deleted": [...]}
    # 增量索引完成后由 indexer.py 写入；全量索引时为空 dict {}
    changed_files = models.JSONField(
        default=dict,
        blank=True,
        help_text="增量索引涉及的变更文件路径列表，全量索引时为空",
    )
    # initial implementation contract：GraphRAG 增量构建可观测字段（lifecycle 写入逻辑见 plan）
    graph_build_status = models.CharField(
        max_length=20,
        choices=GraphBuildStatus.choices,
        default=GraphBuildStatus.PENDING,
        help_text="GraphRAG 增量构建状态（pending/running/completed/failed/skipped）",
    )
    edge_count = models.PositiveIntegerField(
        default=0,
        help_text="累计快照：当前 ChunkEdge.objects.filter(repository=repo).count()",
    )
    payload_synced_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="最近一次 payload.related_chunks 同步完成时间",
    )
    # initial implementation：跨仓 API join 可观测字段
    cross_repo_match_count = models.PositiveIntegerField(
        default=0,
        help_text="最近一次 cross_repo offline join 产生的匹配记录总数",
    )
    cross_repo_built_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="最近一次 cross_repo offline join 完成时间",
    )
    # initial implementation：per-run delta 可观测字段
    # 语义与上方累计 edge_count 严格对立——这 5 个字段记录「本次索引」量，
    # 而非全仓库累计快照（Pitfall 7：杜绝把累计 count 误填进 per-run delta）。
    # 用 IntegerField（非 PositiveIntegerField）与 files_added 风格一致，避免负值边界争议。
    #
    # ⚠️ 口径区分（code-review 295 H1）：前 4 个 *_added 取自 GraphWriter.write_bundle
    # 的本次写入量——增量索引按 per-file delete+rebuild，故对「被修改文件」会把该文件
    # 内既有实体也计入（语义=本次重建涉及量，非去重净增）；chunk_edges_added 走
    # bulk_insert_edges(ignore_conflicts) 去重后的 inserted，是真正的净新增。前端文案
    # 用「本次索引」中性措辞，避免把前 4 个的重建量误读为净新增。
    symbols_added = models.IntegerField(
        default=0,
        help_text="本次索引写入/重建的 Symbol 数（per-run，非累计；增量重建文件含其既有符号，非去重净增）",
    )
    imports_added = models.IntegerField(
        default=0,
        help_text="本次索引写入/重建的 ImportEdge 数（per-run，非累计）",
    )
    calls_added = models.IntegerField(
        default=0,
        help_text="本次索引写入/重建的 CallEdge 数（per-run，非累计）",
    )
    endpoints_added = models.IntegerField(
        default=0,
        help_text="本次索引写入/重建的 Endpoint 数（per-run，非累计）",
    )
    chunk_edges_added = models.IntegerField(
        default=0,
        help_text="本次索引净新增 ChunkEdge 数（per-run，去重后 inserted；区别于累计 edge_count）",
    )
    # initial implementation：行级 diff 可观测字段（nullable 三态）
    # 三态语义：真实值（numstat 汇总数）/ 0（无变更或二进制文件）/ null（不可计算）。
    # null=不可计算——全量索引无 from/to SHA diff、或 shallow clone 加深失败时，
    # 绝不把「不可计算」写成 0（Pitfall 6：null 与真实 0 必须可区分，前端据此显示 "—"）。
    lines_added = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="本次增量 +行数；null=不可计算（全量索引/shallow 加深失败），0=无新增或二进制文件",
    )
    lines_deleted = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="本次增量 -行数；null=不可计算（全量索引/shallow 加深失败），0=无删除或二进制文件",
    )
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "index_history"
        ordering = ["-created_at"]
        verbose_name = "索引历史"
        verbose_name_plural = "索引历史"

    def __str__(self) -> str:
        return f"{self.repository.name} - {self.trigger_type} ({self.status})"


class GraphBuildHistory(models.Model):
    """独立图谱构建历史（initial implementation-03）。

    与 `IndexHistory` 同居 repositories app，但描述的是顶层
    `services/graph_builder.py` 的图谱构建生命周期——三种 trigger 一视同仁
    （manual / auto_after_index / webhook），全量持久化以供 list endpoint
    审计与未来排障使用。

    字段口径全部对齐 `IndexHistory`（PK UUIDField、ForeignKey CASCADE、
    started_at/finished_at 双时间字段）。Meta.indexes 提前为 plan 的
    GET `/codegraph/history/?ordering=-started_at` 命中索引。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="graph_build_histories",
    )
    trigger_type = models.CharField(
        max_length=20,
        choices=GraphBuildHistoryTrigger.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=GraphBuildHistoryStatus.choices,
        default=GraphBuildHistoryStatus.RUNNING,
        help_text="创建即 RUNNING——CONTEXT 决议不引入 pending 态",
    )
    # v26.2 contract：分支隔离维度。"" = base 分支（与 codegraph 6 模型同口径），
    # feature 分支由 manual REST `build_graph_for_repository(branch=...)` 归一化后写入，
    # 供 history list endpoint 区分「这次重建跑的是哪个分支」。
    branch_name = models.CharField(max_length=200, default="", blank=True)
    # 文件处理进度计数
    files_total = models.IntegerField(default=0)
    files_processed = models.IntegerField(default=0)
    files_failed = models.IntegerField(default=0)
    # 产物计数（GraphBuildResult 完成时一次性回写）
    symbols_count = models.IntegerField(default=0)
    imports_count = models.IntegerField(default=0)
    calls_count = models.IntegerField(default=0)
    endpoints_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "graph_build_history"
        ordering = ["-started_at"]
        verbose_name = "图谱构建历史"
        verbose_name_plural = "图谱构建历史"
        indexes = [
            models.Index(
                fields=["repository", "-started_at"],
                name="idx_gbh_repo_started",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.repository.name} - {self.trigger_type} ({self.status})"


class FileIndex(models.Model):
    """文件级索引记录——DB 级幂等性保障，替代 Qdrant hash 比较。

    通过 unique_together(repository, file_path) 约束确保多进程部署下
    同一文件不会被重复索引。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="file_indexes",
    )
    file_path = models.CharField(max_length=1000)
    file_hash = models.CharField(max_length=64)
    indexed_at = models.DateTimeField(auto_now=True)
    # 该文件自身最近一次 git commit 的 SHA 与时间，由 indexer 在写入时通过
    # `git log -1 --format=%H|%ct -- <file>` 查询并填入。
    # 用于"已索引文件清单"展示文件级新鲜度，独立于整次索引的 to_sha。
    last_commit_sha = models.CharField(max_length=40, blank=True, default="")
    last_commit_authored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "file_indexes"
        verbose_name = "文件索引记录"
        verbose_name_plural = "文件索引记录"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "file_path"],
                name="uq_repo_file_path",
            ),
        ]
        indexes = [
            models.Index(
                fields=["repository", "file_path"],
                name="idx_repo_file_path",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.file_path} ({self.file_hash[:8]})"


class GitCredential(models.Model):
    """Git credential model for authentication."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.OneToOneField(
        Repository,
        on_delete=models.CASCADE,
        related_name="credential",
    )
    auth_type = models.CharField(
        max_length=20,
        choices=AuthType.choices,
        default=AuthType.ACCESS_TOKEN,
    )
    ssh_key_encrypted = models.TextField(blank=True, null=True)
    encrypted_token = models.TextField(blank=True, null=True)
    git_user_name = models.CharField(max_length=200, default="Friday Codes AI Agent")
    git_user_email = models.CharField(max_length=200, default="ai@friday.codes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "git_credentials"
        verbose_name = "Git 凭证"
        verbose_name_plural = "Git 凭证"

    def __str__(self):
        return f"Credential for {self.repository.name}"


class RepositoryBranchIndex(models.Model):
    """分支索引记录——追踪每个分支的索引状态与 overlay collection 映射。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="branch_indexes",
    )
    branch_name = models.CharField(max_length=200)
    is_base_branch = models.BooleanField(default=False)
    head_sha = models.CharField(max_length=40, blank=True, null=True)
    merge_base_sha = models.CharField(max_length=40, blank=True, null=True)
    last_indexed_commit_sha = models.CharField(max_length=40, blank=True, null=True)
    last_indexed_at = models.DateTimeField(blank=True, null=True)
    is_stale = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=BranchIndexStatus.choices,
        default=BranchIndexStatus.NOT_INDEXED,
    )
    effective_chunks_count = models.IntegerField(default=0)
    collection_name = models.CharField(max_length=300, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "repository_branch_indexes"
        verbose_name = "分支索引"
        verbose_name_plural = "分支索引"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "branch_name"],
                name="uq_repo_branch",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.repository.name}:{self.branch_name} ({self.status})"


class BranchFileIndex(models.Model):
    """分支内文件级变更记录——追踪 overlay 中每个文件的变更类型。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch_index = models.ForeignKey(
        RepositoryBranchIndex,
        on_delete=models.CASCADE,
        related_name="file_indexes",
    )
    file_path = models.CharField(max_length=1000)
    change_type = models.CharField(max_length=20)
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "branch_file_indexes"
        verbose_name = "分支文件索引"
        verbose_name_plural = "分支文件索引"
        constraints = [
            models.UniqueConstraint(
                fields=["branch_index", "file_path"],
                name="uq_branch_file",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.file_path} ({self.change_type})"
