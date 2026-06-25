"""交付知识图谱数据模型（Phase 12 地基，KMOD-01/02/03）。

- `KnowledgeEntity`：四类交付知识实体的统一身份表（uuid5 同源稳定 PK），
  携带 source_kind + source_id 稳定业务引用、origin 来源渠道与 event_time。
- `KnowledgeEntityVersion`：实体内容的 supersedes 版本链（失效置位不删除），
  按 (entity, version) 可回溯任意旧版本，单 latest 由条件唯一约束兜底。
- `KnowledgeEdge`：实体间 bi-temporal 四时间戳关系边
  （valid_at/invalid_at 业务时间线 + created_at/expired_at 系统时间线）。
- `EntityKind` / `EntityOrigin` / `EdgeRelation`：TextChoices 枚举，
  字面值为锁定契约（kind 进 uuid5 PK 派生，改名即数据迁移）。
- `generate_entity_id`：实体 id 派生唯一入口纯函数。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

__all__ = [
    "KNOWLEDGE_NAMESPACE",
    "CodeChangeArchive",
    "EdgeRelation",
    "EntityKind",
    "EntityOrigin",
    "KnowledgeEdge",
    "KnowledgeEntity",
    "KnowledgeEntityVersion",
    "generate_entity_id",
]


class EntityKind(models.TextChoices):
    """交付知识实体四分类（KMOD-01，字面值锁定契约）。

    字面值进入 `generate_entity_id` 的 uuid5 派生与 Qdrant payload schema，
    任何改名都构成数据迁移——本枚举与 REQUIREMENTS 命名一致后即锁死（A3 定案）。
    """

    WORK_ITEM = "work_item", "需求/缺陷"
    TECH_PLAN = "tech_plan", "技术方案"
    CODE_CHANGE = "code_change", "代码变更"
    DOCUMENT = "document", "文档"
    # v0.15.0 Phase 79（KLINK）：把项目/仓库/空间纳入交付知识图谱作为图节点，
    # 经 KnowledgeEdge 统一建模项目↔知识/项目/仓库/空间关联。新增字面值不改既有四类，
    # 仅扩 generate_entity_id 派生空间与 kentity_kind_valid 约束（既有 uuid5 PK 零漂移）。
    PROJECT = "project", "项目"
    REPOSITORY = "repository", "仓库"
    SPACE = "space", "空间"


class EntityOrigin(models.TextChoices):
    """实体来源渠道（KMOD-01）。

    与 `source_kind`（业务对象类型）是两个维度：origin 回答"知识从哪个渠道进来"，
    source_kind + source_id 回答"它对应哪个稳定业务对象"。
    """

    FEISHU = "feishu", "飞书"
    CHAT = "chat", "对话"
    MCP = "mcp", "MCP"
    WORKFLOW = "workflow", "工作流"
    # v0.15.0 Phase 79：工件正文摄取来源渠道（ARTIFACT-04）+ 项目图谱投影参考节点来源
    # （KLINK）。origin 不进 generate_entity_id（仅 kind/source_kind/source_id），
    # 故新增 origin 仅触发 kentity_origin_valid 约束更新，无 PK 漂移。
    ARTIFACT = "artifact", "工件"
    PROJECT = "project", "项目"


class EdgeRelation(models.TextChoices):
    """知识边关系枚举（KMOD-02，字面值大写下划线，A4 定案）。

    `MODIFIES_CHUNK` 为 Phase 14（diff 归档→代码块关联）占位：
    本阶段仅落枚举与 `KnowledgeEdge.target_chunk_id` 弱引用字段，不交付写入路径。
    """

    HAS_PLAN = "HAS_PLAN", "需求→方案"
    IMPLEMENTED_BY = "IMPLEMENTED_BY", "方案→代码变更"
    REFERENCES = "REFERENCES", "引用文档"
    RELATES_TO = "RELATES_TO", "相关"
    DUPLICATE_OF = "DUPLICATE_OF", "重复"
    MODIFIES_CHUNK = "MODIFIES_CHUNK", "修改代码块"


# knowledge 独立 uuid5 命名空间。
# 禁止复用 code_relations 的 NAMESPACE_REPO——两个域的 id 空间必须隔离，
# 否则跨域 uuid5 入参偶然同串会产生不可解释的 id 碰撞。
KNOWLEDGE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "knowledge.friday-ai")


def generate_entity_id(kind: str, source_kind: str, source_id: str) -> uuid.UUID:
    """根据 (kind, source_kind, source_id) 生成确定性实体 id（uuid5）。

    本函数是 KnowledgeEntity.id 派生的**唯一入口**：Phase 13 摄取、测试 fixture、
    任何写入路径全部走此函数，禁止散落复刻 `uuid5(KNOWLEDGE_NAMESPACE, ...)`。
    拼接格式 ``f"{kind}:{source_kind}:{source_id}"`` 锁定；任何顺序 / 分隔符 /
    枚举字面值变更都构成实体 id 漂移（generate_chunk_id 同款警告）——届时需要
    全量数据迁移，而非简单改函数。

    Natural key 规则（locked decision，Phase 13+ 摄取按此构造 source_id）：

    | source_kind          | source_id 构成                                      | 对应业务对象 |
    |----------------------|-----------------------------------------------------|-------------|
    | feishu_work_item     | ``{project_key}:{work_item_type_key}:{work_item_id}`` | 飞书工作项三元组 |
    | feishu_document      | 飞书文档 token                                       | PRD/技术方案文档 |
    | coding_plan          | CodingPlan UUID str                                  | chat 产出方案 |
    | mcp_technical_plan   | McpWorkItemTechnicalPlan UUID str                    | MCP 产出方案 |
    | workflow_plan        | ``{execution_id}:{node_id}``                         | workflow 产出方案 |
    | task_result          | TaskResult/session UUID str                          | 编码产出 |
    | artifact             | initiatives.Artifact UUID str（kind=document）        | 项目工件正文（Phase 79）|
    | project              | initiatives.Project UUID str（kind=project）          | 项目图谱节点（Phase 79）|
    | repository           | repositories.Repository UUID str（kind=repository）   | 仓库图谱节点（Phase 79）|
    | space                | projects.Space UUID str（kind=space）                  | 空间图谱节点（Phase 79）|

    Args:
        kind: EntityKind 字面值（如 ``"work_item"``）。
        source_kind: 稳定业务引用类型（见上表）。
        source_id: 业务对象稳定 ID（含飞书三元组拼接）。

    Returns:
        uuid.UUID 实例（不是 str；调用方按需 `str(eid)` 自行转字符串）。
    """
    return uuid.uuid5(KNOWLEDGE_NAMESPACE, f"{kind}:{source_kind}:{source_id}")


class KnowledgeEntity(models.Model):
    """交付知识实体身份表（KMOD-01）。

    PK = ``generate_entity_id(kind, source_kind, source_id)``（uuid5 同源稳定 PK，
    ChunkRegistry 同款模式）：同一业务对象重复摄取得到同一实体 id，是 Phase 13
    摄取 upsert 的幂等锚点；DB 层另有 (kind, source_kind, source_id) 唯一约束兜底。

    FK 双层引用原则（实现契约）：
    - 组织维度（project / repository）用 FK 但 ``on_delete=SET_NULL``——
      可按项目/仓库过滤，但删项目不应抹掉知识历史（bi-temporal 历史可审计要求）。
    - 源业务对象一律 ``source_kind + source_id`` 弱引用：不做 FK、不用
      GenericForeignKey（无法表达飞书三元组，且 contenttypes 在本仓库零业务先例）。
    """

    id = models.UUIDField(primary_key=True, editable=False)
    kind = models.CharField(max_length=20, choices=EntityKind.choices, db_index=True)
    origin = models.CharField(max_length=20, choices=EntityOrigin.choices)
    source_kind = models.CharField(
        max_length=50, help_text="稳定业务引用类型（见 generate_entity_id natural key 规则表）"
    )
    source_id = models.CharField(max_length=255, help_text="业务对象稳定 ID（含飞书三元组拼接）")
    space = models.ForeignKey(
        "projects.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="knowledge_entities",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="knowledge_entities",
    )
    title = models.CharField(max_length=500)
    current_version = models.PositiveIntegerField(default=1)
    event_time = models.DateTimeField(help_text="业务事件时间（最近一次）")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "知识实体"
        verbose_name_plural = "知识实体"
        constraints = [
            # 幂等 natural key：Phase 13 摄取 upsert 的锚点
            UniqueConstraint(
                fields=["kind", "source_kind", "source_id"],
                name="uniq_kentity_natural_key",
            ),
            # DB 层枚举兜底（bulk_create / 直接 Manager.create 绕过 full_clean 时挡 typo）
            CheckConstraint(
                condition=Q(kind__in=EntityKind.values),
                name="kentity_kind_valid",
            ),
            CheckConstraint(
                condition=Q(origin__in=EntityOrigin.values),
                name="kentity_origin_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["space", "kind"], name="idx_kentity_proj_kind"),
            models.Index(fields=["source_kind", "source_id"], name="idx_kentity_source"),
        ]

    def __str__(self) -> str:
        return f"KnowledgeEntity({self.kind}:{self.source_kind}:{self.source_id})"


class KnowledgeEntityVersion(models.Model):
    """实体内容版本链（KMOD-03，supersedes 显式 FK + 单 latest 条件唯一约束）。

    实现契约：
    1. ``supersedes`` 用显式 self FK 而非只靠 version 号——非线性历史
       （如 v3 直接推翻 v1 的驳回重生成）可表达；``on_delete=PROTECT`` 是
       "失效置位不删除"（locked decision）的 DB 级保险，被引用旧版本物理删除被拒。
    2. ``uniq_kversion_one_latest`` 并发翻转 is_latest 时撞约束即报错是**期望行为**
       （优于静默双 latest）；串行化（``select_for_update``）责任在 Phase 13 摄取。
    3. 版本链回溯（KMOD-03）只走本 PG/SQLite 表，不依赖 Qdrant——
       召回面（payload is_latest）/ 轨迹面（本表版本链）边界（P10），
       Phase 15 检索按此分面实现。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(KnowledgeEntity, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
        help_text="被本版本取代的旧版本（显式版本链；PROTECT 防止删除被引用旧版本）",
    )
    content = models.TextField(help_text="该版本全文（Phase 13 embedding 输入）")
    content_hash = models.CharField(max_length=64, help_text="sha256 hex；内容未变跳过重摄取")
    payload = models.JSONField(default=dict, help_text="结构化原文快照")
    qdrant_point_ids = models.JSONField(
        default=list, help_text="Phase 13 写入；版本下线按 point id 精确删除（P1）"
    )
    # PageIndex 化章节树：从 markdown 标题层级确定性生成（knowledge/toc_tree.py），
    # 节点含 chunk_indexes 映射，检索命中 chunk 可回溯章节路径与 tree-walk 扩展。
    toc_tree = models.JSONField(default=list, blank=True)
    is_latest = models.BooleanField(default=True)
    vector_synced = models.BooleanField(
        default=False,
        help_text=(
            "Phase 13：向量 upsert 成功后置 True；"
            "短路条件 = content_hash 相同 AND vector_synced（堵 DB 已写/向量缺失窗口）"
        ),
    )
    event_time = models.DateTimeField(help_text="该版本对应的业务事件时间")
    valid_at = models.DateTimeField(help_text="业务时间线：版本生效")
    invalid_at = models.DateTimeField(
        null=True, blank=True, help_text="业务时间线：被取代（置位不删除）"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True, blank=True, help_text="系统时间线：记录作废")

    class Meta:
        verbose_name = "知识实体版本"
        verbose_name_plural = "知识实体版本"
        constraints = [
            # 按版本号回溯的基础
            UniqueConstraint(
                fields=["entity", "version"],
                name="uniq_kversion_entity_version",
            ),
            # 同一实体最多一个 latest（SQLite/PG 均编译为 partial unique index）
            UniqueConstraint(
                fields=["entity"],
                condition=Q(is_latest=True),
                name="uniq_kversion_one_latest",
            ),
            # 时间次序兜底（P2）：invalid_at 必须晚于 valid_at
            CheckConstraint(
                condition=Q(invalid_at__isnull=True) | Q(invalid_at__gt=F("valid_at")),
                name="kversion_valid_range",
            ),
        ]
        indexes = [
            models.Index(fields=["entity", "-version"], name="idx_kversion_entity_ver"),
        ]

    def __str__(self) -> str:
        return f"KnowledgeEntityVersion({self.entity_id} v{self.version}, latest={self.is_latest})"


