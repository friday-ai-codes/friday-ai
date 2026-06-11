# Phase 14: 全触发点接入与 diff 归档 - Research

**Researched:** 2026-06-11
**Domain:** 知识摄取触发点接线（workflow / 编码回调 / 飞书）+ 全量 diff 归档与代码图谱对齐（brownfield，Django 5.1 / Python 3.14 异步栈）
**Confidence:** HIGH（全部挂点经实读源码给出行级锚点；唯一新增外部依赖 unidiff 经 PyPI registry 验证；GitHub/GitLab API 大 diff 行为标 MEDIUM/LOW）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

已锁定的硬约束（不可偏离）：
- 复用 Phase 13 统一摄取管线：触发点只构造 IngestionRequest/normalizer + `aschedule_ingestion`，不各写摄取逻辑
- 图写入只走 GraphStore；payload schema 以 `knowledge/collection.py` 常量为唯一事实源
- diff 归档表（KMOD-05）按 Phase 12 预留方式本阶段随 migration 建（CodeChangeArchive 当时定案不建 stub，本阶段定型）
- `MODIFIES_CHUNK` 边 target_chunk_id 不做 FK（Phase 12 XOR 约束已就位）；懒解析（file+symbol+commit_sha 记录即可，不强制实时对齐）
- Git 平台凭证走既有 git_platform service 层（数据库加密凭证，不读 env）
- 生成文件跳过、超大 diff 压缩存储（PITFALLS 防线）

### Claude's Discretion

All implementation choices are at Claude's discretion — pipeline/infrastructure phase。以 ROADMAP Phase 14 success criteria 与 Phase 12/13 已交付契约为准。

### Specific Ideas

ENH-01 降级路径已获 ROADMAP 授权：符号级受阻 → 文件级起步不阻塞，符号级仍为本阶段明确交付项跟踪。

### Deferred Ideas (OUT OF SCOPE)

None — discuss skipped（infrastructure phase）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KMOD-05 | 全量 diff 归档落库（unidiff 文件级解析、commit SHA / MR URL / 仓库元数据、超大 diff 压缩存储） | §CodeChangeArchive schema + §DiffArchiver 设计 + unidiff 0.7.5 验证 + zlib/BinaryField 压缩方案 |
| INGEST-01 | workflow `ai_plan_generation` 产出方案自动摄取 + HAS_PLAN 边（含审批通过事件） | §触发点 1：`plan_generation.py:401` 成功路径锚点 + `node_approved` hook 机制（`scheduler.py:1210`）+ workflow_plan natural key 已锁定 |
| INGEST-02 | 编码完成回调自动归档全量 diff、摄取 code_change 关联方案/需求 | §触发点 2：`callbacks.py:614` 锚点 + repository/凭证解析路径 + MR URL 两段式回填 + EdgeSpec 扩展（reverse 方向） |
| INGEST-04 | 飞书工作项关键事件摄取带事件时间快照（名称/描述/自定义字段/PRD 与方案文档正文/关联工作项） | §触发点 3：`feishu/views.py` 四事件 handler 锚点 + `build_work_item_context` 全量快照取材件复用 + TriggerLog 作 normalizer 源 |
| ENH-01 | diff→chunk 符号级对齐：MODIFIES_CHUNK 边（file+symbol+commit_sha 懒解析）关联 ChunkRegistry，反查"这个函数被哪些需求改过" | §MODIFIES_CHUNK 设计：`Symbol.chunk_id` 已有同源绑定（symbol_chunk_binding.py）+ unidiff `section_header` 符号源 + 文件级降级规则 |
</phase_requirements>

## Summary

Phase 14 是纯既有模式拼装：Phase 13 已交付的统一摄取管线（`aschedule_ingestion` + normalizer 注册表 + 六步版本翻转）只需"加三个 normalizer + 接若干锚点"；真正的新代码集中在 **DiffArchiver**（git platform 拉全量 diff → unidiff 解析 → 压缩归档 → diff 专用切块 → MODIFIES_CHUNK 边）。所有触发点挂点已实读定位到行级；三条路径（workflow 节点、容器回调、飞书 webhook）各自已有幂等与异常隔离基建（TaskResult 存在性短路、ProcessedEvent + TriggerLog unique、HookManager 异常吞噬），接线成本低。

两个需要规划期明确的设计扩展：① `EdgeSpec` 目前只支持"以本事件实体为 source 的实体出边"（`ingestion.py:75-86`），MODIFIES_CHUNK（chunk 目标 + metadata）和 IMPLEMENTED_BY（方案→code_change，本事件实体是 *target*）都表达不了——需要向后兼容地扩展 `EdgeSpec`（加 `target_chunk_id` / `metadata` / `reverse` 三个默认值字段）并同步扩展 `apply_edge_specs`；② 现有 `get_merge_request_diff` 带硬截断（max_files=50 / max_diff_lines=500，`base.py:48-64`）且签名面向 MR——全量归档需要在 git_platform 层新增按分支对比拉全量 diff 文本的方法（GitLab `repository_compare` 的 `diffs[]` 已含全文；GitHub `repo.compare().files[].patch`）。

ENH-01 的符号级对齐有意外的好牌：indexer 已把 `codegraph.Symbol` 与 RAG chunk 做了同源绑定（`Symbol.chunk_id` 字段，`code_relations/symbol_chunk_binding.py`），符号级解析 = 一次 `Symbol.objects.filter(repository, file_path, name=symbol)` 查询；unidiff 的 `hunk.section_header` 天然携带 hunk 所在函数/类名，是零成本符号源。文件级降级 = `ChunkRegistry.filter(repository, branch_name="", file_path)` + hunk 行号区间与 `line_start/line_end` 相交。

**Primary recommendation:** 按"3 个 normalizer + 1 个 DiffArchiver 模块 + 1 张归档表 + EdgeSpec 向后兼容扩展 + git_platform 1 个新方法"切分；每个触发点照抄 13-03 的"lazy import + 只组装 ID 投递 + 测试断言投递"模板；diff 切块新增 `chunk_diff_text`（文件→hunk 层级）与 `chunk_kind="diff_file"`，不动 `KNOWLEDGE_SCHEMA_VERSION`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| workflow 方案产出/审批触发 | Backend：workflow 引擎（节点 execute + HookManager） | knowledge 摄取管线 | 触发点只投递 IngestionRequest（locked），取材在 normalizer 后台 |
| 编码回调触发 + diff 归档 | Backend：subagent callbacks + knowledge/DiffArchiver | git_platform service | 回调路径只投递；拉 diff/解析/落库全在后台 normalizer 内 |
| 飞书事件快照 | Backend：feishu webhook views | services/feishu + feishu_doc（API 取材） | webhook 必须快速返回（飞书重推），快照拉取在后台 |
| diff 文本切块/向量化 | knowledge（chunking + vector_ops） | Qdrant | chunking 是纯函数层；写入走既有 vector_ops 批量收口 |
| MODIFIES_CHUNK 边 | knowledge/GraphStore | code_relations / codegraph（只读对齐源） | 图写入只走 GraphStore（locked）；Symbol/ChunkRegistry 仅作只读查询 |
| MR URL 回填 | Backend：MR 创建点（coding_graph / ai_coding 节点） | CodeChangeArchive | PR 在回调之后才创建，归档行二段式 update |
| 凭证 | Backend：repositories.GitCredential + common.encryption | — | DB 加密凭证（locked），样板见 `coding_graph.py:228-238` |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `unidiff` | 0.7.5 | unified diff 解析到文件/hunk 级（`PatchSet` / `PatchedFile` / `Hunk.section_header`） | REQUIREMENTS（KMOD-05）点名；事实标准纯 Python diff 解析库，2014 年起维护，零三方依赖 [VERIFIED: PyPI registry + github.com/matiasb/python-unidiff] |
| `zlib`（stdlib） | — | diff 全文压缩存储 | 标准库零依赖；文本 diff 压缩比 5–10x；`zlib.compress(b, 6)` / `zlib.decompress` 对称 [VERIFIED: Python stdlib] |
| `hashlib`（stdlib） | — | diff_sha256 完整性/幂等指纹 | 与 `ingestion.py:186` content_hash 同模式 |

### Supporting（全部已在依赖中，零新增）

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `PyGithub` | >=2.0（已有） | GitHub compare/PR diff（`repo.compare(base, head).files[].patch`） | DiffArchiver GitHub 路径 |
| `python-gitlab` | >=4.0（已有） | GitLab `project.repository_compare()` / `mr.changes()` | DiffArchiver GitLab 路径 |
| `lark-oapi` / 既有 `FeishuClient` `FeishuDocClient` | 已有 | 工作项快照 + 文档正文 | INGEST-04 normalizer 取材 |
| `structlog` | 已有 | 结构化日志 | 全部新代码 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| unidiff | 手写 `@@` 正则解析 | Don't hand-roll：rename/binary/no-newline-at-eof/多 hunk 边界全是坑（见 Don't Hand-Roll 表） |
| zlib | gzip / lzma | gzip 仅多了文件头开销；lzma 压缩比高但 CPU 成本数倍，归档读写频繁不划算。zlib level 6 是平衡点 |
| BinaryField 存压缩 bytes | TextField 存原文 | 万行 lockfile diff 原文可达数 MB；TextField 在 PG 走 TOAST 也行，但压缩后行体积减 80%+，且"压缩存储"是 locked decision |
| 平台 API 拉 diff | 本地 git clone + `git diff` | 服务器无仓库工作副本（clone 在 task 容器内）；API 路径是唯一不引入新基建的方案 |

**Installation:**

```bash
cd server && uv add "unidiff>=0.7.5"
```

