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
    """GraphRAG 增量构建状态（implementation contract）。

    与 IndexHistoryStatus 互相独立——前者描述本次索引对应的 graph
    enrichment 阶段（ChunkEdge 构建 + payload 同步），后者描述整体索引流程。
    """

    PENDING = "pending", "等待中"
    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "已跳过"


class GraphBuildHistoryStatus(models.TextChoices):
    """独立 graph 构建生命周期 4 态（implementation-03）。

    与 IndexHistoryStatus / GraphBuildStatus 均独立——本枚举描述顶层
    `services/graph_builder.py` 的构建生命周期；**不引入 pending 态**：
    创建即 RUNNING（per implementation CONTEXT 决议），省一态简化测试与未来
    SSE 终止判定，与 success criterion/success criterion 的 4 态对齐。
    """

    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已停止"


class GraphBuildHistoryTrigger(models.TextChoices):
    """独立 graph 构建触发来源 3 态（implementation-03）。

    - MANUAL：REST `POST /codegraph/rebuild/` 用户显式触发
    - AUTO_AFTER_INDEX：indexer 主流程在 `_extract_and_write_graph` 前后包裹
    - WEBHOOK：仅占位，implementation 范围内无 view 路径产生该值（webhook 接入留 legacy.2+）
    """

    MANUAL = "manual", "手动触发"
    AUTO_AFTER_INDEX = "auto_after_index", "索引完成自动触发"
    WEBHOOK = "webhook", "Webhook 触发"


class RepositoryGraphStatus(models.TextChoices):
    """Repository 上的图谱当前态 5 态（implementation-01）。

    与 ``GraphBuildHistoryStatus`` 4 态独立——后者描述 history 行（创建即 RUNNING，
    不引入 pending/idle），前者描述仓库聚合态：必须有 ``IDLE`` 默认值表示"从未
    构建过"或"两次构建之间空闲"。4 个运行态字符串（running/completed/failed/
    cancelled）与 ``GraphBuildHistoryStatus`` 完全对齐，便于 view 层 1:1 映射。

    CONTEXT 决议（implementation Grey Area 1）：不引入 pending / skipped。
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
    graph_file_indexes: "QuerySet[GraphFileIndex]"
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
    # 远端 HEAD 所在分支（创建 / 测连时 best-effort 探测缓存，供 UI 展示 HEAD 标签）
    remote_head_branch = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="远端仓库 HEAD 指向的分支名，由 ls-remote --symref 探测缓存",
    )
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
    # commit 历史索引（IDX-01）专用增量边界，**独立于上方 last_indexed_commit_sha**
    # （后者是代码 chunk 索引边界，由 _mark_indexed_after_vector 写入）。两者口径不同，
    # 切勿混用：本字段记录 commit 历史已索引推进到的 commit SHA，NULL 表示尚未索引过
    # 任何 commit 历史。index_commits 仅在 upsert 成功后才推进本字段。
    commit_index_boundary_sha = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="commit 历史索引已推进到的 commit SHA（增量边界）；NULL=未索引过 commit 历史",
    )
    auto_index_enabled = models.BooleanField(default=False)
    # implementation-01：per-repo 自动构图开关，默认 True 保向后兼容。
    # indexer 主流程会在 _extract_and_write_graph 调用前以
    # `settings.ENABLE_CODEGRAPH AND auto_build_graph_enabled` 双重判断决定是否跳过
    # （双重判断落在 plan；本字段在 plan 单独落地）。
    auto_build_graph_enabled = models.BooleanField(
        default=True,
        help_text="是否自动构建图谱（per-repo 开关，AND settings.ENABLE_CODEGRAPH 决定是否跳过）",
    )
    # implementation-01：图谱进度 6 字段（与 index_* 字段并行，彻底解耦
    # 索引文案与图谱文案）。由 `services.indexer.update_graph_progress` helper 按
    # `GRAPH_YIELD_EVERY=25` callsite 节流写入；reset/terminal 由
    # `services.graph_builder.build_graph_for_repository` 主入口 + indexer 4 处
    # callsite 外层（auto_after_index 路径）写。
    graph_build_status = models.CharField(
        max_length=20,
        choices=RepositoryGraphStatus.choices,
        default=RepositoryGraphStatus.IDLE,
        help_text="图谱当前态（implementation-01）",
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

    # Hash 新鲜度字段（implementation contract）
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

    # STALE commit 差值（implementation contract）
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

    # AI 描述生成字段（implementation）
    ai_summary = models.TextField(null=True, blank=True)
    ai_summary_status = models.CharField(
        max_length=20,
        choices=AISummaryStatus.choices,
        default=AISummaryStatus.NOT_STARTED,
    )
    ai_summary_generated_at = models.DateTimeField(null=True, blank=True)
    ai_summary_error = models.TextField(blank=True, default="")

    # PageIndex 化能力树字段：
    # ai_summary_tree 存校验通过的嵌套能力树（root 列表，节点含
    # node_id/node_type/title/summary/keywords/paths/children）；
    # 校验失败时保留旧树不覆盖（fail-closed）。
    ai_summary_tree = models.JSONField(null=True, blank=True)
    is_monorepo = models.BooleanField(default=False)
    # 多维分面标签 {dimension: value}；语义分面来自 repo_summary 打标，
    # 事实分面（活跃度/技术栈/关键程度/团队）由 FacetService 自动刷新。
    facets = models.JSONField(default=dict, blank=True)
    # 增量更新状态：{"stale_node_ids": [...], "new_paths": [...], "evaluated_at": iso}
    # webhook 索引完成后由 tree_freshness 维护；树重建成功后清空。
    tree_stale_state = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "repositories"
        verbose_name = "仓库"
        verbose_name_plural = "仓库"

    def __str__(self):
        return self.name

    @property
    def overview_text(self) -> str:
        """对外（agent 工具 / 浏览树）展示用描述：从 ai_summary 提取 overview。

        手动维护的「仓库简介」字段已移除——描述统一来源于 AI 生成的
        ai_summary（JSON 时取 overview 字段，非 JSON 时取原文）。
        """
        import json

        if not self.ai_summary:
            return ""
        try:
            obj = json.loads(self.ai_summary)
            if isinstance(obj, dict):
                return str(obj.get("overview", "") or "")
        except (json.JSONDecodeError, TypeError):
            pass
        return str(self.ai_summary)

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
    # implementation contract：GraphRAG 增量构建可观测字段（lifecycle 写入逻辑见 plan）
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
    # 跨仓 API join 可观测字段
    cross_repo_match_count = models.PositiveIntegerField(
        default=0,
        help_text="最近一次 cross_repo offline join 产生的匹配记录总数",
    )
    cross_repo_built_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="最近一次 cross_repo offline join 完成时间",
    )
    # per-run delta 可观测字段
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
    # 行级 diff 可观测字段（nullable 三态）
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
    """独立图谱构建历史（implementation-03）。

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


