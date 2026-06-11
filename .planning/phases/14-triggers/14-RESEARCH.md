# Phase 14: 全触发点接入与 diff 归档 - Research

**Researched:** 2026-06-11
**Domain:** 触发点接线（workflow/编码回调/飞书）+ diff 归档（unidiff 解析/压缩存储）+ 代码图谱对齐（MODIFIES_CHUNK）— Friday AI brownfield
**Confidence:** HIGH（所有挂点/契约均实读本仓库代码并给出行级锚点；外部依赖仅 unidiff 一个，已经 PyPI 官方页验证）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

> 复制自 14-CONTEXT.md `<decisions>`，逐字：

All implementation choices are at Claude's discretion — pipeline/infrastructure phase。以 ROADMAP Phase 14 success criteria 与 Phase 12/13 已交付契约为准。

已锁定的硬约束（不可偏离）：
- 复用 Phase 13 统一摄取管线：触发点只构造 IngestionRequest/normalizer + `aschedule_ingestion`，不各写摄取逻辑
- 图写入只走 GraphStore；payload schema 以 `knowledge/collection.py` 常量为唯一事实源
- diff 归档表（KMOD-05）按 Phase 12 预留方式本阶段随 migration 建（CodeChangeArchive 当时定案不建 stub，本阶段定型）
- `MODIFIES_CHUNK` 边 target_chunk_id 不做 FK（Phase 12 XOR 约束已就位）；懒解析（file+symbol+commit_sha 记录即可，不强制实时对齐）
- Git 平台凭证走既有 git_platform service 层（数据库加密凭证，不读 env）
- 生成文件跳过、超大 diff 压缩存储（PITFALLS 防线）

### Claude's Discretion

All implementation choices are at Claude's discretion — pipeline/infrastructure phase。

### Specific Ideas

ENH-01 降级路径已获 ROADMAP 授权：符号级受阻 → 文件级起步不阻塞，符号级仍为本阶段明确交付项跟踪。

### Deferred Ideas (OUT OF SCOPE)

None — discuss skipped（infrastructure phase）。不在本阶段：检索（Phase 15）、入口暴露（Phase 16）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| KMOD-05 | 编码产出的全量 diff 归档落库（unidiff 解析到文件级），关联 commit SHA / MR URL / 仓库元数据，超大 diff 压缩存储 | §CodeChangeArchive schema、§DiffArchiver、§Package Audit（unidiff [VERIFIED: PyPI]）、zlib+BinaryField 压缩方案 |
| INGEST-01 | 工作流 `ai_plan_generation` 产出技术方案时自动摄取需求与方案实体并建 `HAS_PLAN` 边（含方案审批通过事件） | §触发点 1（plan_generation.py 成功尾部 + scheduler.approve_node 行级锚点）、workflow_plan natural key 已锁、trigger_data 取 work_item 锚 |
| INGEST-02 | 编码完成回调（TaskResult/CodingTask）时自动归档全量 diff、摄取 code_change 实体并关联方案/需求 | §触发点 2（三条编码完成路径的时序分析 + 推荐挂点）、§DiffArchiver、task_result natural key 已锁 |
| INGEST-04 | 飞书工作项关键事件摄取带事件时间快照（名称/描述/自定义字段/PRD 与方案文档正文/关联工作项） | §触发点 3（FeishuWebhookView 三事件 handler 锚点）、FeishuClient.get_work_item / get_work_item_relations / FeishuDocClient.get_document_content 能力清单 |
| ENH-01 | diff→chunk 符号级对齐：`MODIFIES_CHUNK` 边关联 ChunkRegistry（file+symbol+commit_sha 懒解析），反查"函数被哪些需求改过" | §MODIFIES_CHUNK 设计（codegraph.Symbol.chunk_id 已回填的符号级路径 + ChunkRegistry 行号/文件级降级阶梯 + metadata 载体） |
</phase_requirements>

## Summary

Phase 14 是纯 brownfield 拼装：Phase 13 的摄取管线（`IngestionRequest` → normalizer → `ingest_events` 六步版本翻转）已经把"触发点只接线"的成本压到每处 ≤5 行；本阶段三类新触发点（workflow 方案产出/审批、编码完成回调、飞书 webhook 三事件）全部有现成的行级挂点，且 5 处 Phase 13 接线模板可逐字复制。`graph_store.add_edge` 已原生支持 `target_chunk_id`（XOR 校验在 `graph_store.py:174`），MODIFIES_CHUNK 的图层地基零缺口。

真正的新代码集中在三块：① `CodeChangeArchive` 模型 + migration（zlib 压缩 BinaryField，knowledge app 内）；② `DiffArchiver` service（git platform 拉全量 diff → unidiff 解析 → 生成文件判定 → 归档 + 符号对齐）；③ `task_result` / `workflow_plan` / `feishu_work_item` 三个 normalizer + `chunk_knowledge_text` 的 diff-aware 分支。唯一新外部依赖是 `unidiff` 0.7.5（PyPI 官方页验证：周下载 1500 万、MIT、matiasb/python-unidiff，10 年历史）。

**最重要的时序发现**：编码完成回调（`callbacks.py:_handle_completed`）发生在 **MR 创建之前**——chat 路径的 PR 在 `coding_graph.create_pr_or_skip_node` 才创建，workflow 路径的 MR 在 `AICodingNode._resume_after_containers` 才创建。若把 diff 归档挂在容器回调上，将永远拿不到 MR URL。INGEST-02 的挂点必须放在 MR/PR 创建完成之后的两个锚点上（详见触发点 2）。