class KnowledgeEdge(models.Model):
    """实体间 bi-temporal 关系边（KMOD-02，四时间戳，失效置位不删除）。

    四时间戳语义：
    - ``valid_at`` / ``invalid_at``：业务时间线——关系何时成立 / 何时失效；
    - ``created_at`` / ``expired_at``：系统时间线——记录何时写入 / 何时作废（纠错用）。
    失效与作废均为置位操作，物理删除被排除（历史可审计，locked decision）。

    target 二选一（DB 层 XOR 约束）：实体边填 ``target_entity``；
    Phase 14 的 MODIFIES_CHUNK 边填 ``target_chunk_id``（弱引用 ChunkRegistry，
    per 柔性引用原则不做 FK）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_entity = models.ForeignKey(
        KnowledgeEntity, on_delete=models.CASCADE, related_name="out_edges"
    )
    target_entity = models.ForeignKey(
        KnowledgeEntity,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="in_edges",
    )
    target_chunk_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "MODIFIES_CHUNK 边弱引用 ChunkRegistry.chunk_id（Phase 14 写入）。"
            "不做 ForeignKey（柔性引用原则）；与 target_entity 二选一（XOR 约束）。"
        ),
    )
    relation = models.CharField(max_length=30, choices=EdgeRelation.choices)
    metadata = models.JSONField(default=dict, blank=True)
    valid_at = models.DateTimeField(help_text="业务时间线：关系成立")
    invalid_at = models.DateTimeField(
        null=True, blank=True, help_text="业务时间线：关系失效（置位不删除）"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True, blank=True, help_text="系统时间线：记录作废")

    class Meta:
        verbose_name = "知识边"
        verbose_name_plural = "知识边"
        constraints = [
            # 活跃边唯一：同一对实体同 relation 只能有一条"当前有效"边
            UniqueConstraint(
                fields=["source_entity", "target_entity", "relation"],
                condition=Q(invalid_at__isnull=True) & Q(expired_at__isnull=True),
                name="uniq_kedge_active",
            ),
            # chunk 边活跃唯一（Phase 14 / Pitfall 4 DB 防线）：
            # uniq_kedge_active 对 target_entity 为 NULL 的 chunk 边不生效
            # （NULL 彼此不相等），单独补一条 partial unique 封堵重复活跃 chunk 边。
            UniqueConstraint(
                fields=["source_entity", "target_chunk_id", "relation"],
                condition=Q(invalid_at__isnull=True) & Q(expired_at__isnull=True),
                name="uniq_kedge_chunk_active",
            ),
            # 两端二选一：实体边 XOR chunk 边
            CheckConstraint(
                condition=(
                    (Q(target_entity__isnull=False) & Q(target_chunk_id__isnull=True))
                    | (Q(target_entity__isnull=True) & Q(target_chunk_id__isnull=False))
                ),
                name="kedge_target_xor",
            ),
            # 时间次序兜底（P2）
            CheckConstraint(
                condition=Q(invalid_at__isnull=True) | Q(invalid_at__gt=F("valid_at")),
                name="kedge_valid_range",
            ),
            # DB 层枚举兜底
            CheckConstraint(
                condition=Q(relation__in=EdgeRelation.values),
                name="kedge_relation_valid",
            ),
        ]
        indexes = [
            # 遍历 fanout 主索引：GraphStore 递归 CTE 每一跳走它
            models.Index(fields=["source_entity", "relation"], name="idx_kedge_fanout"),
            models.Index(fields=["target_entity"], name="idx_kedge_reverse"),
            # 活跃边部分索引：默认遍历只扫有效边
            models.Index(
                fields=["source_entity"],
                condition=Q(invalid_at__isnull=True) & Q(expired_at__isnull=True),
                name="idx_kedge_active_fanout",
            ),
        ]

    def __str__(self) -> str:
        target = self.target_entity_id or self.target_chunk_id
        return f"KnowledgeEdge({self.source_entity_id} -[{self.relation}]-> {target})"


class CodeChangeArchive(models.Model):
    """编码产出全量 diff 归档（KMOD-05，Phase 14 定型建表）。

    diff 原文经 zlib 压缩存 ``diff_compressed``，文件级解析摘要进 ``files`` JSON；
    **diff 原文绝不进 KnowledgeEntityVersion 的 payload/content 全量**——
    version.content 只放受控大小的归一化文本（chunk 策略），全量原文唯一落点是本表。

    与 KnowledgeEntity(code_change) 的关系（柔性引用原则，不 FK 到 entity）：
    实体 id 经 ``generate_entity_id("code_change", source_kind, source_id)`` 派生，
    归档行与实体经 ``(source_kind, source_id)`` 双向可查。

    幂等锚：``uniq_codechange_source_commit`` 约束保证同一编码产出 + 同一
    commit 只归档一次（重触发/回放撞约束即幂等放弃，T-14-01 防线）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 与 KnowledgeEntity(code_change) 同源弱引用（不 FK 到 KnowledgeEntity）
    source_kind = models.CharField(max_length=50, help_text='来源类型（如 "task_result"）')
    source_id = models.CharField(max_length=255, help_text="业务对象稳定 ID（如 session_id）")
    repository = models.ForeignKey(
        "repositories.Repository",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="code_change_archives",
    )
    # Git 元数据（KMOD-05 显式要求）
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    branch_name = models.CharField(max_length=255, blank=True, default="")
    base_branch = models.CharField(max_length=255, blank=True, default="")
    # 500：自托管 GitLab 深层 group 嵌套 MR URL 可超默认 200 列宽（WR-02）
    mr_url = models.URLField(max_length=500, blank=True, default="")
    mr_id = models.CharField(max_length=64, blank=True, default="")
    # 压缩 diff 原文：zlib.compress(raw.encode("utf-8"))，读取侧 decompress 还原
    diff_compressed = models.BinaryField()
    diff_size = models.PositiveIntegerField(help_text="解压后字节数")
    compressed_size = models.PositiveIntegerField(help_text="压缩后字节数")
    diff_sha256 = models.CharField(max_length=64, help_text="原文 sha256 hex（幂等/完整性校验）")
    truncated = models.BooleanField(default=False, help_text="平台 API / 上限截断标记")
    # unidiff 文件级解析结果（每项：path/old_path/change_type/additions/
    # deletions/is_generated/hunk_ranges/unresolved_symbols）
    files = models.JSONField(default=list)
    file_count = models.PositiveIntegerField(default=0)
    total_additions = models.PositiveIntegerField(default=0)
    total_deletions = models.PositiveIntegerField(default=0)
    event_time = models.DateTimeField(help_text="业务事件时间（编码产出完成）")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "代码变更归档"
        verbose_name_plural = "代码变更归档"
        constraints = [
            # 同一编码产出 + 同一 commit 只归档一次（重触发幂等锚）
            UniqueConstraint(
                fields=["source_kind", "source_id", "commit_sha"],
                name="uniq_codechange_source_commit",
            ),
        ]
        indexes = [
            models.Index(fields=["repository", "commit_sha"], name="idx_cca_repo_commit"),
            models.Index(fields=["source_kind", "source_id"], name="idx_cca_source"),
        ]

    def __str__(self) -> str:
        return f"CodeChangeArchive({self.source_kind}:{self.source_id} @ {self.commit_sha[:12]})"