class GraphFileIndex(models.Model):
    """图谱级文件断点锚点——记录某分支下已成功写入图谱的文件 hash。

    与 ``FileIndex``（向量轨断点）口径一致，但服务于"图谱构建"轨：
    ``_extract_and_write_graph`` 在 ``GraphWriter.write_bundle`` 成功**之后**
    才 upsert 本行。进程 / Pod 重启后续跑时（skip_unchanged）据此跳过 hash 未变、
    已写入图谱的文件，实现图谱构建的文件级断点恢复。

    branch_name 维度与 codegraph 六模型同口径（""=base 分支）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="graph_file_indexes",
    )
    file_path = models.CharField(max_length=1000)
    file_hash = models.CharField(max_length=64)
    branch_name = models.CharField(max_length=200, default="", blank=True)
    built_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "graph_file_indexes"
        verbose_name = "图谱文件断点"
        verbose_name_plural = "图谱文件断点"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "branch_name", "file_path"],
                name="uq_graph_repo_branch_file",
            ),
        ]
        indexes = [
            models.Index(
                fields=["repository", "branch_name"],
                name="idx_graph_repo_branch",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.file_path}@{self.branch_name or 'base'} ({self.file_hash[:8]})"


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


class GitInstanceCredential(models.Model):
    """Git 实例级凭证池（按 host 维度集中管理，per D-01）。

    设计要点：
    - 同一 Git 实例（host）下的多个仓库复用一份 access token，无需各仓重复粘贴；
    - token 以 Fernet 密文存于 ``encrypted_token``，绝不存明文、绝不进日志；
    - host 唯一约束（存归一化小写 host，含端口若有），避免错配他 host 凭证；
    - 解析优先级（per-repo token 优先 → 实例池 fallback）见 ``services.git_credentials``。

    本阶段聚焦 GitLab，``provider`` 字段保留以便后续扩展其他平台。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="归一化小写 host（含端口若有），如 gitlab.example.com 或 gitlab.example.com:8443",
    )
    provider = models.CharField(
        max_length=20,
        choices=GitPlatform.choices,
        default=GitPlatform.GITLAB,
    )
    encrypted_token = models.TextField(help_text="Fernet 密文 access token，绝不存明文")
    label = models.CharField(max_length=200, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "git_instance_credentials"
        verbose_name = "Git 实例凭证"
        verbose_name_plural = "Git 实例凭证"

    def __str__(self) -> str:
        # 绝不含 token：仅 provider + host
        return f"{self.provider}:{self.host}"


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


class FacetVocabulary(models.Model):
    """语义分面受控词表（PageIndex 化）。

    语义分面（业务线/服务对象/技术形态）的打标只能从本词表选值，
    防止 LLM 自由发挥导致标签碎片化。事实分面（活跃度/技术栈/关键程度/团队）
    由 FacetService 自动计算，不进词表。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dimension = models.CharField(
        max_length=64,
        unique=True,
        help_text="分面维度标识，如 业务线 / 服务对象 / 技术形态",
    )
    values = models.JSONField(
        default=list,
        help_text="该维度的合法取值列表（字符串数组）",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "facet_vocabularies"
        verbose_name = "分面词表"
        verbose_name_plural = "分面词表"

    def __str__(self) -> str:
        return f"{self.dimension} ({len(self.values or [])} values)"


class CorpusTreeSnapshot(models.Model):
    """全局知识树快照（业务域 → 子域 → 仓库归属）。

    tree 结构：[{"id", "title", "summary", "children": [...], "repo_ids": [...]}]
    —— 域/子域节点递归嵌套，叶子域节点带 repo_ids。
    manual_overrides：{repo_id: domain_node_id}，人工 pin 的归属，重建时不可改动。
    同一时刻仅一个 is_active=True 快照；重建写新行再切换，保留历史可回溯。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.IntegerField(default=1)
    tree = models.JSONField(default=list)
    manual_overrides = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    built_by = models.CharField(
        max_length=20,
        default="llm_full",
        help_text="构建方式：llm_full（全量聚类）/ incremental（增量归类）/ manual",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "corpus_tree_snapshots"
        verbose_name = "全局知识树快照"
        verbose_name_plural = "全局知识树快照"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"CorpusTree v{self.version} ({'active' if self.is_active else 'inactive'})"


class RepoExclusionRule(models.Model):
    """per-repo 排除规则（Phase 22 fail-closed 单一事实源之一）。

    规则需可枚举 / 可增删 / 可审计（Phase 23 对账依赖），故落表而非单 JSON 字段。
    有效规则 = 全局默认（BUILTIN_GLOBAL_DEFAULTS ∪ SystemSetting JSON）∪ per-repo 规则；
    其中 ``source="global" + enabled=False`` 的行表示「关闭某条全局默认」的 override 标记，
    匹配器（services/exclusion.py）据此从有效集合中剔除同 pattern 的全局默认。

    仅承诺「被排除文件对 Friday 不可见（fail-closed，INV-4）」，不承诺 git object 物理消失
    （DOMAIN §9.1）。
    """

    class RuleType(models.TextChoices):
        """规则类型：目录前缀 / glob 通配 / 正则（DOMAIN §9 D-02）。"""

        DIR = "dir", "目录前缀"
        GLOB = "glob", "glob 通配"
        REGEX = "regex", "正则"

    class Source(models.TextChoices):
        """规则来源。"""

        USER = "user", "用户配置"
        AI_SUGGESTED = "ai_suggested", "AI 建议"
        GLOBAL = "global", "全局默认 override 标记"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="exclusion_rules",
    )
    pattern = models.CharField(
        max_length=500,
        help_text="规则模式：dir 为目录前缀，glob 为通配模式，regex 为正则（相对仓库根 POSIX）",
    )
    rule_type = models.CharField(
        max_length=16,
        choices=RuleType.choices,
        default=RuleType.GLOB,
    )
    enabled = models.BooleanField(default=True)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.USER,
        help_text="source=global + enabled=False 表示关闭某条全局默认的 override 标记",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "repo_exclusion_rules"
        verbose_name = "仓库排除规则"
        verbose_name_plural = "仓库排除规则"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "rule_type", "pattern", "source"],
                name="uq_repo_exclusion_rule",
            ),
        ]
        indexes = [
            models.Index(
                fields=["repository", "enabled"],
                name="idx_repo_exclusion_enabled",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.repository_id}:{self.rule_type}:{self.pattern} ({self.source})"


class CleanupRun(models.Model):
    """单次清理运行的持久化记录（Phase 23 Plan 02，W1/W2）。

    清理在后台异步执行（D-04），API 立即返回 ``run_id``；其结果——尤其敏感清理「哪些
    操作记录面已清 / 未清(unscrubbed) + caveat」——必须能回流前端，故每次清理落一条
    ``CleanupRun``，状态查询端点据此如实展示进度/结果（不靠静态文案）。

    ``sensitive`` 存 23-03 ``purge_sensitive_planes`` 返回 dict（各面计数 + unscrubbed +
    caveat）；普通模式恒为 ``None``。``(repository, -started_at)`` 索引供「取最近一次」。
    """

    class Mode(models.TextChoices):
        """清理模式：普通（仅派生索引面）/ 敏感（额外清操作记录面，23-03）。"""

        NORMAL = "normal", "普通清理"
        SENSITIVE = "sensitive", "敏感清理"

    class Status(models.TextChoices):
        """运行状态：进行中 / 完成 / 失败。"""

        RUNNING = "running", "进行中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="cleanup_runs",
    )
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.NORMAL,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    match_count = models.IntegerField(default=0, help_text="本次清理命中（差异）文件数")
    failures = models.JSONField(
        default=list,
        blank=True,
        help_text="逐文件/逐面失败标记列表（best-effort，不阻断其余）",
    )
    sensitive = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="敏感清理结果 dict（各面计数 + unscrubbed + caveat），普通模式为 null",
    )
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cleanup_runs"
        verbose_name = "清理运行记录"
        verbose_name_plural = "清理运行记录"
        indexes = [
            models.Index(
                fields=["repository", "-started_at"],
                name="idx_cleanup_repo_started",
            ),
        ]

    def __str__(self) -> str:
        return f"CleanupRun({self.repository_id}, {self.mode}, {self.status})"


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