**Primary recommendation:** 全部触发点按 Phase 13 接线范式（lazy import + `aschedule_ingestion` + 异常全吞）落在本文档给出的行级锚点；DiffArchiver 作为 `task_result` normalizer 的后台执行体（重 IO 全部离开宿主路径）；MODIFIES_CHUNK 用 `KnowledgeEdge.metadata` 记 `{file_path, symbol, commit_sha, resolution}`，解析阶梯 = Symbol 行重叠 → ChunkRegistry 行重叠 → 文件级降级。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 触发点接线（投递 IngestionRequest） | 宿主代码（workflow 节点 / 回调 view / webhook view） | — | Phase 13 范式：宿主只投递 ID，零取材逻辑 |
| 取材 + diff 拉取 + 归档（DiffArchiver） | knowledge app（normalizer 后台执行体） | services/git_platform（diff API） | 重 IO 必须在 background runner 内，不阻塞请求/回调路径（P3） |
| diff 解析（unidiff）/ 生成文件判定 / 压缩 | knowledge app 纯函数层 | — | 确定性、无 IO，可单测（chunking.py 同款哲学） |
| CodeChangeArchive 持久化 | knowledge app models + migration | PostgreSQL/SQLite | CONTEXT 锁定 "knowledge/ 内新增 diff_archive 模型" |
| MODIFIES_CHUNK 边写入 | GraphStore（唯一收口） | code_relations/codegraph（只读对齐查询） | 锁定决策：图写入只走 GraphStore |
| 符号/chunk 对齐查询 | codegraph.Symbol + code_relations.ChunkRegistry（只读 ORM） | — | Symbol.chunk_id 已由 symbol_chunk_binding 回填，读即用 |
| 向量写入 | knowledge/vector_ops.py（既有薄层） | Qdrant | 锁定：payload schema 以 collection.py 常量为唯一事实源 |
| 飞书快照取材 | services/feishu.py + services/feishu_doc.py（既有 client） | 飞书开放平台 API | 凭证既有 service 层解析，不新增凭证通道 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `unidiff` | 0.7.5 | unified diff 解析到文件/hunk/行级（PatchedFile.is_added_file/added/removed、hunk 的 target_start/target_length） | 唯一被广泛使用的纯 Python diff 解析库，周下载 1500 万，API 恰好覆盖"文件级解析 + 行号区间"需求 [VERIFIED: PyPI https://pypi.org/project/unidiff/] |
| `zlib`（stdlib） | py3.14 内置 | diff 原文压缩存储 | 标准库零依赖；level=6 默认对文本 diff 压缩比 5–10×（lockfile 类更高）[ASSUMED] |
| Django `BinaryField` | django>=5.1 既有 | 压缩字节落库（PG bytea / SQLite BLOB） | 框架内置，双后端无差异 [ASSUMED] |

### Supporting（全部已在仓库内，零新增）

| Asset | Location | When to Use |
|-------|----------|-------------|
| `aschedule_ingestion` / `IngestionRequest` / `IngestionEvent` / `EdgeSpec` | `server/knowledge/ingestion.py:54-102` | 一切触发点与 normalizer |
| normalizer 注册表 | `server/knowledge/sources/__init__.py:19-22` `_NORMALIZERS` dict | 新增 3 个 source_kind 各登记一行 |
| `graph_store.add_edge(target_chunk_id=...)` | `server/knowledge/graph_store.py:156-192` | MODIFIES_CHUNK 边写入（XOR 校验 L174） |
| `get_git_platform_client(repository, token)` | `server/services/git_platform/__init__.py:113` | DiffArchiver 取 client |
| `GitCredential` + `decrypt_value` 模式 | `server/orchestration/coding_graph.py:583-594`（范例） | 凭证解析（锁定决策：DB 加密凭证） |
| `get_merge_request_diff` | `github_client.py:168` / `gitlab_client.py:190` | MR diff 拉取（需放大截断参数，见 Pitfall 2） |
| `compare_branches` | `github_client.py:258` / `gitlab_client.py:261` | skip-PR 路径的分支 diff 兜底（GitLab 返回含 per-file diff 文本） |
| `FeishuClient.get_work_item` / `get_work_item_relations` | `server/services/feishu.py:104 / 188` | 飞书快照取材（名称/描述/自定义字段/关联工作项） |
| `FeishuDocClient.get_document_content` | `server/services/feishu_doc.py:127` | PRD/技术方案文档正文取材 |
| `codegraph.Symbol`（含 `chunk_id` 回填字段） | `server/codegraph/models.py:12-63` | ENH-01 符号级对齐主路径 |
| `ChunkRegistry`（line_start/line_end nullable） | `server/code_relations/models.py:39-109` | 行号重叠对齐 + 文件级降级 |
| `run_in_background` / `transaction.on_commit` | `services/background_runner.py`（经 aschedule_ingestion 封装） | 已内置，不直接调用 |
| 接线测试范式（monkeypatch `knowledge.ingestion.aschedule_ingestion`） | `server/tests/knowledge/test_triggers.py:199-209` | 全部新触发点投递断言 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| unidiff 解析 | 手写正则解析 unified diff | rename/binary/no-newline-at-eof/hunk 头部边界全是坑，PITFALLS"Don't Hand-Roll"明令禁止 |
| 平台 API 拉 diff | 本地 `git clone` + `git diff` | 引入工作目录管理/磁盘清理/凭证注入三类复杂度；平台 API 已有封装且回调时分支必然已 push |
| zlib | gzip / zstd | gzip 仅是 zlib 加头部无收益；zstd 需新依赖，diff 归档非热路径，没必要 |
| BinaryField 存 PG | 对象存储（S3/MinIO） | 自托管部署不强制对象存储；万行 diff 压缩后 ~100KB 量级，PG 完全可承受；超阈值截断策略兜底 |
| 审批事件挂 hooks（HookManager `node_approved`） | 直接锚点在 `approve_node` 内 | hooks 注册在 `WorkflowEngine.__init__`（scheduler.py:89-125）每实例重复注册；直接锚点与 Phase 13 范式一致、测试更直接——**推荐直接锚点** |

**Installation:**

```bash
cd server && uv add "unidiff>=0.7.5,<0.8"
```

**Version verification:** `pip index versions unidiff` → `0.7.5`（2023-03-10 发布，API 稳定无 breaking 迭代）[VERIFIED: PyPI]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| unidiff | PyPI | 12 yrs（0.5 于 2014-12） | 15M/wk | github.com/matiasb/python-unidiff | [OK]*（见注） | **Approved** |

> *注：本机 slopcheck 不支持 `--json` 且默认查 **npm** 注册表（跨生态混淆，已中止其触发的 `npm install`，确认仓库 `package.json` / `node_modules` 零污染）。Python 侧改用双重人工验证：`pip index versions unidiff`（PyPI 存在，0.5→0.7.5 共 13 个版本横跨 2014–2023）+ PyPI 官方项目页核对（作者 Matias Bordese、MIT、homepage 指向 github.com/matiasb/python-unidiff、周下载 1500 万）。下载量级 + 版本历史长度 + 源仓库一致性三项均通过，slopsquat 风险可排除。
>
> **Packages removed due to [SLOP]:** none
> **Packages flagged [SUS]:** none
> zlib 为标准库，无需审计。

## 触发点挂点清单（核心交付 1：行级锚点）

### 触发点 1 — workflow `ai_plan_generation`（INGEST-01）

**1a. 产出方案成功路径**

- 挂点：`server/workflows/nodes/ai/plan_generation.py` `AIPlanGenerationNode.execute`，`result = await super().execute(context)` 返回后、`result.status != "failed"` 分支（L386-401 区间，`emit_sub_step("review", COMPLETED)` 附近）。
- 可得上下文：`result.output["plan"]`（结构化方案 dict，`map_output` L301-331 产出，含 title/summary/execution_plan）；`context.execution_id` + `context.node_id`（natural key 素材）；`context.workflow_execution`（取 project）；`context.trigger_data`（飞书 payload，见下）。
- natural key（已锁，`knowledge/models.py:97`）：`source_kind="workflow_plan"`，`source_id=f"{execution_id}:{node_id}"`。
- 接线形态（13-03 范式逐字复制）：

```python
# Source: server/chat/coding_session_service.py:586-591（Phase 13 既有范例）
from knowledge import ingestion  # lazy import 防循环

await ingestion.aschedule_ingestion(
    ingestion.IngestionRequest(
        "workflow_plan", f"{context.execution_id}:{context.node_id}", "workflow_plan_generated"
    )
)
```

- **work_item 锚实体来源**：`WorkflowExecution.trigger_data`（`workflows/models/execution.py:118`，JSONField，飞书触发时为 webhook payload）。normalizer 后台读 `execution.trigger_data` 提取 `payload.id` / `payload.work_item_type_key` + `project.feishu_project_key`，拼三元组 `{project_key}:{work_item_type_key}:{work_item_id}` 产出 work_item 锚事件 + `HAS_PLAN` exclusive EdgeSpec——与 `sources/mcp_plan.py:74-101` 双事件模式完全同构。trigger_data 无飞书工作项（手动触发）时只产出 tech_plan 单事件（mcp_plan.py:64-72 防御分支同款）。

**1b. 方案审批通过事件**

- 挂点：`server/workflows/engine/scheduler.py:1188 approve_node`，`hooks.trigger("node_approved", ...)`（L1210-1215）之后追加接线，按 `node_execution.node.node_type == "ai_plan_approval"` 过滤（NodeExecution.node 为 WorkflowNode FK；approve_node 入口的 node_execution 来自 `approval_callback.py:232-239` 的 `.filter(...).select_related("workflow_execution")`，**node 未必预加载，接线处需 `await` 安全获取 node_type**——可经 `sync_to_async` 或在 filter 链补 `select_related("node")`）。
- 飞书侧回调链（只为理解，不在此挂线）：`feishu/callbacks/approval_callback.py:25 handle_approval_approve` → `_schedule_approval_completion`（L207）→ `engine.approve_node`。挂 approve_node 同时覆盖飞书卡片与 API 两条审批入口。
- 可得上下文：`node_execution.approval_data`（含 `plan`、`document_url`、`approved/approver_id/approver_name/approved_at`——`aapprove` 写入）；`workflow_execution_id` + `node_id`。
- **审批事件的 source_id 难点**：审批节点（ai_plan_approval）与产出节点（ai_plan_generation）是两个 node_id。审批事件应**重摄同一 tech_plan 实体**（用产出节点的 natural key），否则图中出现两个方案实体。normalizer 方案：审批触发时传审批节点的 `{execution_id}:{node_id}`，normalizer 内沿 `NodeExecution.workflow_execution` 找同 execution 中 node_type=ai_plan_generation 的已完成 NodeExecution（output_data 含 plan 的那个），用**它的** node_id 派生实体——或更简单：plan_generation 与 approval 的 plan 数据相同，trigger 字符串区分 `workflow_plan_generated` / `workflow_plan_approved`，source_id 统一传**生成节点**的 key（审批接线处沿 DAG/前驱查询拿到生成节点 id）。规划时二选一即可，推荐后者（接线处多一次查询，normalizer 保持单纯）。
- **审批状态进版本的 hash 短路陷阱**：见 Pitfall 5——审批信息必须进 `content`（如尾部追加 `\n\n## 审批\n已通过 by {approver} at {time}`）才会产生新版本；只改 payload 会被 `content_hash` 相同短路丢弃。

### 触发点 2 — 编码完成回调（INGEST-02 + KMOD-05）

**时序事实（实读结论，决定挂点）**：

| 路径 | 容器回调 | MR/PR 创建时机 | 完成锚点 |
|------|---------|---------------|---------|
| chat CodingSession | `subagent/api/callbacks.py:573 _handle_completed` 创建 TaskResult（L599-608）→ resume langgraph | `orchestration/coding_graph.py:551 create_pr_or_skip_node`：skip 路径 L566-579（无 PR，`amark_completed(pr_url="")`）；PR 路径 L602-613（`client.create_merge_request` → `amark_completed(pr_url=result.mr_url)`） | **L571-579（skip）与 L605-613（PR 成功）两处** |
| workflow AICodingNode | 同上 `_handle_completed` → `_schedule_workflow_resume`（callbacks.py:617） | `workflows/nodes/ai/coding.py:507 _resume_after_containers` → `_create_mr_for_repo`（L1091，内部 L1123-1124 解凭证建 client）→ mr_results 聚合 L604-620 | **L620 `mr_results.append` 之后 / L658 返回 completed 之前**，逐 repo 接线 |
| 旧兼容路径（非 graph 管理） | `callbacks.py:512-517` `amark_completed(pr_url=task_result.pr_url)` | TaskResult 自带 pr_url（容器内建 MR 的历史模式） | 同处追加接线（低优先级，可与 chat 主路径共用） |

> `CodingTask`（`workflows/models/coding_task.py`）持有 commit_sha/pr_url/branch_name 字段（L103-119），但当前 AICodingNode 主流程经 SubAgentSession/TaskResult 运转，CodingTask 是 dispatcher 节点历史产物——**diff 归档以 TaskResult 为权威数据源**，ROADMAP 措辞"TaskResult/CodingTask"按 TaskResult 落地即可。

**推荐挂点（2 处必接 + 1 处可选）**：

1. `coding_graph.create_pr_or_skip_node`：PR 成功分支与 skip 分支各一次投递。`source_kind="task_result"`，`source_id=str(coding_session.subagent_session.session_id)`（natural key 表锁定 "TaskResult/session UUID str"；SubAgentSession.session_id 是 `sub-{hash}` 唯一串，`subagent/models.py:54`）。trigger 分别 `chat_coding_pr_created` / `chat_coding_pr_skipped`。
2. `AICodingNode._resume_after_containers` mr_results 循环后：逐 session 投递（pending_sessions 里有 session_id，L530-531），trigger `workflow_coding_completed`。
3. （可选兜底）`callbacks.py:_handle_completed` 旧兼容分支。

**normalizer（task_result）内可得字段**：

- `TaskResult`（`subagent/models.py:253-299`）：`branch_name` / `commit_sha` / `pr_url` / `modified_files`（list）/ `raw_output` / `session` FK。
- `SubAgentSession`：`session_id`、`node_execution`（→ workflow 路径回溯 plan）、`main_session`、`last_output`（含 task_type/repository 信息）。
- chat 路径仓库：`CodingSession.repository` FK（`chat/models.py:363-367`），经 `CodingSession.objects.filter(subagent_session=session)` 反查；`CodingSession.coding_plan` FK → 关联的 CodingPlan（→ tech_plan 实体 `("tech_plan","coding_plan",str(plan.id))`，**IMPLEMENTED_BY 边的对端**）。
- workflow 路径方案回溯：`session.node_execution.workflow_execution` → 同 execution 的 ai_plan_generation NodeExecution → `workflow_plan` 实体 key。
- **边方向注意**：`IMPLEMENTED_BY = 方案→代码变更`（models.py:67）。`EdgeSpec` 语义是"以本事件实体为 source 的出边"（ingestion.py:76-86），所以 IMPLEMENTED_BY EdgeSpec 必须挂在 **tech_plan 锚事件**上（target=code_change 实体 id），不能挂在 code_change 事件上。normalizer 产出 `[tech_plan 锚事件(短路重摄, 带 IMPLEMENTED_BY EdgeSpec), code_change 事件]`——mcp_plan.py 双事件模式同构；**skipped 事件仍执行边阶段**（ingestion.py:241-243 阶段 B 契约），锚事件 hash 不变也能补边，这正是该机制的设计用途。

### 触发点 3 — 飞书工作项关键事件（INGEST-04）

- 挂点（`server/feishu/views.py` FeishuWebhookView.post 事件分发 L656-667 之后的各 handler）：
  - `_handle_workitem_create`（L751）——工作项创建
  - `_handle_workitem_status`（L763）——状态变更（"触发编码"类事件以此进入）
  - `_handle_workitem_update`（L857）——字段修改（"工作项更新"）
  - "产出方案"事件已被 MCP（13-03 已接 `technical_plan_service.py:528`）与触发点 1b（审批通过）覆盖，webhook 侧无需重复。
- 接线形态：各 handler 尾部投递 `IngestionRequest("feishu_work_item", f"{project.feishu_project_key}:{work_item_type}:{work_item_id}", "feishu_workitem_<event>")`。**只投 ID，不在 webhook 路径做任何取材**——现状 `_fetch_and_update_work_item`（L720）已在请求路径同步拉工作项（为 TriggerLog），knowledge 摄取不要加重它（P3）。
- 幂等已有：`ProcessedEvent`（L125/131）+ TriggerLog `event_uuid` unique（L650-653）挡 webhook 重推；摄取层再有 hash 短路双保险。
- **normalizer（feishu_work_item）取材清单**（全部后台执行）：
  - `create_feishu_client_for_project(project)` → `get_work_item(project_key, work_item_id, work_item_type)`（feishu.py:104）→ name / description（rich text 已解析）/ status / **fields 全量自定义字段 dict**（L159-164）。
  - `get_work_item_relations`（feishu.py:188）→ 关联工作项列表（relation_type/name/status）。
  - PRD/技术方案文档正文：fields 里 `KeyFields.PRD_URL` / `KeyFields.TECH_DOC_URL`（views.py:737-740 既有提取范例）→ 解析 doc token → `FeishuDocClient.get_document_content`（feishu_doc.py:127）。client 构造复用 `agents/tools/feishu_doc_tools.create_feishu_doc_client_for_project`（plan_approval.py:198-202 范例）。文档拉取失败降级为快照不含正文 + warning（13 范式：源缺失不 raise）。
  - 实体：`kind=work_item`，`source_kind="feishu_work_item"`（与 mcp_plan.py:77-79 已锁三元组格式一致——**同 key 重摄即把 13-03 的"轻量锚"升级为全量快照**，这是 13-03 SUMMARY 明示的 Phase 14 任务）。content 推荐 `name + description + 自定义字段表 + PRD/方案文档正文 + 关联工作项清单` 的 markdown 拼接（## 标题分段以契合既有 chunker）。
- **event_time**：飞书 webhook payload 的时间字段是毫秒时间戳/本地串（P2 警告）。统一 `datetime.fromtimestamp(ms/1000, tz=timezone.utc)` 或 `django.utils.timezone.now()` 兜底；naive datetime 会被 `require_aware`（graph_store.py:82）当场拒绝——这是已有防线，测试需覆盖。

## CodeChangeArchive 表 schema 建议（核心交付 2）

落位：`server/knowledge/models.py` 追加（或 `knowledge/models_archive.py` + `__init__` 导出），随本阶段 migration 建表（Phase 12 定案不预建 stub）。

```python
class CodeChangeArchive(models.Model):
    """编码产出全量 diff 归档（KMOD-05）。原文压缩存储，文件级摘要进 JSON。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 与 KnowledgeEntity(code_change) 同源弱引用（柔性引用原则，不 FK 到 entity）
    source_kind = models.CharField(max_length=50)        # "task_result"
    source_id = models.CharField(max_length=255)         # SubAgentSession.session_id
    repository = models.ForeignKey("repositories.Repository",
                                   null=True, on_delete=models.SET_NULL,
                                   related_name="code_change_archives")
    # Git 元数据（KMOD-05 显式要求）
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    branch_name = models.CharField(max_length=255, blank=True, default="")
    base_branch = models.CharField(max_length=255, blank=True, default="")
    mr_url = models.URLField(blank=True, default="")
    mr_id = models.CharField(max_length=64, blank=True, default="")
    # 压缩 diff 原文（zlib.compress(raw.encode("utf-8"))）
    diff_compressed = models.BinaryField()
    diff_size = models.PositiveIntegerField()            # 解压后字节数
    compressed_size = models.PositiveIntegerField()
    diff_sha256 = models.CharField(max_length=64)        # 幂等/完整性校验
    truncated = models.BooleanField(default=False)       # 平台 API 截断标记
    # unidiff 文件级解析结果（每项：path/old_path/change_type/additions/
    # deletions/is_generated/hunk_ranges/unresolved_symbols）
    files = models.JSONField(default=list)
    file_count = models.PositiveIntegerField(default=0)
    total_additions = models.PositiveIntegerField(default=0)
    total_deletions = models.PositiveIntegerField(default=0)
    event_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # 同一编码产出 + 同一 commit 只归档一次（重触发幂等锚）
            UniqueConstraint(fields=["source_kind", "source_id", "commit_sha"],
                             name="uniq_codechange_source_commit"),
        ]
        indexes = [
            models.Index(fields=["repository", "commit_sha"], name="idx_cca_repo_commit"),
            models.Index(fields=["source_kind", "source_id"], name="idx_cca_source"),
        ]
```

设计要点：

- **与 KnowledgeEntity 的关系**：不 FK。code_change 实体经 `generate_entity_id("code_change", "task_result", source_id)` 派生，归档行与实体经 `(source_kind, source_id)` 双向可查——与 ChunkEdge"柔性引用 + reconcile 兜底"先例一致。`KnowledgeEntityVersion.payload` 里存 `{"archive_id": str(...), "commit_sha": ..., "mr_url": ...}` 摘要即可，**diff 原文绝不进 payload/content 全量**（version.content 只放受控大小的归一化文本，见 chunk 策略）。
- **压缩策略**：恒压缩（zlib level 6），无条件分支减少测试矩阵；`diff_size`/`compressed_size` 双记可观测。读取用 `zlib.decompress(...).decode("utf-8")`。超大原文（如 >8MB 解压后）截断尾部 + `truncated=True`（上限可配常量）。
- **幂等**：unique 约束 `(source_kind, source_id, commit_sha)`；DiffArchiver 入口先 `aexists()` 短路，撞约束按 13 范式 warning 放弃。
- SQLite（dev/test）BinaryField 即 BLOB，migration 双后端无差异 [ASSUMED]。

## DiffArchiver service 设计（核心交付 3）

落位：`server/knowledge/diff_archive.py`（service + 纯函数），由 `sources/task_result.py` normalizer 调用——**DiffArchiver 整体运行在 background runner 内**（normalizer 即后台执行体），宿主路径只投 ID。

```text
任务回调/PR 创建锚点 ──IngestionRequest("task_result", session_id)──▶ aschedule_ingestion
                                                                        │ on_commit + background
                                                                        ▼
sources/task_result.normalize(request)
  ① 重读 TaskResult/SubAgentSession/CodingSession（select_related）
  ② 解析 repository + GitCredential → get_git_platform_client     ←锁定：凭证 service 层
  ③ 拉全量 diff：
       mr_url/mr_id 存在 → client.get_merge_request_diff(mr_id, max_files=放大, max_diff_lines=放大)
       skip-PR（无 MR）  → client.compare_branches(branch, base)（GitLab diffs 自带文本；
                            GitHub 需扩展 client 提取 file.patch——见 Open Question 1）
  ④ 拼回 unified diff 文本 → unidiff.PatchSet(text) 文件级解析
  ⑤ 逐文件：生成文件判定（glob + 标记启发式）→ is_generated 标注
  ⑥ zlib 压缩 + CodeChangeArchive.acreate（撞 unique 即幂等放弃）
  ⑦ 符号对齐（ENH-01）：hunk 行区间 × Symbol/ChunkRegistry → MODIFIES_CHUNK 边规格
  ⑧ 产出 IngestionEvent 列表：
       [tech_plan 锚事件(带 IMPLEMENTED_BY EdgeSpec), code_change 事件(content=归一化 diff 文本)]
  ⑨ 返回给 ingest_events → 既有六步版本翻转 + 阶段 B 边写入 + 阶段 C 向量序
```

### unidiff 解析要点

```python
# Source: https://pypi.org/project/unidiff/（官方 README）
from unidiff import PatchSet

patch = PatchSet(diff_text)          # 或 PatchSet(diff_text, metadata_only=True) 仅元数据
for pf in patch:                     # PatchedFile
    pf.path, pf.source_file, pf.target_file
    pf.is_added_file, pf.is_removed_file, pf.is_rename
    pf.added, pf.removed             # 增删行数
    for hunk in pf:                  # Hunk：target_start / target_length → 新文件行区间
        (hunk.target_start, hunk.target_start + hunk.target_length - 1)
```

- 平台 API 返回的是 per-file diff 片段（`MRDiffFile.diff` 不含 `diff --git` 头），拼回 PatchSet 前需为每文件补 `--- a/{old_path}\n+++ b/{new_path}\n` 头（或逐文件单独 `PatchSet` 解析——更稳，推荐逐文件）。
- hunk 的 `target_start/target_length` 给出**新文件侧行区间**，正是符号对齐的输入。

### 生成文件判定规则（建议常量表，置于 diff_archive.py 顶部）

```python
GENERATED_PATH_PATTERNS = (
    # lockfiles
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "uv.lock", "poetry.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
    # 构建产物 / vendor
    "dist/", "build/", "vendor/", "node_modules/", ".min.js", ".min.css",
    # 代码生成
    "_pb2.py", ".pb.go", "auto-imports.d.ts", "components.d.ts",
)
GENERATED_CONTENT_MARKERS = ("@generated", "DO NOT EDIT", "Code generated by")
```

- 判定 = 路径后缀/前缀匹配 **或** diff 前 N 行含标记串；命中 → `is_generated=True`：**跳过向量化与符号对齐，仍归档原文**（锁定决策"生成文件跳过"指跳过管线重活，归档不跳）。
- 单文件 diff 超行数阈值（如 >3000 行）即便未命中规则也按生成文件处置（防漏网的超大生成物）。

### 超大 diff 分层切块与批量写入（ROADMAP SC#5）

- **分层 = 文件 → hunk → 硬切**：`chunk_knowledge_text` 新增 diff-aware 分支（见下节），单 chunk ≤ `MAX_CHUNK_CHARS=3000`（chunking.py:29 既有上限，对 embedding token 上限已留余量）。
- **points 上限**：单 code_change 实体 diff chunk 总数封顶（建议常量 `MAX_DIFF_CHUNKS = 200`，可配）；超出部分只保留文件级摘要 chunk，原文仍在归档表。
- **批量写入**：向量走既有 `upsert_knowledge_points`（vector_ops.py:117，`_UPSERT_BATCH_SIZE=100` 已分批 + 失败 raise）；embedding 走 `EmbeddingService.generate_embeddings_batch`（ingestion.py:221 既有批量）——**零新基建**，只要 chunk 数受控。
- 大 diff 夹具验证路径：见测试策略。

## diff 文本 chunk 策略（INGEST-08 diff 类型补全）

**约束**：Phase 13 管线从 `version.content` 确定性重派生 chunks（`revectorize_version` ingestion.py:347 重走 `chunk_knowledge_text(entity.title, version.content)`）。因此 **diff chunks 必须可从 content 重派生**——不能在 normalizer 里旁路生成 chunks。

**推荐方案（最小侵入）**：

1. `code_change` 事件的 `content` = 受控大小的归一化文本：

```text
{title}                                  ← "fix: xxx (repo @ abc1234)"

## 变更摘要
{中文一句话摘要 + 文件清单 + 统计}          ← chunk 0 (summary)，服务中文 query 召回（P5）

## diff
diff --git a/... b/...                   ← 生成文件已剔除、超限已截断的 diff 正文
...
```

2. `chunk_knowledge_text` 增加 diff-aware 分支：探测到 `^diff --git ` 行（regex MULTILINE，与 `_HEADING_PROBE_RE` 同款写法）时，diff 区段按**文件边界**切段（`re.split(r"^(?=diff --git )", ...)`）、超长文件段按 hunk 头 `^@@ ` 再切、仍超长走既有 `_hard_split`；产出 chunk 标 `chunk_kind="diff"`。非 diff 区段（摘要）沿用既有标题分段。确定性与幂等语义不变（纯函数、同输入同输出）。
3. `chunk_kind` 在 payload 中是自由字符串（collection.py:69-76 必带字段，无枚举约束），新增 `"diff"` 值零迁移成本；Phase 15 检索可按 `chunk_kind` 过滤/配额（P5/P7 预留的逃生门）。
4. content 总大小上限（建议 ≤ 256KB）：normalizer 构造 content 时按 `MAX_DIFF_CHUNKS × MAX_CHUNK_CHARS` 预算截断 diff 区段并标注 `[diff truncated: 全文见归档 {archive_id}]`——全量原文永远在 CodeChangeArchive。

## MODIFIES_CHUNK 懒解析设计（ENH-01，核心交付 4）

### 载体与写入

- **边 metadata 即懒解析载体**：`KnowledgeEdge.metadata` JSONField（models.py:290）记
  `{"file_path": ..., "symbol": ..., "commit_sha": ..., "resolution": "symbol"|"file", "hunk_ranges": [[s,e],...]}`。
- 写入只经 `graph_store.add_edge(source_id=code_change_entity_id, target_chunk_id=chunk_id, relation="MODIFIES_CHUNK", valid_at=event_time, metadata=...)`——接口已就位（graph_store.py:156-192，XOR 校验 L174，`EdgeRelation.MODIFIES_CHUNK` 枚举 L71 占位已留）。
- **EdgeSpec 扩展决策**：`EdgeSpec` 目前只有 `target_entity_id`（ingestion.py:76-86），且 `apply_edge_specs` 按 `target_id` 匹配既有边（L313）。两个选项：
  - A（推荐）：扩展 `EdgeSpec` 增加 `target_chunk_id: uuid.UUID | None = None` + `metadata: dict | None = None`，`apply_edge_specs` 对 chunk 边按 `target_chunk_id` 匹配幂等——保持"边只有一条通路"的 13-02 契约，reconcile 检查项 6 自动覆盖。
  - B：chunk 边不走 EdgeSpec，DiffArchiver 在 normalizer 内直接调 graph_store（需自写幂等检查）。
  - 选 A 的理由：chunk 边**没有 DB 唯一约束防线**（见 Pitfall 4），把幂等收口在 apply_edge_specs 一处比散落强。
- 解析不出 chunk 的条目**不建边**（XOR 约束下边必须有 target）：file+symbol+commit_sha 落 `CodeChangeArchive.files[].unresolved_symbols`，留给 reconcile 扩展项/后续懒解析命令补建——这就是"懒解析不强制实时对齐"的落点。

### 解析阶梯（符号级 → 文件级降级）

输入：unidiff 解析出的 `(file_path, hunk target 行区间列表)` + repository + base 分支。

```text
① 符号级（主路径）：codegraph.Symbol.objects.filter(
       repository=repo, branch_name="", file_path=fp,
       start_line__lte=hunk_end, end_line__gte=hunk_start)
   → sym.chunk_id 非 NULL 即对齐成功（symbol_chunk_binding.py:30 已批量回填）
   → metadata.symbol = sym.name, resolution="symbol"
② chunk 行号级（Symbol 缺料时）：ChunkRegistry.objects.filter(
       repository=repo, branch_name="", file_path=fp,
       line_start__lte=hunk_end, line_end__gte=hunk_start)   ← 字段 nullable，过滤掉 NULL
   → chunk_id 直接命中，resolution="symbol"（chunk 即符号边界切块）
③ 文件级降级（①②均空，ROADMAP Note 授权）：ChunkRegistry.objects.filter(
       repository=repo, branch_name="", file_path=fp)
   → 该文件全部 chunk 建边（上限封顶，如 ≤20/文件），resolution="file"
④ 全空（文件未入索引/新增文件）：不建边，记 unresolved。
```

- **branch_name 取 `""`（base）**：MODIFIES_CHUNK 语义是"这次变更改了 base 代码图谱里的哪个块"——反查"这个函数被哪些需求改过"针对的是主干代码；feature 分支 chunk 命名空间（generate_chunk_id 掺分支名，utils.py:12-33）是临时 overlay，MR 合入后即过期，不应作为边 target。
- **文件级降级判定（ENH-01 降级条款）**：按文件而非全局降级——每个文件独立走阶梯，①②失败的文件自动落 ③；"符号级作为明确交付项跟踪"= ①② 路径与其测试必须交付，不是只交付 ③。
- 新增文件（`is_added_file`）：base 图谱必然无 chunk，直接 ④，等下次索引后由懒解析补——记录 unresolved 即为"跟踪"。
- 反查路径（验收用）：`graph_store.neighbors(chunk_id 所在边的反向)` 现仅支持实体 direction；chunk 反查走 ORM `KnowledgeEdge.objects.filter(target_chunk_id=..., invalid_at__isnull=True)`（target_chunk_id 有 db_index，models.py:280-288）→ source code_change 实体 → `traverse(direction="in")` 沿 IMPLEMENTED_BY/HAS_PLAN 回到需求。注意：**该 ORM 查询应封装进 GraphStore 新方法**（如 `chunk_in_edges(chunk_id)`），维持"图访问唯一收口"（P9 / grep 审计测试守护的是 raw SQL，但精神是收口）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| unified diff 解析 | 手写 regex 解析器 | `unidiff.PatchSet` | rename/binary/EOF 无换行/多 hunk 边界全是坑 |
| 触发投递/幂等/事务边界 | 各触发点自写 on_commit/去重 | `aschedule_ingestion`（13-02 已解决 A1 写法 + 全吞） | P3 历史事故（CurrentThreadExecutor）已封装 |
| 版本翻转/向量序 | 自写 upsert/tombstone | `ingest_events` 六步序 | INGEST-07 铁律 + chaos 测试已锁 |
| 图边写入 | 直接 `KnowledgeEdge.objects.create` | `graph_store.add_edge` | 锁定决策 + XOR/relation 校验在接口层 |
| Qdrant 写入 | 直接拿 qdrant client | `vector_ops.upsert_knowledge_points` | 60s timeout/分批/失败语义全部历史修复在内（P7） |
| 符号→chunk 对齐 | 自写行号 bisect | `Symbol.chunk_id`（已回填）+ ChunkRegistry 行区间 ORM | symbol_chunk_binding 已做过一遍并落库 |
| 飞书 API 调用 | 新写 http 调用 | `FeishuClient` / `FeishuDocClient` | token 缓存/rich text 解析/错误语义已封装 |

## Runtime State Inventory

> 本阶段为新增管线（非 rename/迁移），但涉及一个存量数据交互点，按要求显式声明：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 13-03 已摄入的 `feishu_work_item` 轻量锚实体（content=name+description） | 无需迁移——INGEST-04 同 natural key 重摄即版本翻转为全量快照（13-03 SUMMARY 明示设计意图） |
| Stored data | `delivery_knowledge` collection 既有 points | 零影响——新 chunk_kind="diff" 是 payload 自由字段，schema_version 不变（无索引字段增删） |
| Live service config | 飞书 webhook 订阅事件集（飞书项目后台配置，不在 git） | 验证部署侧已订阅 WorkitemUpdateEvent/WorkitemStatusEvent/WorkitemCreateEvent（代码已处理这三类，views.py:656-665） |
| OS-registered state | None — 无新增进程/调度注册 | — |
| Secrets/env vars | None — Git/飞书凭证全部走既有 DB 加密通道（GitCredential / project 凭证） | — |
| Build artifacts | `server/uv.lock` 将因 unidiff 新增而变更 | `uv add` 自动更新，随 migration 一起提交 |

## Common Pitfalls

### Pitfall 1: 把 diff 归档挂在容器回调上——MR 还不存在

**What goes wrong:** `_handle_completed`（callbacks.py:573）时刻 TaskResult.pr_url 几乎总是空串：chat 的 PR 在 langgraph `create_pr_or_skip_node` 才建，workflow 的 MR 在 `_resume_after_containers` 才建。挂错位置 = 归档行永远缺 mr_url/mr_id。
**How to avoid:** 挂点放 PR/MR 创建完成之后（触发点 2 的两处锚点）。skip-PR 路径显式接受 mr_url=""（branch diff 兜底）。
**Warning signs:** CodeChangeArchive 全表 mr_url 为空。

### Pitfall 2: 直接复用 `get_merge_request_diff` 默认参数——"全量"变"截断"

**What goes wrong:** 现有实现默认 `max_files=50, max_diff_lines=500` 且超限静默加 `[diff truncated]`（github_client.py:171-205 / gitlab_client.py:193-229）——为 code_review 节点的 LLM 上下文设计，不是归档语义。
**How to avoid:** DiffArchiver 调用时放大参数（如 max_files=1000, max_diff_lines=100000）并尊重返回的 `truncated` 标记落库。注意平台侧自身限制：GitHub PR files API 上限 3000 文件、单文件超大时 `patch` 字段缺失 [ASSUMED]；GitLab `mr.changes()` 对超大 diff 返回 collapsed/截断 [ASSUMED]——遇到时 `truncated=True` 响亮记录，不补本地 git 兜底（保持范围克制）。
**Warning signs:** 万行 lockfile MR 归档后 `total_additions` 远小于实际。

### Pitfall 3: 在 webhook/回调请求路径里拉飞书文档或 git diff

**What goes wrong:** 飞书 webhook 3 秒超时即重推（重复事件）；git diff 拉取秒级。P3 全文适用。
**How to avoid:** 触发点只投 `IngestionRequest`（一次 DB 注册 + on_commit）；所有取材在 normalizer（background runner）内。`aschedule_ingestion` 全吞异常（ingestion.py:120-130），接线处不包 try/except（13-03 纪律）。

### Pitfall 4: chunk 边没有 DB 唯一约束——重复边静默累积

**What goes wrong:** `uniq_kedge_active` 约束字段为 `(source_entity, target_entity, relation)`（models.py:302-307）；MODIFIES_CHUNK 边 target_entity 为 NULL，PG 把 NULL 视为彼此不同 → **约束对 chunk 边完全不生效**，重触发可无限插入重复活跃边。
**How to avoid:** 幂等收口在 `apply_edge_specs` 扩展逻辑（按 target_chunk_id 比对既有出边——`neighbors` 返回的 EdgeRecord 已含 target_chunk_id，graph_store.py:285）；测试显式覆盖"同事件 3 连发 chunk 边数不变"。可选加一条 partial unique（`fields=["source_entity","target_chunk_id","relation"]` condition 同款）作为 DB 防线——推荐加，migration 成本一行。
**Warning signs:** 同 (code_change, chunk) 对出现多条 `invalid_at IS NULL` 边。

### Pitfall 5: 审批通过事件被 hash 短路吞掉

**What goes wrong:** 审批不改方案正文。若审批信息只写 payload，`content_hash` 与产出时相同 → `_persist_sync` 三态判定 skipped（ingestion.py:438-447），payload 不更新、版本不产生，"含方案审批通过事件"验收失败。
**How to avoid:** normalizer 把审批状态写进 content（尾部追加审批段落）→ hash 变化 → 正常版本翻转，event_time=审批时间。注意 skipped 事件仍执行边阶段（自愈机制），所以 HAS_PLAN 边无论如何会补齐——但**快照语义**必须靠 content 变化承载。

### Pitfall 6: 飞书 event_time 毫秒时间戳 / naive datetime

**What goes wrong:** `require_aware` 当场 raise（graph_store.py:82-90），后台摄取整体 abort（响亮但功能缺失）。
**How to avoid:** normalizer 统一 `datetime.fromtimestamp(ms / 1000, tz=datetime.UTC)`；payload 缺时间字段时 fallback `timezone.now()`。单测 UTC 与 Asia/Shanghai 双时区跑（P2 警告信号）。

### Pitfall 7: 拿 feature 分支命名空间的 chunk_id 建 MODIFIES_CHUNK 边

**What goes wrong:** `generate_chunk_id` 对 feature 分支掺分支名（utils.py:26-29），分支索引是临时 overlay；对齐到 feature chunk 的边在分支删除/重索引后变孤儿。
**How to avoid:** 对齐查询恒用 `branch_name=""`（base）；新增文件在 base 无 chunk 属预期 ④ 路径。

### Pitfall 8: diff content 不可重派生破坏 revectorize

**What goes wrong:** 若 normalizer 旁路构造 chunks（不经 content），`revectorize_version`（ingestion.py:347）按 content 重切时 chunk 数/内容不一致 → point id 错位 + WR-01 防线误触发。
**How to avoid:** 严守"chunks 只从 content 派生"——diff-aware 逻辑放进 `chunk_knowledge_text`，content 即真理（本研究 chunk 策略节的设计动机）。

### Pitfall 9: 接线 import 形态触发 grep 验收/monkeypatch 失效

**What goes wrong:** 13-03 教训：`from knowledge.ingestion import aschedule_ingestion` 让 import 行也命中 grep 计数，且 from-import 绑定符号使测试 monkeypatch 模块属性失效。
**How to avoid:** 逐字复用 `from knowledge import ingestion` + `ingestion.aschedule_ingestion(...)` 属性调用形态（13-03 SUMMARY Deviation 1 定案）。

## Code Examples

### 触发接线（Phase 13 锁定范式，全部新挂点复制此形态）

```python
# Source: server/chat/coding_session_service.py:586-591（既有真实代码）
if result.created:
    from knowledge import ingestion  # lazy import 防循环

    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_coding_started")
    )
```

### 双事件 + exclusive 边 normalizer（task_result 复制此结构）

```python
# Source: server/knowledge/sources/mcp_plan.py:74-102（既有真实代码，缩略）
work_item_event = IngestionEvent(
    kind=EntityKind.WORK_ITEM, ...,
    edges=(
        EdgeSpec(
            relation=EdgeRelation.HAS_PLAN,
            target_entity_id=generate_entity_id("tech_plan", "mcp_technical_plan", str(artifact.id)),
            exclusive=True,
        ),
    ),
)
return [work_item_event, tech_plan_event]
```

### MODIFIES_CHUNK 边写入（GraphStore 已就位的接口）

```python
# Source: server/knowledge/graph_store.py:156-192（接口签名为既有真实代码）
await graph_store.add_edge(
    source_id=code_change_entity_id,
    target_chunk_id=chunk_id,            # XOR：不传 target_id
    relation=EdgeRelation.MODIFIES_CHUNK,
    valid_at=event_time,
    metadata={"file_path": fp, "symbol": sym_name,
              "commit_sha": sha, "resolution": "symbol"},
)
```

### 压缩归档

```python
import hashlib, zlib

raw = diff_text.encode("utf-8")
await CodeChangeArchive.objects.acreate(
    source_kind="task_result", source_id=session_id,
    diff_compressed=zlib.compress(raw, 6),
    diff_size=len(raw), compressed_size=None,  # len(compressed) 实际计算
    diff_sha256=hashlib.sha256(raw).hexdigest(), ...
)
```

### 大 diff 夹具构造（测试内程序化生成，不提交大文件）

```python
def build_large_diff(files: int = 30, lines_per_file: int = 400,
                     with_lockfile: bool = True) -> str:
    """≥10k 行混合 diff：lockfile 生成文件 + 多源码文件。"""
    parts = []
    if with_lockfile:
        body = "\n".join(f"+dep-{i}: 1.0.{i}" for i in range(8000))
        parts.append(
            "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n"
            "--- a/pnpm-lock.yaml\n+++ b/pnpm-lock.yaml\n"
            f"@@ -1,0 +1,8000 @@\n{body}"
        )
    for n in range(files):
        body = "\n".join(f"+    line_{i} = {i}" for i in range(lines_per_file))
        parts.append(
            f"diff --git a/src/mod_{n}.py b/src/mod_{n}.py\n"
            f"--- a/src/mod_{n}.py\n+++ b/src/mod_{n}.py\n"
            f"@@ -1,0 +1,{lines_per_file} @@\n{body}"
        )
    return "\n".join(parts)
```

## 测试策略（核心交付 6）

| 测试面 | 方式 | 参照先例 |
|--------|------|---------|
| 触发投递断言 | monkeypatch `knowledge.ingestion.aschedule_ingestion` 收集请求，断言 source_kind/source_id/trigger 三元组 | `tests/knowledge/test_triggers.py:199-209` `_collect` fixture |
| 异常隔离（宿主不被拖垮） | 注册体抛 RuntimeError，断言宿主流程（approve_node / create_pr_or_skip / webhook handler）仍成功 | test_triggers.py TestExceptionIsolation 三用例 |
| git platform mock | monkeypatch `get_git_platform_client` 返回 fake client（返回构造的 MRDiffResult）；或参照 `tests/e2e/fixtures/mock_services.py` | `tests/test_batch_pr.py` / `tests/mcp_tools/test_mr_tools.py` 已有 client mock 先例 |
| unidiff 解析/生成文件判定/压缩 | 纯函数单测（无 DB/网络），golden 断言 | `test_chunking.py` 风格 |
| 大 diff 夹具 | `build_large_diff()` 程序化生成 ≥10k 行（lockfile+多文件混合），断言：生成文件跳过向量化、chunk 数 ≤ MAX_DIFF_CHUNKS、归档 truncated/统计正确、摄取不超时 | PITFALLS P7 "looks done but isn't" 第 5 条 |
| MODIFIES_CHUNK 幂等 | 同事件 3 连发，chunk 边数不变（Pitfall 4 无 DB 防线，必测） | test_ingestion.py 幂等三连发模式 |
| 符号对齐阶梯 | fixture 造 Symbol（含 chunk_id）/ChunkRegistry（含行号）/空表三态，断言 resolution 字段 | — |
| 飞书快照 normalizer | mock FeishuClient/FeishuDocClient（respx 或 monkeypatch），文档拉取失败降级断言 | feishu 既有测试 + `respx` 已在 dev 依赖 |
| 宿主回调零回归 | 全量跑 callbacks/coding_graph/workflow 宿主套件 | 13-03 验证模式 |
| 审批事件 | approve_node 后投递断言 + content 含审批段（hash 变化产生 v2） | — |

## State of the Art

| Old Approach（Phase 13 现状） | Current Approach（Phase 14 交付后） | Impact |
|--------------|------------------|--------|
| feishu_work_item 实体 = 轻量锚（name+description） | 同 key 全量快照版本（自定义字段/文档正文/关联项） | 版本链记录工作项演化，13-03 预埋设计闭环 |
| 触发点 5 处（chat×3 + MCP×2） | +6 处（workflow 产出/审批 + 编码完成×2~3 + 飞书×3） | 六类触发点全通 |
| MODIFIES_CHUNK 枚举占位 | 真实边 + metadata 懒解析 | 需求→方案→代码→代码块全链路闭环 |
| diff 只在 code_review 节点临时拉取（截断） | 全量归档 + 压缩落库 + code_change 实体 | KMOD-05 |

**Deprecated/outdated:** 无——本阶段全部为增量，零既有行为变更（normalizer 注册表 + 锚点插入均为加法）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | GitHub PR files API 单文件超大时 `patch` 字段缺失、文件数上限 3000 | Pitfall 2 | 超大 MR 归档不完整——已用 truncated 标记兜底，风险=可观测性而非正确性 |
| A2 | GitLab `mr.changes()` 对超大 diff 有 collapsed/截断行为 | Pitfall 2 | 同上 |
| A3 | zlib level 6 对 diff 文本压缩比 5–10× | CodeChangeArchive | 仅影响磁盘估算，不影响正确性 |
| A4 | Django BinaryField 在 SQLite(BLOB)/PG(bytea) 双后端行为一致 | schema | migration/测试即时暴露，修复成本低 |
| A5 | 飞书 webhook payload 时间字段为毫秒时间戳 | 触发点 3 | normalizer 有 timezone.now() fallback，错也不崩 |

## Open Questions

1. **GitHub skip-PR 路径的全量 diff 文本获取**
   - What we know: GitLab `compare_branches` 内部 `repository_compare` 的 `diffs[].diff` 自带 per-file diff 文本（gitlab_client.py:292-304）；GitHub `compare_branches` 用 `repo.compare()` 只提取统计（github_client.py:296-306），但 PyGithub Comparison.files 的每个 file 对象有 `.patch` 属性可取 [ASSUMED]。
   - What's unclear: GitHub compare API 对超大比较的 patch 截断行为。
   - Recommendation: 给 GitPlatformClient 增加一个 `get_branch_diff(source, target) -> MRDiffResult` 抽象方法（GitLab 包 repository_compare、GitHub 包 compare+file.patch），DiffArchiver 统一消费 MRDiffResult；chat skip-PR 是少数路径，截断容忍度高。
2. **审批事件 source_id 的取法**（触发点 1b 列出的两个选项）
   - Recommendation: 接线处沿 execution 查 ai_plan_generation 节点 id，source_id 恒为生成节点 key——normalizer 单纯、实体唯一性有保证。规划时定案即可，两者实现成本相同。
3. **文件级降级的边数上限**（每文件 ≤20 条 chunk 边的封顶值）
   - Recommendation: 常量起步（`MAX_FILE_LEVEL_EDGES_PER_FILE = 20`），超出只记 metadata 不建边；无需配置化。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| unidiff (PyPI) | diff 解析 | ✓（registry 验证，待 `uv add`） | 0.7.5 | — |
| zlib | 压缩 | ✓ stdlib | py3.14 | — |
| GitHub/GitLab API | diff 拉取 | ✓ 既有 client + 凭证层 | PyGithub>=2.0 / python-gitlab>=4.0 已锁 | truncated 标记降级 |
| 飞书开放平台 API | 工作项快照 | ✓ 既有 FeishuClient/FeishuDocClient | lark 自研 httpx 封装 | 文档拉取失败降级为无正文快照 |
| Qdrant / Postgres | 向量/归档 | ✓ 既有栈 | — | SQLite dev 路径已验证（Phase 12/13） |

**Missing dependencies with no fallback:** 无。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >=9.0.2 + pytest-django + pytest-asyncio（asyncio_mode=auto）+ pytest-socket（--disable-socket） |
| Config file | `server/pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/knowledge/ -x` |
| Full suite command | `cd server && uv run pytest tests/knowledge/ tests/test_coding_session_graph.py tests/test_coding_session_service.py tests/mcp_tools/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | plan_generation 成功/审批通过各投递一次；审批 content 含审批段产生新版本；HAS_PLAN exclusive 边 | unit | `cd server && uv run pytest tests/knowledge/test_triggers.py -k workflow -x` | ❌ Wave 0（扩展 test_triggers.py） |
| INGEST-02 | 编码完成两路径（chat PR/skip + workflow MR）各投递；task_result normalizer 双事件 + IMPLEMENTED_BY 边；宿主 coding_graph/coding 节点零回归 | unit + regression | `cd server && uv run pytest tests/knowledge/test_triggers.py -k coding tests/test_coding_session_graph.py -x` | ❌ Wave 0 |
| KMOD-05 | unidiff 文件级解析正确；zlib 压缩往返一致；unique 约束幂等；commit_sha/mr_url/仓库元数据落库；migration check 干净 | unit | `cd server && uv run python manage.py makemigrations --check --dry-run && uv run pytest tests/knowledge/test_diff_archive.py -x` | ❌ Wave 0（新文件） |
| INGEST-04 | 飞书三事件投递；normalizer 快照含 fields/relations/文档正文；event_time aware；文档失败降级 | unit | `cd server && uv run pytest tests/knowledge/test_triggers.py -k feishu -x` | ❌ Wave 0 |
| ENH-01 | 符号级对齐（Symbol.chunk_id 命中）；行号级；文件级降级封顶；unresolved 记录；chunk 边 3 连发幂等；反查链路（chunk → code_change → 需求） | unit | `cd server && uv run pytest tests/knowledge/test_modifies_chunk.py -x` | ❌ Wave 0（新文件） |
| SC#5 大 diff | 10k+ 行夹具：生成文件跳过、chunk 封顶、归档统计正确、不超时 | unit（slow 可标记） | `cd server && uv run pytest tests/knowledge/test_diff_archive.py -k large -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/knowledge/ -x`
- **Per wave merge:** full suite command（含宿主 coding_graph / mcp_tools 零回归）
- **Phase gate:** full suite green + `makemigrations --check --dry-run` 干净 + `rg` 收口审计（`WITH RECURSIVE` 仍仅 graph_store.py；接线文件 `aschedule_ingestion` 计数符合预期）

### Wave 0 Gaps

- [ ] `server/tests/knowledge/test_diff_archive.py` — KMOD-05 + 大 diff 夹具（含 `build_large_diff` helper）
- [ ] `server/tests/knowledge/test_modifies_chunk.py` — ENH-01 阶梯 + 幂等
- [ ] `tests/knowledge/test_triggers.py` 扩展 — workflow/coding/feishu 三组投递与隔离用例
- [ ] `tests/knowledge/conftest.py` 扩展 — fake git platform client / fake FeishuClient fixture
- [ ] 依赖安装：`cd server && uv add "unidiff>=0.7.5,<0.8"`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（无新认证面；webhook token 校验既有，views.py:603-620） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | KnowledgeEntity 写入恒带 project_id/repository_id（payload 权限维度，collection.py 锁定）；CodeChangeArchive 带 repository FK——Phase 15 检索过滤的前提，本阶段写入侧不得留空可填字段 |
| V5 Input Validation | yes | webhook payload 字段取用前判空（既有 handler 风格）；diff 文本视为不可信输入——unidiff 解析失败 warning 降级为"只归档不解析"，不让畸形 diff 拖垮摄取 |
| V6 Cryptography | yes | Git/飞书凭证只经 `decrypt_value` + service 层（锁定决策）；**绝不**把 token 写入 CodeChangeArchive/payload/日志（structlog redact 已有兜底） |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| diff 原文含密钥被向量化放大（PITFALLS Security 表） | Information Disclosure | 生成文件/超限跳过已降低面积；diff chunk 仅 base 摘要+正文进向量，Phase 15 检索权限过滤为主防线；可选 secret 正则跳过（低成本加分项，非阻塞） |
| 伪造 webhook 污染图谱 | Spoofing/Tampering | 复用既有 token 校验（views.py:603），摄取接线在校验之后的 handler 内，无旁路 |
| runner 篡改 last_output 影响归档归属 | Tampering | 归属（repository/plan）从服务端权威 FK（CodingSession.repository / node_execution）取，不信任 `session.last_output`（callbacks.py:980-1010 contract-E1 同款纪律） |
| 回调重放重复归档 | Tampering | TaskResult 幂等（callbacks.py:587）+ CodeChangeArchive unique 约束 + ingest hash 短路三层 |

## Sources

### Primary (HIGH confidence)

- 本仓库实读（全部行级核对）：`knowledge/ingestion.py`、`knowledge/models.py`、`knowledge/graph_store.py`、`knowledge/chunking.py`、`knowledge/vector_ops.py`、`knowledge/collection.py`、`knowledge/sources/*`、`workflows/nodes/ai/plan_generation.py`、`workflows/nodes/ai/coding.py`、`workflows/engine/scheduler.py`、`workflows/hooks/base.py`、`subagent/api/callbacks.py`、`subagent/models.py`、`orchestration/coding_graph.py`、`feishu/views.py`、`feishu/callbacks/approval_callback.py`、`services/git_platform/*`、`services/feishu.py`、`services/feishu_doc.py`、`code_relations/models.py`、`code_relations/utils.py`、`code_relations/symbol_chunk_binding.py`、`codegraph/models.py`、`chat/models.py`、`chat/coding_session_service.py`、`mcp_tools/models.py`、`workflows/models/coding_task.py`、`workflows/models/execution.py`
- Phase 13 交付契约：`.planning/phases/13-ingest/13-03-SUMMARY.md`、`13-VALIDATION.md`
- unidiff PyPI 官方页（版本/下载量/API/源仓库）：https://pypi.org/project/unidiff/ — [VERIFIED]
- `pip index versions unidiff` → 0.7.5 — [VERIFIED: registry]

### Secondary (MEDIUM confidence)

- `.planning/research/PITFALLS.md`（P1–P10，本阶段直接消费 P3/P7 防线）

### Tertiary (LOW confidence / assumed)

- GitHub/GitLab API 对超大 diff 的截断细节（A1/A2）——训练知识，未逐页核对官方文档；已用 truncated 标记设计兜底

## Metadata

**Confidence breakdown:**

- 触发点挂点：HIGH — 全部实读 + 行级锚点 + 时序验证
- CodeChangeArchive / DiffArchiver：HIGH — 仓库内全部依赖能力已核实；唯一外部库已注册表+官方页双验证
- MODIFIES_CHUNK：HIGH — graph_store 接口/Symbol.chunk_id 回填/ChunkRegistry 行号字段全部实证；降级阶梯为设计建议（planner 可调）
- 平台 API 截断边界：MEDIUM — A1/A2 假设，有降级设计兜底
- Pitfalls：HIGH — 多数直接源自本仓库代码与 Phase 13 教训

**Research date:** 2026-06-11
**Valid until:** 2026-07-11（仓库内部契约为主，外部仅 unidiff 一项，稳定）

---

## RESEARCH COMPLETE

**Phase:** 14 - 全触发点接入与 diff 归档
**Confidence:** HIGH

一句话：三类触发点全部找到了可直接接线的行级锚点（关键发现：diff 归档必须挂在 MR/PR 创建之后而非容器回调），新代码集中在 CodeChangeArchive + DiffArchiver + 3 个 normalizer + chunk_knowledge_text 的 diff 分支，唯一新依赖 unidiff 0.7.5 已验证，MODIFIES_CHUNK 的图层接口（target_chunk_id XOR + Symbol.chunk_id 回填）零缺口、唯一硬坑是 chunk 边无 DB 唯一约束需代码级幂等。