**Version verification:** `unidiff` 当前最新 0.7.5（PyPI JSON API 实查，发布于 2023-03-10；项目稳定低频维护，无已知 CVE）。不在 `server/pyproject.toml` 与 `uv.lock` 中（rg 实查零命中）——**本阶段唯一新增依赖**。

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| unidiff | PyPI | ~12 yrs（0.7.5 @ 2023-03） | 高（pip 生态常用，被 pylint/CI 工具广泛依赖） | github.com/matiasb/python-unidiff | 不可用（未安装） | Approved（带验证说明） |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 在本机不可用（`command -v slopcheck` 未命中，研究期间不向系统装包）。但 unidiff 满足三重独立验证：① PyPI registry JSON API 实查存在且版本/日期吻合（非幻觉包）；② 官方 GitHub 仓库存在且与 PyPI home_page 一致；③ 包名由 REQUIREMENTS/CONTEXT 锁定而非生成式推荐。综合判定低风险 Approved；planner 可按惯例在安装任务里加一句 `uv add` 后 `uv run python -c "import unidiff; print(unidiff.__version__)"` 自检，无需 checkpoint:human-verify。*

## 触发点确切挂点（行级锚点）

### 触发点 1：workflow `ai_plan_generation`（INGEST-01）

**1a. 产出方案成功路径**

挂点：`server/workflows/nodes/ai/plan_generation.py` `AIPlanGenerationNode.execute()`——`result = await super().execute(context)`（line 388）成功、review 子步骤 COMPLETED（line 399）之后、`return result`（line 401）之前。判定条件：`result.status != "failed"` 且 `result.output.get("plan")` 非空（`map_output` 在 line 301-331 把结构化 plan 放进 `output["plan"]`，提取失败时为 `None`）。

可得上下文字段：

| 字段 | 来源 |
|------|------|
| plan dict（title/summary/execution_plan） | `result.output["plan"]` |
| execution_id / node_id | `context.execution_id` / `context.node_id`（`workflows/nodes/base.py:77-78`） |
| project | `context.workflow_execution.project`（`WorkflowExecution.project` FK，`workflows/models/execution.py:86`）；节点内已有 `await self._get_project(context)`（line 355） |
| work_item_id（飞书触发时） | `context.workflow_execution.context.get("work_item_id")`（`FeishuApprovalHandler._find_active_execution` 即按 `context__work_item_id` 查，`feishu/approval.py:91-98`）；fallback `input_data__work_item_id` |
| trigger_data | `context.trigger_data`（飞书 payload 透传，含 work_item_type_key） |

natural key 已锁定（`knowledge/models.py:97`）：`source_kind="workflow_plan"`，`source_id=f"{execution_id}:{node_id}"`。接线照抄 13-03 模板：

```python
# plan_generation.py execute() 成功路径尾部（仿 13-03 锚点形态）
if result.status != "failed" and result.output and result.output.get("plan"):
    from knowledge import ingestion  # lazy import 防循环

    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest(
            source_kind="workflow_plan",
            source_id=f"{context.execution_id}:{context.node_id}",
            trigger="workflow_plan_generated",
        )
    )
```

normalizer（`knowledge/sources/workflow_plan.py`）后台重读：`NodeExecution.objects.filter(workflow_execution_id=execution_id, node_id=node_id)`（source_id 拆分），从 `output_data["plan"]` 取 content（title + summary + execution_plan markdown 渲染），`project_id` 从 `workflow_execution.project_id`，`event_time` 取 `node_exec.completed_at`（aware）。若 `workflow_execution.context["work_item_id"]` 存在 → 产出 `[work_item 锚, tech_plan]` 双事件 + `HAS_PLAN` exclusive EdgeSpec（逐字仿 `sources/mcp_plan.py:74-101`，三元组 `{project.feishu_project_key}:{work_item_type}:{work_item_id}`，type 缺失时默认 `"story"`——与 `feishu/views.py:636` 同默认值）；无 work_item → 仅 tech_plan 单事件。

**1b. 方案审批通过事件**

审批在两条互不相交的路径上发生，都收敛到 `WorkflowEngine.approve_node`（`workflows/engine/scheduler.py:1188-1219`）：
- 飞书评论审批：`feishu/views.py:805-855` `_handle_workitem_comment` 关键词判定 → `FeishuApprovalHandler.on_approval_comment`（`feishu/approval.py:26-83`）→ `engine.approve_node`；
- 前端/API 审批同样走 `approve_node`。

`approve_node` 内部已触发 `self.hooks.trigger("node_approved", execution=..., node_execution=..., approver=...)`（line 1210-1215）。**推荐挂点：注册 HookManager 钩子而非改 approve_node 内部**——`workflows/hooks/base.py` 的 HookManager 自带逐钩子异常吞噬（line 72-81，与"异常全吞不阻塞宿主"纪律天然一致），注册位置仿 `FeishuSyncHook`（`scheduler.py:121-125` 在 `WorkflowEngine.__init__` 注册）。钩子内过滤：`node_execution.node.node_type == "human_approval"`（`workflows/nodes/control/approval.py:25`）时，沿 `workflow_execution` 找同 execution 内 `ai_plan_generation` 类型且已完成的 NodeExecution，对其投递同 key 的 `IngestionRequest(trigger="workflow_plan_approved")`。

审批事件的摄取语义（裁量推荐）：审批通过时重投同一 natural key——若方案经多轮 revise 后内容已变 → 正常版本翻转（审批后的最终内容入图）；内容未变 → `_persist_sync` hash 短路 skip，但 **边阶段对 skipped 事件仍然执行**（`ingestion.py:241-243`，13-02 既有行为），HAS_PLAN 边自愈。审批留痕：normalizer 在 `trigger=="workflow_plan_approved"` 时把 `{"approved": true, "approved_at": ...}` 并入 payload（内容变更时随新版本落库）；并经扩展后的 `EdgeSpec.metadata` 写进 HAS_PLAN 边 metadata（`graph_store.add_edge` 已支持 metadata 参数，`graph_store.py:111-120`）。注意：对"边已存在且 target 相同"的复用分支，`apply_edge_specs` 现状跳过不更新 metadata（`ingestion.py:313-314`）——若规划认为审批时间必须可查，需在该分支补一次 metadata merge 更新（KnowledgeEdge.metadata JSONField 直接 aupdate，仍在 graph_store 收口内做）。

### 触发点 2：编码完成回调（INGEST-02 + KMOD-05）

挂点：`server/subagent/api/callbacks.py` `_handle_completed`（line 573-636），在 `_update_coding_session_on_complete(session)`（line 614）之后、`_schedule_workflow_resume` 之前插入投递。gate 条件：`session.task_type == SubAgentSession.TaskType.CODING`（line 41-46 枚举）或 `last_output.task_type` 等效为 coding，且 `commit_sha` 或 `branch_name` 非空（line 592-593 已提取）。注意该 handler 已有幂等防线：TaskResult 已存在直接 return（line 587-589），重复回调不会二次投递。

可得上下文字段（回调时刻）：

| 字段 | 来源 | 备注 |
|------|------|------|
| branch_name / commit_sha / modified_files | `TaskResult`（`subagent/models.py:281-284`）| 容器回传 |
| repository | **chat 路径**：`CodingSession.repository`（FK，`chat/models.py:363-367`，经 `subagent_session` OneToOne 反查）；**workflow 路径**：`NodeExecution.output_data["pending_sessions"][*].repository_id`（`ai/coding.py:530-533`）；**兜底**：`Repository.objects.filter(git_url=session.repo_url)`（`SubAgentSession.repo_url` line 64） | normalizer 内解析，不在回调路径解析 |
| base_branch | `repository.default_branch`（`repositories/models.py:160`）；workflow 路径 `output_data["base_branch"]` | |
| MR URL | **回调时刻不存在**（见下） | 二段式回填 |
| 关联方案 | chat：`CodingSession.coding_plan`（FK）→ `coding_plan` natural key；workflow：同 execution 内 `ai_plan_generation` NodeExecution → `workflow_plan` key；MCP：13-03 已有 `mcp_technical_plan` 实体（execute_work_item_repo_tasks 路径的 session 关联经 last_output 溯源） | IMPLEMENTED_BY 边目标 |

natural key 已锁定（`knowledge/models.py:98`）：`source_kind="task_result"`，`source_id=session.session_id`。

**MR URL 时序事实（关键）**：`_handle_completed` 时 PR 尚未创建——chat 路径 PR 在用户确认后的 `create_pr_or_skip_node`（`orchestration/coding_graph.py:551-621`，成功在 line 604-613 拿到 `result.mr_url`）；workflow 路径在节点恢复后的 `_resume_after_containers` → `_create_mr_for_repo`（`workflows/nodes/ai/coding.py:603-620` / `1090-1180`）。推荐**二段式**：① 回调触发归档（diff 按 branch vs default_branch 经 compare 拉取，commit_sha/分支/仓库元数据齐全）；② 在上述两个 MR 创建成功点直接 `CodeChangeArchive.objects.filter(source_id=...).aupdate(mr_url=..., mr_id=...)`（小函数收在 DiffArchiver 模块，如 `attach_mr_url(session_id, mr_url, mr_id)`），**不**重摄取实体（mr_url 进 archive 行与实体 payload 的策略见 Open Questions OQ-2）。

### 触发点 3：飞书工作项关键事件（INGEST-04）

挂点（全部在 `server/feishu/views.py` `FeishuWebhookView`，事件分发在 line 655-667）：