class SensitiveFileSuggestion(models.Model):
    """敏感文件 AI 识别建议（Phase 24，EXCL-03）。

    检测器（``services/sensitive_detect.py``）在索引阶段产出**建议名单**：识别疑似
    含密钥 / 敏感信息的文件，供用户确认后接入 Phase 22 ``RepoExclusionRule``
    （source="ai_suggested"）——**绝不静默删除 / 绝不自动建规则**（DOMAIN §9 D-03）。

    upsert 锚点为 ``(repository, path)``：重复检测同一 path 更新而非重复插入；用户
    ``dismissed`` 的不反复打扰，除非升级为 ``real_secret``（升级打扰，见检测器）。
    """

    class Severity(models.TextChoices):
        """严重级别：命中真实密钥 / 疑似敏感 / 待复核配置（DOMAIN §9 D-02）。"""

        REAL_SECRET = "real_secret", "命中真实密钥"
        LIKELY_SENSITIVE = "likely_sensitive", "疑似敏感"
        CONFIG_REVIEW = "config_review", "待复核配置"

    class Detector(models.TextChoices):
        """命中来源：文件名启发式 / 内容扫描 / LLM 分类。"""

        HEURISTIC = "heuristic", "文件名启发式"
        CONTENT = "content", "内容扫描"
        LLM = "llm", "LLM 分类"

    class Status(models.TextChoices):
        """建议状态：待处理 / 已接受（建规则）/ 已忽略。"""

        PENDING = "pending", "待处理"
        ACCEPTED = "accepted", "已接受"
        DISMISSED = "dismissed", "已忽略"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="sensitive_suggestions",
    )
    path = models.CharField(
        max_length=500,
        help_text="相对仓库根的 POSIX 路径（口径与 exclusion.normalize_rel_path 对齐）",
    )
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
    )
    detector = models.CharField(
        max_length=16,
        choices=Detector.choices,
    )
    reason = models.TextField(
        help_text=(
            "脱敏命中描述：只记命中类型与位置（行号），"
            "**绝不**包含密钥本体 / 命中文本原值（DOMAIN §9 D-04，T-24-01）"
        ),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "repo_sensitive_file_suggestions"
        verbose_name = "敏感文件建议"
        verbose_name_plural = "敏感文件建议"
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "path"],
                name="uq_repo_sensitive_suggestion",
            ),
        ]
        indexes = [
            models.Index(
                fields=["repository", "status"],
                name="idx_repo_sensitive_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.repository_id}:{self.path} ({self.severity}/{self.status})"