| 关键事件 | handler | 行号 | 快照语义 |
|---------|---------|------|---------|
| WorkitemCreateEvent | `_handle_workitem_create` | 751-761 | 工作项创建快照（v1） |
| WorkitemUpdateEvent | `_handle_workitem_update` | 857-874 | 字段修改 → 重摄新版本 |
| WorkitemStatusEvent | `_handle_workitem_status` | 763-791 | 状态流转（含"触发编码"类状态）→ 重摄 |
| WorkitemCommentEvent（审批语义命中时） | `_handle_workitem_comment` | 805-855 | 审批通过/驳回 → 重摄（approval payload） |

幂等已就位：`is_event_processed_db`/`mark_event_processed_db`（line 571-574 / 622-624，ProcessedEvent DB 唯一约束）+ TriggerLog `event_uuid` unique 兜底（line 650-653）。每个 handler 已持有 `trigger_log`（line 639-649 创建，含 project FK / work_item_id / work_item_type / webhook_raw_request）。

接线：每个 handler 尾部投递 `IngestionRequest(source_kind="feishu_work_item_event", source_id=str(trigger_log.id), trigger=event_type)`。**source_id 用 TriggerLog id 而非三元组**——IngestionRequest 是 frozen 三字段 DTO，normalizer 需要"事件上下文"（project、事件类型、事件时间），TriggerLog 是唯一把这些落库的源模型；产出的 IngestionEvent 的实体 key 仍是三元组（见下），二者不冲突（normalizer 注册表按 request.source_kind 路由，事件实体按 event.source_kind+source_id 定 id）。

normalizer（`knowledge/sources/feishu_work_item.py`）后台取材：
1. 读 TriggerLog（project / feishu_project_key / work_item_id / work_item_type / created_at）；
2. 全量快照——复用 `mcp_tools/work_item_context_service.py` 已验证的取材件：`create_feishu_client_for_project(project)`（`services/feishu.py:567`）+ `client.get_work_item(...)`（line 104，返回 name/description/status/fields）+ `client.get_work_item_relations(...)`（line 188，关联工作项）+ `extract_feishu_doc_refs({description, fields, comments})` + `_read_documents(project, refs)`（`work_item_context_service.py:133-175`，PRD 与技术方案文档正文经 FeishuDocClient `get_document_content` 转 markdown）。`_read_documents` 是私有函数——建议把"工作项全量快照"抽成 `mcp_tools` 或 `services` 层公共 helper（`build_work_item_context` 本体绑定 InteractionRun ledger 不可直接复用，但内部件可平移）；
3. 产出 work_item 事件：`source_kind="feishu_work_item"`，`source_id=f"{project_key}:{work_item_type}:{work_item_id}"`（与 13-03 mcp 锚**同 key**——全量快照对轻量锚版本翻转，13-03 决策原文："Phase 14 INGEST-04 同 key 重摄为全量快照"）。content = name + description + 自定义字段渲染 + 文档正文（截断，见 chunk 节）+ 关联工作项清单；payload 存结构化快照；`event_time` 取 webhook 接收时间（`trigger_log.created_at`，aware）或 payload 内毫秒时间戳转换（**必须 `timezone.make_aware`/`datetime.fromtimestamp(tz=)`，P2 时区坑**）。

“产出方案/触发编码”两类关键事件在飞书侧的实际代码路径就是 MCP 工具链（13 已接）与 workflow（本阶段 1a 接）——INGEST-04 的飞书侧落点以上表四类 webhook 事件 + 审批评论为准，不需要额外挂点。

## CodeChangeArchive 表 schema 建议

放 `knowledge` app（CONTEXT integration point 指定 "knowledge/ 内新增 diff_archive 模型"），随本阶段 migration 建（Phase 12 定案不预建 stub）：

```python
class CodeChangeArchive(models.Model):
    """编码产出全量 diff 归档（KMOD-05）。diff 原文压缩存储，文件级解析结果进 files JSON。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 与 KnowledgeEntity(code_change) 同源对齐的弱引用（柔性引用原则，不做 FK）
    source_kind = models.CharField(max_length=50, default="task_result")
    source_id = models.CharField(max_length=255)  # SubAgentSession.session_id
    # 组织维度 FK（SET_NULL，知识历史不随删除抹掉——KnowledgeEntity 同款原则）
    repository = models.ForeignKey("repositories.Repository", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="code_change_archives")
    project = models.ForeignKey("projects.Project", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="code_change_archives")
    # Git 元数据
    branch_name = models.CharField(max_length=255, blank=True, default="")
    base_branch = models.CharField(max_length=255, blank=True, default="")
    commit_sha = models.CharField(max_length=64, blank=True, default="", db_index=True)
    mr_url = models.URLField(blank=True, default="")       # 二段式回填
    mr_id = models.CharField(max_length=64, blank=True, default="")
    # 统计
    files_count = models.PositiveIntegerField(default=0)
    additions = models.PositiveIntegerField(default=0)
    deletions = models.PositiveIntegerField(default=0)
    raw_diff_bytes = models.PositiveBigIntegerField(default=0)   # 压缩前体积
    truncated = models.BooleanField(default=False)               # 文件数/单文件截断标记
    # diff 本体（压缩存储，locked decision）
    diff_compressed = models.BinaryField()                        # zlib.compress(diff_text.encode(), 6)
    compression = models.CharField(max_length=10, default="zlib") # 算法演进逃生门
    diff_sha256 = models.CharField(max_length=64)                 # 压缩前全文指纹（完整性/幂等）
    # 文件级解析结果（unidiff 产物 + 生成文件判定 + 符号清单 → MODIFIES_CHUNK 懒解析的"全集记录"）
    # 形如 [{"path","old_path","change_type","additions","deletions","is_generated",
    #        "hunks":[{"target_start","target_length","section_header","symbol"}]}]
    files = models.JSONField(default=list)
    event_time = models.DateTimeField()        # 业务事件时间（回调时刻）
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # 幂等锚：同一 session 只归档一次（重复回调被 _handle_completed 短路，本约束兜底）
            models.UniqueConstraint(fields=["source_kind", "source_id"], name="uniq_codechange_source"),
        ]
        indexes = [
            models.Index(fields=["repository", "-created_at"], name="idx_cca_repo_created"),
        ]
```

要点：
- **不做 FK 到 KnowledgeEntity/SubAgentSession**：`(source_kind, source_id)` 与 `generate_entity_id("code_change", "task_result", session_id)` 同源，可双向反查；柔性引用是仓库既定原则（ChunkEdge/target_chunk_id 同款）。
- **diff 一律压缩**（不设"超大才压"分支）：行为单一、读写对称；zlib level 6 对 unified diff 文本压缩比约 5–10x。解压封装成 model property `diff_text`。
- **`files` JSON 是 MODIFIES_CHUNK 懒解析的"全集记录"**：每文件每 hunk 的 `section_header` 提取符号 + 行区间，无论边是否建成功，三元组（file+symbol+commit_sha）都先落在这里——这正是 locked decision"记录即可，不强制实时对齐"的载体。
- `BinaryField` 在 PG（bytea）/SQLite（BLOB）双后端原生支持，测试零特判。

## DiffArchiver service 设计

模块：`server/knowledge/diff_archive.py`（与 ingestion/chunking 同层，knowledge 域内聚）。

### 1. git platform 拉全量 diff——现有 API 盘点与缺口

| 现有方法 | 位置 | 能否复用 |
|---------|------|---------|
| `get_merge_request_diff(mr_id, max_files=50, max_diff_lines=500)` | `git_platform/base.py:48-64`；GitHub `github_client.py:168-256`（`pr.get_files()` 逐文件 `f.patch`）；GitLab `gitlab_client.py:190-259`（`mr.changes()["changes"][].diff`） | ❌ 需要 MR 已存在 + 硬截断（500 行/文件、50 文件），归档用会丢全量性 |
| `compare_branches(source, target, max_files=50)` | GitLab `gitlab_client.py:261-359`（`project.repository_compare` 返回的 `diffs[]` **已含每文件全量 diff 文本**，现实现只取统计后丢弃文本 line 302-325）；GitHub `github_client.py:258-351`（`repo.compare().files` 有 `.patch` 属性，现实现未取） | ⚠️ 数据源对，但返回模型 `CompareFileEntry` 不含 diff 文本 |
| 凭证解析 | `GitCredential`（OneToOne `repository.credential`，`repositories/models.py:551-566`）+ `decrypt_value`（样板 `coding_graph.py:228-238`） | ✅ 直接照抄 |
| client 工厂 | `get_git_platform_client(repository, token)`（`git_platform/__init__.py:113-136`） | ✅ |

**推荐**：在 `GitPlatformClient` 新增抽象方法 `get_branch_diff(source_branch, target_branch, max_files=500) -> MRDiffResult`（复用既有 `MRDiffFile`/`MRDiffResult` dataclass，**不做行级截断**，只保留文件数上限防线 + truncated 标记）：
- GitLab：`project.repository_compare(target, source)["diffs"]` → 每项 `{diff, old_path, new_path, new_file, deleted_file, renamed_file}` 直接映射（diff 文本全量）；
- GitHub：`repo.compare(target, source).files` → `f.patch / f.filename / f.previous_filename / f.status` 映射。

平台 API 已知边界（写进实现注释与 pitfall）：
- GitHub compare：单次最多返回 **300 个文件**条目（commits 上限 250），超出需逐 commit 或标 truncated [CITED: docs.github.com/rest/commits/commits#compare-two-commits]；超大单文件 `patch` 字段会被 API **省略（None）**——此时按"仅元数据归档"处理（is_generated 同路径），不报错 [ASSUMED——GitHub 文档对 patch 省略阈值无精确数字，需大文件实测]。
- GitLab `repository_compare`：默认整包返回（无分页），万行 diff 单请求体积大——依赖 python-gitlab 默认 timeout，必要时构造 client 时调大 [ASSUMED——本仓库 GitLab 实例行为未实测]。

### 2. unidiff 解析

```python
# Source: github.com/matiasb/python-unidiff README（API 稳定自 0.5.x）
from unidiff import PatchSet

# 平台 API 给的是"每文件 diff 体"（GitLab changes.diff / GitHub f.patch 都从 @@ 或 --- 开始，
# 无 `diff --git` 头）。喂 PatchSet 前必须为每个文件补头，否则解析为空：
def _wrap_file_diff(old_path: str, new_path: str, body: str) -> str:
    return f"--- a/{old_path}\n+++ b/{new_path}\n{body}\n"

patch = PatchSet(_wrap_file_diff(f.old_path, f.new_path, f.diff))
for pf in patch:                      # PatchedFile
    pf.path, pf.is_added_file, pf.is_removed_file, pf.is_rename
    pf.added, pf.removed              # 行级统计
    for hunk in pf:                   # Hunk
        hunk.target_start, hunk.target_length
        hunk.section_header           # "def foo(self):" —— ENH-01 符号源（git 上下文行）
```

`section_header` 即 `@@ -a,b +c,d @@ <这里>`，git 默认填 hunk 所在函数/类签名——从中正则提取符号名（`def X` / `class X` / `func X` / `function X` / 首个标识符）即得 file+symbol，零额外解析成本。

### 3. 生成文件判定规则

`knowledge/diff_archive.py` 模块级常量（可测纯函数 `is_generated_file(path) -> bool`）：

```python
GENERATED_FILE_PATTERNS = (
    # lockfiles
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "uv.lock", "poetry.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "Pipfile.lock",
    # 构建产物/vendor 目录前缀
    "dist/", "build/", "node_modules/", "vendor/", ".next/", "__pycache__/",
    # 后缀
    "*.min.js", "*.min.css", "*.map", "*.pb.go", "*_pb2.py", "*_pb2_grpc.py",
    "*.generated.*", "*.snap",
)
# 启发式兜底：单文件 diff 超 N 行（默认 3000，可配）且所有 hunk 无 section_header → 视为生成文件
```

语义（locked decision"生成文件跳过"）：**跳过向量化与 MODIFIES_CHUNK 边，但原文仍进压缩归档**（`files[].is_generated=true` 标记）——归档求全、检索求精。Django migrations 文件建议**不跳过**（它们是交付代码的一部分，且体量小），在常量注释里说明该裁量。

### 4. 超大 diff：分层切块与批量写入

- **第一层（文件数）**：`max_files=500`（可配）截断 + `truncated=True`；
- **第二层（向量 chunk 配额）**：每次归档向量化 chunk 上限（建议 120，可配）——summary chunk + 按文件序逐文件切块，配额耗尽后剩余文件只在 summary 的文件清单中留名（P7"单 MR points 上限"防线）；
- **第三层（单 chunk）**：复用 `MAX_CHUNK_CHARS = 3000`（`chunking.py:29`），hunk 超长按既有 `_hard_split` 字符硬切；
- **写入**：points 走 `upsert_knowledge_points`（`vector_ops.py:117-145`，已分批 ≤100、失败 raise，**绝不绕开**）；MODIFIES_CHUNK 边逐条 `graph_store.add_edge`（每文件 ≤1 条边 + 总上限建议 200，避免万行 diff 产出千条边）。
- **embedding 批量**：复用 `EmbeddingService.generate_embeddings_batch`（`ingestion.py:221`，已是批量接口）。

### 5. normalizer 编排（`knowledge/sources/task_result.py`）

```text
normalize(request):
  session = SubAgentSession.objects.aget(session_id=request.source_id)   # 源缺失 → [] + warning（13-03 契约）
  task_result = TaskResult（session OneToOne）
  repository = 解析（CodingSession FK → workflow output_data → git_url 兜底）
  archive = await diff_archive.archive_code_change(session, task_result, repository)
      # 内部: 凭证→client→get_branch_diff→unidiff→生成文件判定→压缩→
      #        CodeChangeArchive.update_or_create(uniq source 锚)→返回 archive
  plan_target = 解析关联方案 entity_id（coding_plan / workflow_plan / mcp_technical_plan，经 generate_entity_id）
  chunk 解析 = 对非生成文件逐 hunk 提取 (file, symbol, 行区间) → Symbol/ChunkRegistry 对齐（见下节）
  return [IngestionEvent(
      kind="code_change", origin=按路径(chat/workflow/mcp), source_kind="task_result",
      source_id=session.session_id, title=f"{branch} @ {short_sha}",
      content=diff 摘要文本（见 chunk 策略）, payload={commit_sha, branch, mr_url:"", files 统计...},
      project_id=..., repository_id=str(repository.id), event_time=回调时刻,
      edges=( EdgeSpec(IMPLEMENTED_BY, target=plan_target, reverse=True),       # 方案 →IMPLEMENTED_BY→ code_change
              *[EdgeSpec(MODIFIES_CHUNK, target_chunk_id=cid, metadata={...}) for 命中的 chunk] ),
  )]
```

diff 归档（DB 写 + Qdrant 无关）放 normalizer 内、`ingest_events` 之前执行——后台 background runner 上下文，耗时无碍；归档成功与向量化解耦（归档失败 raise → background_task_failed 响亮；向量化失败不回滚归档行——archive 是 source of truth，可由 reconcile/重触发补向量）。

### 6. EdgeSpec 向后兼容扩展（前置小改）

现状（`ingestion.py:75-86`）：`EdgeSpec(relation, target_entity_id, exclusive=False)`，语义固定"本事件实体为 source 的实体出边"。Phase 14 需要：

```python
@dataclass(frozen=True)
class EdgeSpec:
    relation: str
    target_entity_id: uuid.UUID | None = None      # 实体边
    target_chunk_id: uuid.UUID | None = None       # chunk 边（MODIFIES_CHUNK）—— XOR
    exclusive: bool = False
    reverse: bool = False                          # True = 本事件实体为 target（IMPLEMENTED_BY：方案→code_change）
    metadata: dict | None = None                   # 透传 graph_store.add_edge(metadata=...)
```

`apply_edge_specs` 同步扩展：chunk 边的幂等判断用 `EdgeRecord.target_chunk_id` 比较（`graph_store.py:73` 已携带该字段）；reverse 边把 source/target 互换后走同一逻辑。全部默认值保证 13-03 两个 normalizer 与 13-04 reconcile 零改动。`graph_store.add_edge` 已原生支持 `target_chunk_id` + `metadata`（`graph_store.py:156-175`，XOR 校验在 line 174-175），**无需动 GraphStore**。

## MODIFIES_CHUNK 懒解析设计（ENH-01）

### 对齐资产盘点（实读结论）

| 资产 | 关键事实 |
|------|---------|
| `ChunkRegistry`（`code_relations/models.py:39-109`） | PK=chunk_id（uuid5，与 Qdrant point 1:1）；字段 repository / branch_name（""=base）/ file_path / chunk_index / line_start / line_end（可 NULL，历史数据未回填） |
| `generate_chunk_id`（`code_relations/utils.py`） | `uuid5(NAMESPACE_REPO, f"{repo_id}:{file_path}:{chunk_index}")`（base 分支）——**没有 chunk_index 无法正推**，对齐必须走查表 |
| `codegraph.Symbol`（`codegraph/models.py:12-47`） | name / symbol_type / file_path / start_line / end_line / branch_name / **chunk_id**（nullable UUID，indexer 已同源回填——`code_relations/symbol_chunk_binding.py`） |
| `KnowledgeEdge.target_chunk_id`（`knowledge/models.py:280-288`） | 弱引用已就位 + `kedge_target_xor` 约束 + db_index；`EdgeRelation.MODIFIES_CHUNK` 枚举占位（line 71） |

### 解析算法（创建时尽力对齐 + 三元组全集留档）

对每个非生成变更文件的每个 hunk：

1. **符号级（首选）**：`section_header` 提取符号名 →
   `Symbol.objects.filter(repository=repo, branch_name="", file_path=path, name=symbol).afirst()`
   → 命中且 `symbol.chunk_id` 非 NULL → `EdgeSpec(MODIFIES_CHUNK, target_chunk_id=symbol.chunk_id, metadata={"file_path": path, "symbol": symbol, "commit_sha": sha, "resolution": "symbol"})`。
2. **文件级降级（ENH-01 授权路径）**，触发条件 = 符号级任一环节失败：hunk 无 `section_header` / Symbol 查无 / `chunk_id` 为 NULL：
   `ChunkRegistry.objects.filter(repository=repo, branch_name="", file_path=path)` 中取与 hunk 行区间 `[target_start, target_start+target_length)` 相交（`line_start/line_end` 非 NULL 时）的 chunk；行号未回填（NULL）时取该文件 `chunk_index=0` 的 chunk 作文件代表。metadata `"resolution": "file"`、`"symbol"` 留原值或 ""。
3. **解析全失败**：**不建边**（XOR 约束要求 target 必填，无法建"悬空边"）——但三元组已记录在 `CodeChangeArchive.files[].hunks[]`，这就是 locked decision"file+symbol+commit_sha 记录即可，不强制实时对齐"的落点：日后 reconcile 扩展项或检索期可按归档重放对齐（重放入口 = 重投同 key IngestionRequest，边阶段幂等自愈）。

去重与上限：同一 (entity, chunk_id) 多 hunk 命中只建一条边（`apply_edge_specs` 的"同 target 复用"分支天然去重）；每次归档边数上限建议 200（可配），超出按文件序截断 + 日志。

**降级判定的可交付口径**（符号级是本阶段明确交付项）：metadata 的 `resolution` 字段使"符号级 vs 文件级"占比可统计——验收用合成夹具断言符号级路径至少在"Python 函数修改"用例上命中；真实仓库中 lockfile/无符号文件走文件级是预期行为而非降级失败。

### 反查路径（"这个函数被哪些需求改过"）

数据齐备即达成（检索面是 Phase 15）：`chunk_id ←(target_chunk_id, db_index)— KnowledgeEdge —source→ code_change —IMPLEMENTED_BY(入边)— tech_plan —HAS_PLAN(入边)— work_item`。本阶段验收以 DB 断言走通该链为准（直接 ORM 查询或 graph_store.neighbors 组合），不需要给 GraphStore 加新遍历 API。

## diff 文本的 chunk 策略（INGEST-08 diff 类型补全）

现有 `chunk_knowledge_text`（`chunking.py:79-110`）按 markdown 标题切分——对 diff 完全不适用。新增**确定性纯函数** `chunk_diff_text(title, archive_files) -> list[KnowledgeChunk]`（仍在 `knowledge/chunking.py`，与既有函数并列）：

1. **chunk 0 = summary**（`chunk_kind="summary"`，既有惯例 chunk 0 固定 summary）：标题（分支@短 SHA + 方案标题）+ 变更统计（N 文件 +A -D）+ 全部文件清单（含被配额截断者）——这是中文 query 召回 diff 的主要落点（P5 跨语言缓解：summary 用中文措辞渲染）；
2. **每个非生成文件 = 若干 section chunk**（新 `chunk_kind="diff_file"`）：`文件路径标题行 + 该文件 hunks 文本`，超 `MAX_CHUNK_CHARS` 按 hunk 边界分包、单 hunk 超长 `_hard_split` 硬切；
3. **生成文件零 chunk**（只进归档与 summary 清单）；
4. 配额（默认 120 chunk）耗尽即停。

payload 影响（以 `knowledge/collection.py` 为唯一事实源核对）：
- `chunk_kind` 是**非索引必带字段**（`KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS`，line 69-76）——新增 `"diff_file"` 取值**不改键集合**，`KNOWLEDGE_SCHEMA_VERSION` 不动、payload 回归测试键集合断言不动；
- `file_path` 必带字段现被 `build_knowledge_points` 硬编码空串（`vector_ops.py:102`）——建议给 `KnowledgeChunk` 增加 `file_path: str = ""` 默认字段（frozen dataclass 加默认值字段向后兼容），`build_knowledge_points` 改读 `chunk.file_path`，diff_file chunk 携带真实路径（Phase 15 按文件过滤检索的逃生门，且本来就是 schema 预留语义）。

ingest 路径分叉：`ingest_events` 步 1 写死 `chunk_knowledge_text(event.title, event.content)`（`ingestion.py:219`、`revectorize_version` line 347 同）。两个选项：
- **A（推荐）**：`chunk_knowledge_text` 内按 entity kind 无感知保持现状，给 `IngestionEvent` 加 `chunk_strategy: str = "text"` 默认字段，`ingest_events`/`revectorize_version` 按其分发到 `chunk_diff_text`（diff 时 content 即"summary 文本 + 文件分节的确定性拼接"，函数从 content 重新切）——要求 chunk_diff_text 能从 content 还原切块，故 **content 本身按"摘要 + per-file 分节（`## file: path` 标题）"格式生成**，diff 切块退化为"按 `## file:` 标题切 + 硬切"，可直接复用既有标题切分机制；
- **B**：content 仍是全格式文本，但直接复用现有 `chunk_knowledge_text`（markdown 标题切分 + 贪心合并 + 硬切对"## file: 路径"分节文本同样成立）。

**推荐 B 的简化形态**：normalizer 生成 content 时就用 `## file: {path}` 做二级标题、生成文件不进 content、超配额文件只留清单——则现有 chunker 原样可用（标题切分天然按文件分块），无需动 `ingest_events`，`chunk_kind` 区分退化为可选优化（summary/section 已够 Phase 15 起步）。这是改动最小、回归面最小的路径；`chunk_kind="diff_file"` 与 `file_path` 填充作为同 plan 内的增强项（动 `KnowledgeChunk`/`build_knowledge_points` 两处，各一行级别）。规划者按工期取舍，**content 格式锁定 `## file: {path}` 分节是两案共同前提**。

注意 content 体量上限：content 落 `KnowledgeEntityVersion.content`（TextField）+ payload——diff 摘要 content 建议总上限 ~200KB（约 60+ chunks），全文细节永远以 CodeChangeArchive 压缩归档为准，content 只是"可检索投影"。

## Architecture Patterns

### System Architecture Diagram

```text
┌─ 触发点（只投递，零取材）────────────────────────────────────────────┐
│ plan_generation.execute 成功尾部 ──┐                                  │
│ node_approved hook（审批）─────────┤                                  │
│ callbacks._handle_completed ───────┼─ aschedule_ingestion(             │
│ feishu webhook 4 handlers ─────────┘     IngestionRequest)             │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ on_commit + background runner（13-02 既有）
┌─ normalizer（后台取材）────────▼──────────────────────────────────────┐
│ workflow_plan.py ── NodeExecution.output_data → [work_item锚, tech_plan]│
│                                                + HAS_PLAN(exclusive)    │
│ feishu_work_item.py ── TriggerLog → 飞书 API 全量快照 → [work_item]     │
│ task_result.py ── SubAgentSession/TaskResult                            │
│      │                                                                  │
│      ├─► DiffArchiver: GitCredential→client.get_branch_diff(全量)       │
│      │     → unidiff 解析 → 生成文件判定 → zlib 压缩                     │
│      │     → CodeChangeArchive(update_or_create) ◄── MR 创建点二段回填   │
│      ├─► Symbol/ChunkRegistry 对齐 → MODIFIES_CHUNK EdgeSpec(metadata)  │
│      └─► [code_change 事件 + IMPLEMENTED_BY(reverse) + MODIFIES_CHUNK]  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ ingest_events（六步序，13-02 原样）
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
        PG 实体/版本       GraphStore 边        Qdrant delivery_knowledge
     （版本翻转/幂等）   （add_edge 含 chunk 边）  （summary+diff_file chunks）
```

### Recommended Project Structure（新增/修改文件）

```text
server/knowledge/
├── models.py            # [修改] +CodeChangeArchive
├── migrations/000X_*.py # [新增] CodeChangeArchive migration
├── ingestion.py         # [修改] EdgeSpec 扩展(target_chunk_id/reverse/metadata) + apply_edge_specs
├── chunking.py          # [可选修改] KnowledgeChunk.file_path 默认字段（推荐 B 时 chunker 本体不动）
├── vector_ops.py        # [可选修改] file_path 从 chunk 读
├── diff_archive.py      # [新增] DiffArchiver：拉取/解析/判定/压缩/归档/chunk 对齐/attach_mr_url
└── sources/
    ├── __init__.py      # [修改] 注册表 +3 行
    ├── workflow_plan.py # [新增]
    ├── task_result.py   # [新增]
    └── feishu_work_item.py # [新增]
server/services/git_platform/
├── base.py              # [修改] +get_branch_diff 抽象方法
├── github_client.py     # [修改] 实现（repo.compare 提 patch）
└── gitlab_client.py     # [修改] 实现（repository_compare 提 diffs）
server/workflows/hooks/
└── knowledge_ingest.py  # [新增] node_approved hook（仿 feishu_sync.py）
server/workflows/engine/scheduler.py  # [修改] __init__ 注册 hook（仿 :121-125）
server/workflows/nodes/ai/plan_generation.py  # [修改] 接线 ~5 行
server/subagent/api/callbacks.py              # [修改] 接线 ~8 行
server/feishu/views.py                        # [修改] 4 handler 接线 ~20 行
server/orchestration/coding_graph.py          # [修改] attach_mr_url ~3 行
server/workflows/nodes/ai/coding.py           # [修改] attach_mr_url ~3 行
```

### Pattern 1: 触发接线统一形态（13-03 已验证，逐字复用）

```python
# Source: 13-03-SUMMARY established pattern（grep 锚点形态）
from knowledge import ingestion  # 函数内 lazy import 防循环

await ingestion.aschedule_ingestion(
    ingestion.IngestionRequest(source_kind="...", source_id="...", trigger="...")
)
# aschedule_ingestion 自身全吞异常（ingestion.py:120-130），接线处不包 try/except
```

### Pattern 2: normalizer 统一签名 + 源缺失降级（13-03 契约）

`async def normalize(request) -> list[IngestionEvent]`；后台按 source_id 重读源模型，源缺失返回 `[]` + warning 不 raise（`sources/mcp_plan.py:36-43` 样板）。

### Pattern 3: 凭证解析（locked：DB 加密凭证）

```python
# Source: orchestration/coding_graph.py:228-238（既有样板）
from common.encryption import decrypt_value
from repositories.models import GitCredential

cred = await GitCredential.objects.filter(repository=repo).afirst()
if cred is None or not cred.encrypted_token:
    # 无凭证：归档降级——只落元数据行（diff_compressed 空、truncated=True、error 注记），不 raise 拖垮摄取
    ...
token = decrypt_value(cred.encrypted_token)
client = get_git_platform_client(repo, token)
```

### Pattern 4: workflow hook 注册（仿 FeishuSyncHook）

```python
# Source: workflows/engine/scheduler.py:121-125（FeishuSyncHook 注册样板）
from workflows.hooks.knowledge_ingest import KnowledgeIngestHook
hook = KnowledgeIngestHook()
self.hooks.register_hook("node_approved", hook)
# HookManager.trigger 已逐钩子 catch（hooks/base.py:72-81）——异常隔离免费
```

### Anti-Patterns to Avoid

- **在触发点（请求/回调路径）做任何取材或网络调用**：飞书 webhook 超时即重推（P3）；接线只组装 ID。
- **绕开 `vector_ops`/`QdrantService` 直接拿 qdrant client**：丢掉 timeout/批量/失败响亮全部历史修复（P1/P7）。
- **`KnowledgeEdge.objects` 出现在 ingestion/normalizer/diff_archive**：边写只走 graph_store（13-02 验收 grep 同款约束，扩展后的 apply_edge_specs 仍是唯一边入口）。
- **按业务 filter 删/查 Qdrant 点**：版本下线沿用 upsert→tombstone→delete 序，Phase 14 零新增向量删除路径。
- **naive datetime**：飞书毫秒时间戳、Git ISO 时间一律转 aware（`require_aware` 在 `ingest_events` 入口会响亮拒绝，`ingestion.py:182`——这是防线不是许可）。
- **给 MODIFIES_CHUNK 建 FK 或要求 chunk 必须已索引**：柔性引用 + 解析不中不建边、归档留全集。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| unified diff 解析 | 手写 @@ 正则状态机 | `unidiff.PatchSet` | rename/binary/EOF 无换行/多 hunk 偏移全是边界坑；unidiff 12 年打磨 |
| hunk 所属函数识别 | tree-sitter 重新解析变更文件 | `hunk.section_header`（git 已算好）+ `Symbol` 表查询 | 零成本符号源；tree-sitter 路径需要文件全文（API 拉 diff 没有全文） |
| symbol→chunk 对齐 | 自写行号 bisect | `Symbol.chunk_id`（indexer 同源回填，`symbol_chunk_binding.py`）；NULL 时 `ChunkRegistry` 行区间查询 | 已有持久化绑定，运行时软对齐是被该模块明确取代的旧方案 |
| 摄取幂等/版本翻转/向量序 | 任何自写摄取逻辑 | `aschedule_ingestion` + `ingest_events`（13-02） | locked decision；六步序含四层幂等与 chaos 测试 |
| 工作项快照取材 | 自拼飞书 API 调用链 | `services/feishu.FeishuClient` + `work_item_context_service` 取材件（get_work_item / relations / extract_feishu_doc_refs / 文档读取） | 限流/权限/富文本解析已处理（PARTIAL 降级语义现成） |
| 批量向量写入 | 自调 qdrant upsert | `vector_ops.upsert_knowledge_points` | 批量≤100 + 失败 raise 语义（P1） |
| webhook 幂等 | 内存 set / 自建去重表 | `ProcessedEvent`（`feishu/views.py:123-139`）+ TriggerLog unique——均已在挂点上游生效 | 多进程/重启安全 |

## Common Pitfalls

### Pitfall 1: 平台 per-file diff 没有 `diff --git` 头，PatchSet 解析为空

**What goes wrong:** GitLab `changes[].diff` / GitHub `f.patch` 都是从 `@@`（或 `---/+++`）开始的文件体；直接 `PatchSet(body)` 得到 0 个文件、静默空结果。
**Why:** unidiff 需要 `---`/`+++` 文件头定界。
**How to avoid:** 逐文件包 `--- a/{old}\n+++ b/{new}\n` 头再解析（见 Code Examples）；单测用真实 GitLab/GitHub 响应样本钉死。
**Warning signs:** 归档 files_count 为 0 但统计 additions>0。

### Pitfall 2: GitHub 大文件 `patch=None` / compare 300 文件上限

**What goes wrong:** 万行生成文件（lockfile）在 GitHub API 中 patch 字段直接缺省；compare 单页最多 300 files——全量性静默丢失。
**How to avoid:** `f.patch is None` → 该文件按"仅元数据"归档（is_generated 同路径，additions/deletions 仍可得）；files==300 时标 `truncated=True` 并日志；大 diff 夹具需覆盖 patch 缺省分支（mock 即可）。
**Warning signs:** `truncated=False` 但 archive 文件数恰为 300。

### Pitfall 3: 回调路径阻塞或异常击穿宿主（zero-regression 红线）

**What goes wrong:** `_handle_completed` 是容器回调主干（`AllowAny`+token），任何新增同步耗时/未捕获异常都会让 runner 重试、CodingSession 状态机错乱。
**How to avoid:** 接线只投递（`aschedule_ingestion` 顶层全吞，A1 已测试钉死）；gate 判断只用已加载字段（session.task_type / p 里的 commit_sha），零额外查询；宿主套件（`test_callbacks_cross_repo_relevance.py`、`test_coding_session_graph_e2e.py` 等）零回归是验收项。
**Warning signs:** 回调响应时间上升；`callback_completed_ok` 与摄取日志出现在同一请求 span。

### Pitfall 4: 审批/更新事件重摄被 hash 短路后"以为丢数据"

**What goes wrong:** 审批通过但方案内容没变 → `_persist_sync` 三态判定 skip，没有新版本——若把"审批必须产生版本"当验收会误判 bug。
**How to avoid:** 明确语义：内容不变 = skip 是 INGEST-07 铁律（13-02 决策"hash 相等绝不产生新版本"）；审批留痕走边 metadata / payload（仅内容变化时落库）。测试按两个分支分别断言。
**Warning signs:** 测试断言"审批后 version+1"而未先改 content。

### Pitfall 5: 飞书文档正文把 content 撑爆 / 文档拉取失败拖垮快照

**What goes wrong:** PRD 文档数万字 + 多文档 → content 数百 KB，chunk 数失控；或文档无权限（PermissionDeniedError）导致整个 normalizer raise。
**How to avoid:** 复用 `_read_documents` 的逐文档 status 降级语义（permission_denied/not_found/rate_limited 都不 raise，`work_item_context_service.py:160-174`）；单文档截断（`truncate_doc_content` 已有，`feishu_doc.py:55`）+ content 总上限；快照 PARTIAL 仍入图（status 进 payload）。
**Warning signs:** 单 work_item 实体版本 chunk 数 > 40。

### Pitfall 6: 同一 work_item 双路（MCP 锚 vs 飞书快照）实体撕裂

**What goes wrong:** 若飞书 normalizer 的 source_id 拼接与 13-03 mcp 锚不字节级一致（顺序/分隔符/类型转 str 差异），同一工作项产生两个实体（P4）。
**How to avoid:** 三元组拼接**唯一引用** `knowledge/models.py` natural key 规则表 `{project_key}:{work_item_type_key}:{work_item_id}`；work_item_id 注意 int→str 一致性（McpWorkItemContext.work_item_id 是 BigInteger，TriggerLog.work_item_id 是 Char）；测试断言：mcp 锚先入 + 飞书快照后入 → 实体数 1、版本翻转、HAS_PLAN 边不重复。
**Warning signs:** 图中出现两个同名 work_item 实体。

### Pitfall 7: MODIFIES_CHUNK 边爆炸 / 误对齐 feature 分支 chunk

**What goes wrong:** 万行 diff 数百文件 × 多 hunk → 数千条边；或对齐时忘了 `branch_name=""` 过滤，命中 feature 分支 overlay chunk（chunk_id 命名空间不同，边指到临时分支的 chunk）。
**How to avoid:** 边数上限 + 同 chunk 去重；Symbol/ChunkRegistry 查询显式 `branch_name=""`（base 分支语义，`code_relations/models.py:54-56` 注释明确 ""=base）。
**Warning signs:** 单次归档 add_edge 调用 > 200；KnowledgeEdge.target_chunk_id 在 ChunkRegistry 中对应 branch_name 非空行。

### Pitfall 8: 归档与向量化的失败耦合

**What goes wrong:** diff 已归档落库，embedding 服务故障导致 ingest 失败 → 重触发时若 `update_or_create` 语义写错（如 get_or_create）会跳过归档更新；或归档失败被吞导致只有向量没有原文。
**How to avoid:** 归档 `update_or_create(source_kind, source_id)`（幂等可重入，diff_sha256 相同短路重压缩）；归档失败 raise（响亮，background_task_failed 兜底）；向量失败不影响已落归档行（KnowledgeEntityVersion.vector_synced=False 路径已有 needs_revector 自愈）。
**Warning signs:** CodeChangeArchive 行存在但对应 code_change 实体缺失（reconcile 可加检查项，非本阶段必须）。

## Code Examples

### unidiff 解析 + 符号提取（核心循环）

```python
# Source: github.com/matiasb/python-unidiff（README API）；section_header 语义为 git hunk 上下文行
import re
from unidiff import PatchSet

_SYMBOL_RE = re.compile(r"(?:def|class|func|function)\s+([A-Za-z_][\w]*)")

def parse_file_diff(old_path: str, new_path: str, body: str) -> list[dict]:
    """单文件 diff 体 → hunk 元信息列表（纯函数，确定性）。"""
    text = f"--- a/{old_path or new_path}\n+++ b/{new_path}\n{body}\n"
    hunks: list[dict] = []
    for pf in PatchSet(text):
        for h in pf:
            m = _SYMBOL_RE.search(h.section_header or "")
            hunks.append({
                "target_start": h.target_start,
                "target_length": h.target_length,
                "section_header": (h.section_header or "")[:200],
                "symbol": m.group(1) if m else "",
            })
    return hunks
```

### 压缩归档（zlib + BinaryField）

```python
# Source: Python stdlib zlib 文档
import hashlib, zlib

raw = full_diff_text.encode("utf-8")
archive = await CodeChangeArchive.objects.aupdate_or_create(
    source_kind="task_result",
    source_id=session.session_id,
    defaults={
        "diff_compressed": zlib.compress(raw, 6),
        "diff_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_diff_bytes": len(raw),
        ...
    },
)
# 读取侧 model property:
# @property
# def diff_text(self) -> str: return zlib.decompress(bytes(self.diff_compressed)).decode("utf-8")
```

### 符号级 → 文件级降级对齐

```python
# Source: 本仓库 codegraph/models.py:12-47 + code_relations/models.py:39-109（实读）
async def resolve_chunk(repo_id: str, path: str, symbol: str, start: int, length: int):
    from codegraph.models import Symbol
    from code_relations.models import ChunkRegistry

    if symbol:
        sym = await Symbol.objects.filter(
            repository_id=repo_id, branch_name="", file_path=path, name=symbol,
        ).afirst()
        if sym and sym.chunk_id:
            return sym.chunk_id, "symbol"
    end = start + max(length, 1) - 1
    reg = await ChunkRegistry.objects.filter(
        repository_id=repo_id, branch_name="", file_path=path,
        line_start__isnull=False, line_start__lte=end, line_end__gte=start,
    ).order_by("chunk_index").afirst()
    if reg is None:  # 行号未回填的历史数据：文件首 chunk 兜底
        reg = await ChunkRegistry.objects.filter(
            repository_id=repo_id, branch_name="", file_path=path,
        ).order_by("chunk_index").afirst()
    return (reg.chunk_id, "file") if reg else (None, "unresolved")
```

### GitLab / GitHub 全量分支 diff（git_platform 新方法体内核）

```python
# Source: python-gitlab repository_compare / PyGithub Comparison.files —— 既有
# compare_branches 实现（gitlab_client.py:284-292 / github_client.py:281-307）同 API 不同取数
# GitLab:
forward = await asyncio.to_thread(project.repository_compare, target_branch, source_branch)
for d in forward.get("diffs", []):
    MRDiffFile(old_path=d["old_path"], new_path=d["new_path"], diff=d.get("diff", ""),
               new_file=d.get("new_file", False), renamed_file=d.get("renamed_file", False),
               deleted_file=d.get("deleted_file", False))
# GitHub:
comparison = await asyncio.to_thread(repo.compare, target_branch, source_branch)
for f in (comparison.files or []):
    MRDiffFile(old_path=f.previous_filename or f.filename, new_path=f.filename,
               diff=f.patch or "",  # patch 可为 None（大文件）——按元数据归档
               new_file=f.status == "added", renamed_file=f.status == "renamed",
               deleted_file=f.status == "removed")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 运行时 SymbolChunkResolver 行号 bisect 软对齐 | `Symbol.chunk_id` 持久化同源绑定 | 既有（symbol_chunk_binding.py） | ENH-01 符号级 = 一次 ORM 查询 |
| 各入口自写摄取逻辑 | `aschedule_ingestion` + normalizer 注册表 | Phase 13 | 本阶段只写 normalizer，不碰摄取核心 |
| `get_merge_request_diff` 截断式 diff（节点上下文用） | 新增 `get_branch_diff` 全量（归档用） | 本阶段 | 两方法并存：截断版继续服务 code_review 节点 |
| TaskResult.modified_files（容器回传文件名列表） | CodeChangeArchive（全量 diff + 文件级解析） | 本阶段 | modified_files 保留（轻量 UI 用），归档为权威 |

**Deprecated/outdated:** 无——本阶段不替换任何既有路径，纯增量。

## Runtime State Inventory

> 本阶段非 rename/refactor，但涉及锁定契约的增量写入，按类别过一遍：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 新增 CodeChangeArchive 表（migration）；KnowledgeEdge 首次写入 target_chunk_id 路径 | migration 一张表；无存量数据迁移（None — 13-03 mcp 锚实体与新快照同 key 是设计内版本翻转，非迁移） |
| 锁定契约影响 | `KNOWLEDGE_SCHEMA_VERSION` 不变（chunk_kind 新值/file_path 填充均不改键集合）；natural key 表新增消费方（workflow_plan/task_result 字面量已预登记于 `models.py:97-98`，零漂移） | 回归测试键集合断言原样通过即证明 |
| Live service config | 飞书 webhook 事件订阅需包含 WorkitemUpdateEvent/StatusEvent/CommentEvent/CreateEvent（飞书项目后台配置，不在 git） | 验收前确认部署侧已订阅（人工核对项） |
| Secrets/env vars | None — 凭证全走 GitCredential DB 加密（locked），零新增 env |  |
| Build artifacts | `uv add unidiff` 改 pyproject/uv.lock；task/ 镜像不受影响（unidiff 仅 server 侧用） | server 镜像重建即可 |

## 测试策略

### 大 diff 夹具构造

- **合成生成器而非静态文件**：`tests/knowledge/helpers.py`（或 conftest fixture）提供 `make_large_diff(files=30, lockfile_lines=8000, code_files=20)`——确定性拼接 unified diff 文本：1 个 ≥8k 行 lockfile（pnpm-lock.yaml 风格 +行）+ 多个带 `@@ ... @@ def xxx():` section_header 的代码文件 hunk + 1 个 rename + 1 个 delete + 1 个 patch 缺省（GitHub None 分支）。≥10k 行总量满足 ROADMAP SC#5。
- 断言面：归档成功（压缩比 >3x、files JSON 完整）、生成文件零向量 chunk、向量 chunk ≤ 配额、`upsert_knowledge_points` 被分批调用、总耗时无外网调用（全 mock）。

### git platform mock

PyGithub / python-gitlab 非 httpx，respx 不适用。两层 mock：
- **DiffArchiver 单测**：monkeypatch `get_git_platform_client` 返回 fake `GitPlatformClient` 子类（`get_branch_diff` 返回夹具 MRDiffResult）——与现有 PR 节点测试同款手法；
- **client 方法单测**（get_branch_diff 本体）：monkeypatch `project.repository_compare` / `repo.compare`（`asyncio.to_thread` 透传 sync callable，直接替对象方法）。

### 触发点投递断言（13-03 模板）

`tests/knowledge/test_triggers.py` 扩展（或新文件 test_triggers_phase14.py）：monkeypatch `ingestion.aschedule_ingestion` 模块属性（13-03 已验证该手法对"模块属性调用时解析"形态全锚点生效），逐触发点断言 `IngestionRequest` 三元组：
- plan_generation 成功 → 投递一次；plan=None / status=failed → 零投递；
- `_handle_completed` coding 类型 → 投递一次；非 coding（repo_summary/explore）→ 零投递；重复回调（TaskResult 已存在）→ 零投递；
- feishu 四 handler 各投递一次（trigger=event_type）；重复 event_uuid → 零投递（ProcessedEvent 短路在上游）；
- node_approved hook → human_approval 节点审批且同 execution 有 ai_plan_generation → 投递；无 plan 节点 → 零投递；
- 异常隔离：`run_in_background` 抛 RuntimeError 时各宿主主流程仍成功（13-03 TestExceptionIsolation 同款三连）。

### 宿主回调零回归

接线 PR 必跑：`tests/test_callbacks_cross_repo_relevance.py`、`tests/test_coding_session_graph_e2e.py`、`tests/test_commit_confirm_api.py`、`tests/test_plan_generation_node.py`、`tests/test_feishu.py`、`tests/test_feishu_approval_integration.py`、`tests/mcp_tools/`——全部既有用例零修改零回归（13-03 同款验收口径）。

### 端到端链路断言（ENH-01 反查）

夹具内建 Repository + ChunkRegistry/Symbol 行（含 chunk_id 绑定）→ 跑 task_result normalizer 全流程（mock 平台 diff）→ ORM 断言：`KnowledgeEdge(relation=MODIFIES_CHUNK, target_chunk_id=已知 chunk, metadata.symbol/commit_sha 正确)` + 从 chunk_id 反向 join 到 work_item 实体链路可达；符号级与文件级（Symbol 缺失场景）两分支分别断言 `metadata.resolution`。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| unidiff | DiffArchiver | ✗（待 `uv add`） | 0.7.5（PyPI 实查） | 无需 fallback——安装即得 |
| PyGithub / python-gitlab | get_branch_diff | ✓（已在 server 依赖） | >=2.0 / >=4.0 | — |
| zlib/hashlib | 压缩/指纹 | ✓ stdlib | — | — |
| 飞书 API（运行时） | INGEST-04 快照 | 部署配置项 | — | 快照 PARTIAL 降级（文档拉取失败仍入轻量快照） |
| Qdrant / Postgres | 既有 | ✓（Phase 12/13 已在用） | — | SQLite + mock（测试态既有） |

**Missing dependencies with no fallback:** 无。
**Missing dependencies with fallback:** 飞书 API 凭证未配置的部署 → 快照降级路径（normalizer warning + 空事件或轻量事件）。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >=9.0.2 + pytest-django + pytest-asyncio（`server/pyproject.toml` 既有） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/knowledge/ -x` |
| Full suite command | `cd server && uv run pytest tests/knowledge/ tests/test_callbacks_cross_repo_relevance.py tests/test_plan_generation_node.py tests/test_coding_session_graph_e2e.py tests/test_feishu.py tests/test_feishu_approval_integration.py tests/mcp_tools/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | plan 节点成功/审批投递 + workflow_plan normalizer 双事件 + HAS_PLAN | unit | `uv run pytest tests/knowledge/test_triggers.py -k workflow -x` | ❌ Wave 0（扩展既有 test_triggers.py） |
| INGEST-02 | 回调投递 gate + task_result normalizer + IMPLEMENTED_BY | unit/integration | `uv run pytest tests/knowledge/test_triggers.py -k callback -x` | ❌ Wave 0 |
| KMOD-05 | DiffArchiver 归档（压缩/解析/元数据/MR 回填/幂等） | unit | `uv run pytest tests/knowledge/test_diff_archive.py -x` | ❌ Wave 0 |
| INGEST-04 | feishu 四事件投递 + 快照 normalizer + 同 key 版本翻转 | unit | `uv run pytest tests/knowledge/test_triggers.py -k feishu -x` | ❌ Wave 0 |
| ENH-01 | MODIFIES_CHUNK 符号级/文件级对齐 + metadata + 反查链路 | unit/integration | `uv run pytest tests/knowledge/test_diff_archive.py -k chunk -x` | ❌ Wave 0 |
| SC#5 大 diff | ≥10k 行夹具端到端不超时/配额生效 | integration | `uv run pytest tests/knowledge/test_diff_archive.py -k large -x` | ❌ Wave 0 |
| 宿主零回归 | 回调/plan 节点/feishu/mcp 套件 | regression | Full suite command | ✅ 既有 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/knowledge/ -x`
- **Per wave merge:** Full suite command + `uv run python manage.py makemigrations --check --dry-run`（仅归档表 plan 例外，须有且只有一个新 migration）
- **Phase gate:** Full suite 全绿 + `ruff check knowledge/ tests/knowledge/` + 验收 grep（`KnowledgeEdge.objects` 在 diff_archive/sources 零命中；`aschedule_ingestion` 各接线文件计数）

### Wave 0 Gaps

- [ ] `tests/knowledge/test_diff_archive.py` — KMOD-05 / ENH-01 / 大 diff
- [ ] `tests/knowledge/test_triggers.py` 扩展（或 test_triggers_phase14.py）— INGEST-01/02/04 投递与隔离
- [ ] 大 diff 夹具生成 helper（conftest 或 helpers）
- [ ] fake GitPlatformClient 测试替身
- [ ] Framework install：无（pytest 栈既有）；`uv add unidiff>=0.7.5` 在实现首个 plan 内完成

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（不新增端点；callbacks/webhook 既有 token 验证不动） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | 归档/实体 payload 必带 project_id/repository_id（既有 schema 强制，`vector_ops.py:107-112` 写入处自检）；Phase 15 检索期过滤的前提在本阶段写对 |
| V5 Input Validation | yes | webhook payload 经既有 token/幂等防线；diff 文本视为不可信数据——只解析不执行，unidiff 纯文本解析；content 体量上限防 DoS |
| V6 Cryptography | yes | Git token 走既有 `decrypt_value`（Fernet）；**禁止**把 token 写进日志/归档/payload（structlog 已有凭证脱敏配置） |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| diff 原文含密钥被向量化为可语义检索的泄漏面 | Information Disclosure | PITFALLS 既有提示：本阶段最低限度——生成文件跳过已排除多数 lockfile 噪音；diff 进 content 前可跑轻量 secret 正则脱敏（裁量项，见 OQ-3） |
| 伪造回调投毒归档（AllowAny 端点） | Spoofing/Tampering | 既有 CONTAINER_CALLBACK_TOKEN 校验在挂点上游（`callbacks.py:386-392`）；接线在校验之后，不开旁路 |
| 伪造飞书事件污染知识图谱 | Spoofing | 既有 webhook token 验证（`feishu/views.py:603-620`）+ ProcessedEvent 幂等在挂点上游 |
| 归档表越权读取 | Information Disclosure | 本阶段不暴露任何归档读 API（检索/入口在 Phase 15/16）；admin 仅 superuser |
| token 经 client 异常栈泄漏 | Information Disclosure | 平台 client 异常 str(e) 进日志——PyGithub/gitlab 异常一般不含 token；归档错误注记只存 error message 截断 |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | GitHub compare API 单次 ≤300 files、大文件 patch 缺省 | DiffArchiver | 截断标记口径错；mock 测试已覆盖 None 分支，真实阈值偏差只影响日志语义 [ASSUMED，文档方向正确但阈值未实测] |
| A2 | GitLab repository_compare 对万行 diff 单请求可承受（默认 timeout 内返回） | DiffArchiver | 大仓库实测可能需要调大 client timeout；降级 = truncated 归档 [ASSUMED] |
| A3 | `hunk.section_header` 在 GitLab/GitHub 返回的 diff 文本中保留（取决于平台生成 diff 时的 xfuncname 行为） | ENH-01 | 若平台 diff 不带上下文行，符号级命中率下降 → 文件级降级路径吃满（ROADMAP 已授权降级，不阻塞）[ASSUMED，需用真实 MR diff 样本验证] |
| A4 | 工作流产出方案的 work_item_id 可从 `WorkflowExecution.context` 取到（飞书触发链路） | 触发点 1 | 取不到则 workflow tech_plan 无 HAS_PLAN 锚——降级为单事件（链路在飞书快照侧仍可经三元组补连）[VERIFIED: approval.py:91-98 以同字段查询，但非全部触发链路都写入该字段——需规划期跑一条真实 workflow 确认] |
| A5 | unidiff 0.7.5 与 Python 3.14 兼容 | Stack | 纯 Python 无 C 扩展、零依赖，3.14 兼容风险极低；安装后 import 自检即验 [ASSUMED] |

## Open Questions

1. **OQ-1：审批留痕的边 metadata 更新**
   - What we know: `apply_edge_specs` 对"同 target 已有活跃边"跳过不更新 metadata；审批事件常落在该分支（内容未变）。
   - What's unclear: 审批时间/审批人是否必须可从图中查到（Phase 15/16 是否消费）。
   - Recommendation: 本阶段在 apply_edge_specs 复用分支加 metadata merge（一行 aupdate，graph_store 收口内），成本低、留好数据；若规划判定 YAGNI 可只进实体 payload。

2. **OQ-2：mr_url 是否进 code_change 实体 payload（还是只在归档行）**
   - What we know: 二段式回填时实体可能已摄取完成；重摄取（content 含 mr_url）会触发版本翻转，纯 payload 变更则被 hash 短路。
   - Recommendation: mr_url 只写 CodeChangeArchive（aupdate 即可）；code_change 实体 content 不含 mr_url（出处链接在 Phase 15 结果组装时按 source_id join 归档表取）。避免为一个 URL 翻转版本。

3. **OQ-3：diff secret 扫描脱敏是否纳入本阶段**
   - What we know: PITFALLS Security 表建议摄取前过 secret 规则；ROADMAP Phase 14 success criteria 未要求。
   - Recommendation: 本阶段仅做"生成文件跳过 + content 截断"；secret 正则脱敏列为 deferred（向 STATE.md blockers/后续 phase 提名），归档原文保真不脱敏（与 git 历史同权限面）。

4. **OQ-4：六类触发点口径**
   - What we know: ROADMAP 说"六类触发点全部接通"——chat(13)/MCP(13)/workflow(14)/编码回调(14)/飞书(14) 为五类，第六类应是"方案审批事件"（workflow node_approved + 飞书评论审批殊途同归）。
   - Recommendation: 规划时把"审批"作为独立触发类列入 must_have truths，避免验收口径漂移。

## Sources

### Primary (HIGH confidence)

- 本仓库实读（行级锚点全部经 Read 工具核对）：`knowledge/{models,ingestion,chunking,vector_ops,collection,graph_store}.py`、`knowledge/sources/{__init__,mcp_plan,coding_plan}.py`、`workflows/nodes/ai/{plan_generation,coding}.py`、`workflows/engine/scheduler.py`、`workflows/hooks/base.py`、`subagent/api/callbacks.py`、`subagent/models.py`、`services/git_platform/*`、`orchestration/coding_graph.py`、`feishu/{views,approval}.py`、`services/{feishu,feishu_doc}.py`、`mcp_tools/{models,work_item_context_service}.py`、`code_relations/{models,utils,symbol_chunk_binding}.py`、`codegraph/models.py`、`repositories/models.py`
- Phase 13 交付契约：`.planning/phases/13-ingest/13-02-SUMMARY.md`、`13-03-SUMMARY.md`
- PyPI JSON API 实查 unidiff（version 0.7.5 / 2023-03-10 / matiasb/python-unidiff）

### Secondary (MEDIUM confidence)

- GitHub REST compare API 文件数上限与 patch 省略行为（官方文档方向 + 社区共识，阈值未本地实测）
- python-gitlab `repository_compare` 全量 diffs 返回（与本仓库既有 `compare_branches` 实现取数路径一致佐证）

### Tertiary (LOW confidence)

- 平台 diff 文本中 `section_header` 的保留度（git xfuncname 行为依平台后端实现，需真实样本验证——A3）

## Metadata

**Confidence breakdown:**

- 触发点挂点：HIGH — 全部实读源码，行号与上下游契约核对
- 摄取管线复用面：HIGH — Phase 13 SUMMARY + 源码双重核对
- Standard stack：HIGH — 唯一新依赖经 registry 验证
- 平台 API 大 diff 边界：MEDIUM — 文档方向正确、阈值未实测（已转为 mock 覆盖 + truncated 防线设计）
- ENH-01 符号命中率：MEDIUM — 机制（Symbol.chunk_id/section_header）已验证存在，真实数据命中率未测（降级路径已获授权）

**Research date:** 2026-06-11
**Valid until:** 2026-07-11（仓库内部契约稳定；平台 API 行为建议实现期抽样实测一次）

---

## RESEARCH COMPLETE

Phase 14 全部三类触发点挂点已定位到行级（plan_generation.py:401 / scheduler node_approved hook / callbacks.py:614 / feishu views 四 handler），Phase 13 管线只需 3 个 normalizer + EdgeSpec 向后兼容扩展即可承载；新代码集中在 DiffArchiver（git_platform 新增 get_branch_diff 全量方法 + unidiff 0.7.5 解析 + zlib/BinaryField 压缩归档 + Symbol.chunk_id 既有绑定做符号级对齐、ChunkRegistry 行区间做文件级降级），唯一新增依赖 unidiff 已经 PyPI 验证。
