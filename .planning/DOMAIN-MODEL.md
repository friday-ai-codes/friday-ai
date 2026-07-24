# Friday AI · 领域模型设计（DOMAIN-MODEL）

> **作用**：定义 Friday 的核心领域模型——以飞书 work item 为脊柱的操作态聚合，配套编排状态机、结构化产物、排除文件 purge 策略与事件 taxonomy。是 `ROADMAP-vNext.md` 的数据模型底座。
>
> **配套文档**：`ROADMAP-vNext.md`（里程碑）、`PREFLIGHT.md`（前置修复/风险）。
>
> *最后更新：2026-06-14*

---

## 0. 设计原则

1. **两层分离**
   - **操作态聚合（新增 `delivery` app）**：work item 的当前状态、关系、关联方案/MR/评论/上线记录、编排会话状态——这是缺失的脊柱。
   - **知识/RAG 投影（已有 `knowledge` app）**：版本化内容快照，供检索。已对齐飞书 ID 三元组，后续**引用脊柱、不重建**。
2. **飞书为权威源**：work item 镜像字段以飞书为准；Friday 增强字段本地拥有；可写回字段 Friday 写飞书后镜像回来（见 §1 source-of-truth）。
3. **单一写入入口**：所有 work item 落库走 `WorkItemService.upsert()` 唯一服务，禁止各路径自己写表（见 §1 生命周期）。
4. **渐进迁移、不爆改**：canonical `TechnicalPlan` 立为新脊柱，存量 3 条 plan 路径挂软链逐步收敛，不全量双写（见 §5）。
5. **事件 taxonomy 早定义**：v0.7 编排即按统一事件词表产出 trace，v0.10 对外 API 只是不同 adapter（见 §10）。

---

## 0.1 不变量（Invariants）

这些是全系统必须恒成立的约束，任何设计/实现不得破坏：

- **INV-1**：一个飞书需求/缺陷在 Friday 内**只能对应一个 canonical `WorkItem`**（自然键三元组唯一）。
- **INV-2**：所有技术方案、评论、上线记录、PR/MR、知识实体**最终都能追溯到某个 `WorkItem`**（chat 自然语言需求例外，允许 null 但需显式标记）。
- **INV-3**：`knowledge` 是**检索投影，不是操作态事实源**；操作态状态/关系/事实只存 `delivery`。
- **INV-4**：排除文件命中后，Friday 工具层（RAG/检索/MCP/grep/agent/容器）**必须 fail-closed**（拒读、不降级泄漏）。
- **INV-5**：对外 Agent API 暴露的是 **progress/trace 事件，不是模型私有 CoT**。
- **INV-6**：work item 落库只经 `WorkItemService.upsert()`；技术方案解析/创建只经 `TechnicalPlanService`——**禁止旁路写表**。

---

## 1. 脊柱：`WorkItem`（交付主对象）

### 1.1 语义与生命周期（单一 upsert 入口）

`WorkItem` 是 Friday 的**交付主对象**，不是飞书 ID 的缓存表。它的身份 = 飞书三元组 `(feishu_project_key, work_item_type, work_item_id)`。

**所有创建/更新路径必须走 `WorkItemService.upsert(identity, source, payload)` 唯一入口：**

| 触发来源 | 场景 | 行为 |
|----------|------|------|
| 飞书 webhook | 工作项创建/状态/字段/评论事件 | upsert（镜像字段刷新） |
| 用户手动输入 ID | 控制台/MCP 按 ID 查询需求 | upsert（首次拉取并落库） |
| Bitable 历史导入 | 上线账本扒历史需求 | upsert（历史快照，标 origin=bitable_import） |
| MR URL 反查 | 给 MR 链接反推所属需求 | upsert（反查到则关联，查不到留 pending） |
| 编排/方案 | 方案/编码引用 work item | 只读，不创建（缺则要求先 upsert） |

upsert service 负责：身份去重、镜像字段刷新、保护 Friday 增强字段、记录 `last_synced_at`、发 `work_item.synced` 事件。

### 1.2 Source-of-truth：字段三分类

| 类别 | 含义 | 冲突规则 | 例 |
|------|------|----------|----|
| **mirror（镜像）** | 飞书权威，本地只读副本 | **飞书赢**：每次 sync 覆盖本地 | `title`、`status`、飞书自定义 fields |
| **friday_enhanced（增强）** | Friday 本地拥有，飞书没有 | **Friday 拥有**：sync 不动 | 业务线/模块归一化标签、内部备注、关联的内部实体 |
| **writeback（可写回）** | Friday 写回飞书字段，再镜像回来 | **Friday 发起写，飞书确认后镜像** | 群聊 `chat_id`、方案文档链接回填 |

- 本地存 `field_provenance`（哪些字段最近由谁更新）+ `last_synced_at`。
- writeback 字段本地存一份（写飞书成功后更新本地镜像；失败保留待重试标记）。

### 1.3 模型字段（pseudo-Django，delivery app）

```text
WorkItem
  id (uuid)
  feishu_project_key, work_item_type, work_item_id   # unique_together 自然键（已由真实 event 坐实）
  feishu_project_simple_name      # URL slug（如 example_platform），与 project_key 不同，用于建/解析 URL
  project        FK projects.Project (空间)           # null 允许（历史导入未映射）
  origin         choices: feishu_webhook|manual|bitable_import|mr_reverse
  # mirror（飞书权威）
  title
  status_state_key                # state_key（story 不透明如 fi46o4r6m；issue 为 OPEN 等）
  status_sub_stage                # sub_stage
  status_display_name             # 人类名：取自 current_nodes[].name / state_times[].name（无需单独映射 API）
  is_archived_state, is_init_state (bool)
  feishu_fields (JSON)            # 存完整 fields[].{field_key, field_name, field_value, field_type_key, field_alias}
  prd_url                         # = 别名 prd_url 的字段值（实测 field_000001 → acme docx 链接）
  tech_doc_url
  # friday_enhanced（Friday 拥有）
  business_line_normalized, module_normalized   # 由"小组"等自定义 select 字段派生（可选）
  internal_note
  # writeback（Friday 写回飞书再镜像）
  feishu_chat_id
  # 元数据
  field_provenance (JSON), last_synced_at, created_at, updated_at, event_time

WorkItemRelation        # ⚠ 实测：关系主要来自"关联型字段"，独立 relation 端点疑似失效（PF-10）
  source_work_item FK, target_work_item FK
  relation_type    choices: belongs_to_project|sprint|version|...   # 派生自 work_item_related_multi_select 字段
  source_field_key                # 来源字段（如 field_000008=所属项目 / planning_sprint / planning_version）
  origin           choices: feishu_field|feishu_relation_api|friday

WorkItemStatusEvent     # 状态变更事件流（cur/pre），非就地改写
  work_item FK
  pre_state_key, cur_state_key
  pre_sub_stage, cur_sub_stage
  operator, event_time
```

### 1.5 真实数据校准（实测 example_platform，2026-06-14）

> 用真实 plugin 凭证实地调用确认。✅=拉取成功，❌=失败。

- **URL 模式**：`https://project.feishu.cn/{project_simple_name}/{url_type}/detail/{id}`。⚠ **URL 段 ≠ API type_key**：`/project/detail/1000000004` 用 `type=project` 查 API 返回 `WorkItem Not Found(30005)`——容器型真实 type key 未知（需查"工作项类型"接口或 `所属项目` 字段反推）。
- **`work_item_type` 开放集**：实测 `issue`(缺陷,✅)、`story`(需求/看板,✅)；缺陷 type=`issue` 非 `bug`。
- **字段结构（重要修正）**：`fields[]` 每项 = `{field_key(稳定), field_name(人类标签), field_value, field_type_key, field_alias}`。⚠ 现有 `get_work_item` 拍平成 `{field_key: field_value}`，**丢失 field_name/type/alias**（PF-12）。`feishu_fields` 应存完整对象。
- **关系在字段里（重要修正）**：工作项间关系经 `work_item_related_multi_select` 字段表达——实测 story 1000000002 的 `所属项目`(field_000008)=`[1000000004]`、`所属迭代`(planning_sprint)、`规划版本/实际上车版本`(planning_version/actual_online_version)。独立 `get_work_item_relations` 端点 ❌（JSON 解析错，PF-10）。
- **状态人类名免映射**：story 响应自带 `work_item_status.state_key`(opaque) + `history[]`(状态变更史) + `current_nodes[].name`(="Sprint计划") + `state_times[].name`；issue 的 state 直接为 `OPEN`。→ `status_display_name` 取 current_nodes/state_times，无需另调映射 API。
- **关键字段别名**：`prd_url`(field_000001→`<tenant>.feishu.cn/docx/...`)、`小组`(field_000002,alias `example_platform_group`,="示例组A")=业务线/小组、`AI审查状态`(field_000003)。description 为字段。均 mirror。
- **评论 ❌**：`get_comments` 端点 JSON 解析错（PF-11）——评论摄取方案需重新确认正确端点。
- **凭证体系**：work item 走**项目 plugin token**(`project.feishu.cn`，plugin_id/secret/user_key) ✅；Bitable/文档在 `<tenant>.feishu.cn` 走**开放平台 token**，不同域——见 §4。
- **GitLab MR ✅**：`<internal-gitlab>` PRIVATE-TOKEN 调通；MR <id> `state=merged`、`target_branch=<release-branch>`(**非 master**)、有 `merge_commit_sha`、`changes[]` 含 6 文件 diff。→ 坐实历史 diff 锚定用 **MR target_branch + merge_commit_sha**，不能假设 master（DOMAIN §历史 diff / ROADMAP v0.6）。

### 1.4 幂等 / 刷新 / 失败 / 来源完整度

- **幂等键** = 自然键三元组 `(feishu_project_key, work_item_type, work_item_id)`；同键多次 upsert 收敛到同一行（保证 INV-1）。
- **刷新策略**：仅 mirror 字段按来源刷新；enhanced 不动；writeback 走专门写回流程。
- **来源完整度（关键）**：upsert **不假装每次都拿到完整飞书真相**。每次带 `source_completeness`，落 `WorkItemSyncState`（按 facet 记 `last_synced_at` + 完整度）：

```text
WorkItemSyncState
  work_item FK
  facet      choices: basic_fields|prd_body|tech_doc|comments|relations
  status     choices: complete|partial|missing|stale
  last_synced_at, source (feishu_webhook|manual|bitable_import|mr_reverse)
```

  - **MR URL 反查**：可能只有关联需求 URL → `basic_fields=partial`、其余 `missing`，标 pending 后续补全。
  - **webhook**：可能无文档正文 → `basic_fields=complete`、`prd_body=missing`。
  - **Bitable 导入**：状态可能过期 → `status=stale` + `as_of` 时间。
- **失败策略**：部分 facet 失败不回滚整体；落 sync error + 重试标记；缺料降配继续（与现有 `knowledge/sources` normalizer 范式一致）。

---

## 2. `WorkItemCommentEvent`（评论事件流，非快照）

评论不建"当前快照表"，而是 **append-only 事件流**，再投影出当前评论树——因为灰区讨论/澄清/方案再生成需要明确的事件边界。

```text
WorkItemCommentEvent   # append-only
  work_item FK
  feishu_comment_id, thread_parent_id        # 线程
  event_type   choices: created|replied|edited|deleted|approval
  author, body, attachments (JSON)
  approval_semantic  choices: none|approve|reject   # 审批语义（通过/驳回）
  event_time, ingested_at

# 当前评论树 = 对事件流的投影（视图/查询，非另一张事实表）
```

- "评论触发方案再生成"挂在 `created|replied|approval` 事件上，有清晰触发边界。
- 编辑/删除是事件，不就地改写——保留可追溯历史。

---

## 3. `Document`（区分外部飞书 / 内部生成）

不建泛泛的单一 Document。至少区分来源与可写回性：

```text
Document
  id
  document_type  choices: prd|tech_plan|release_note|sdd_spec|other
  source_kind    choices: external_feishu|internal_generated
  external_ref   # 飞书 doc token / 其他外部标识（external 时）
  canonical_url
  content_storage choices: snapshot|reference|both   # 正文存快照/存引用/二者
  content_snapshot_version FK -> DocumentVersion (null 允许)
  last_synced_at
  writeback_allowed (bool)        # 内部生成且需回写飞书时 true
  work_item FK (null 允许)        # REFERENCES 边的操作态对应
```

- 外部飞书文档（PRD/技术方案文档）：`source_kind=external_feishu`，存快照 + 引用，飞书为权威。
- 内部生成文档（上线说明、SDD spec）：`source_kind=internal_generated`，Friday 拥有，可能 `writeback_allowed`。
- 与 work item 的关联走 `REFERENCES` 边（knowledge 投影）+ 本地 `work_item` FK（操作态）。

---

## 4. Release 账本（宽容模型，adapter 后填）

先建**宽容模型**，不被 Bitable 列名绑死；真实多维表格结构到位后只做 adapter 字段映射。

```text
ReleaseBatch        # 一次上线/发布窗口
  id, name, released_at, source (bitable|manual), external_ref
ReleaseRecord       # 某需求/缺陷在某次上线中的记录
  batch FK, work_item FK (null 允许，反查中)
  status, note
ReleaseArtifact     # 证据：PR/MR、分支、commit、diff、上线说明
  release_record FK
  artifact_type choices: mr|branch|commit|diff|release_note|doc
  ref           # MR URL / sha / doc token
  payload (JSON)
```

**Bitable 接入坐标（来自真实链接）：**
- 链接 `<tenant>.feishu.cn/base/{app_token}?table={table_id}&view={view_id}`：`app_token=<app_token>`、`table_id=<table_id>`、`view_id=<view_id>`。
- **Bitable 在飞书开放平台**（`/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`），需**开放平台 tenant_access_token**（`feishu_app_id/secret`），**不是项目 plugin token**；且域名 `<tenant>.feishu.cn` 与项目 `project.feishu.cn` 可能是**不同租户**——adapter 要独立解析凭证来源。
- natural key：`{app_token}:{table_id}:{record_id}`。
- ⚠ **仍待**：表的**列结构 + 1~2 行样例**，才能定 `ReleaseRecord` 粒度（每行=需求/缺陷/MR/批次？）与字段映射。我无法实地读该 Bitable（鉴权），需你**贴列头/样例**或开权限/让我写诊断命令在你环境跑。

---

## 5. canonical `TechnicalPlan` + 统一 service + 迁移规则

### 5.1 模型

```text
TechnicalPlan (delivery)
  id, work_item FK (null 允许: chat 自然语言需求)
  origin   choices: chat|mcp|workflow|orchestration
  current_version FK PlanVersion
  status   choices: draft|under_review|approved|superseded|archived
PlanVersion
  plan FK, version, supersedes FK
  content (JSON: MergedPlan schema, 见 §7)
  content_hash, created_at
```

### 5.2 统一入口 `TechnicalPlanService`（= PlanProjectionService）

所有 plan 解析/创建/关联**只经它**（INV-6），"旧表 nullable link"不是策略、service 才是：

- `resolve(ref) -> TechnicalPlan`
- `create_from(origin, payload) -> TechnicalPlan`
- `link(old_record, canonical)`

旧表挂软链：`chat.CodingPlan.canonical_plan_id`、`McpWorkItemTechnicalPlan.canonical_plan_id`、workflow 经 `external_ref={execution_id}:{node_id}`。

### 5.3 创建时机（明确，避免"新有旧无"断层）

- **新编排（v0.7+）**：入口 eager 创建 canonical。
- **旧路径（chat/mcp/workflow 仍会产生）**：入口经 `TechnicalPlanService` **eager 投影**成 canonical（写旧表同时 link `canonical_plan_id`）。这是"投影"非"全量双写"——旧表是事实输入，canonical 是统一投影，service 保证不断层。
- **存量历史**：read-time **lazy migration**（首次读到无 canonical 的旧记录 → service 建 canonical + 回填链）。

### 5.4 读优先级与冲突规则（明确）

1. 旧记录有 `canonical_plan_id` → **读 canonical**。
2. 无 canonical 但旧记录完整 → **lazy 创建 canonical 再读**。
3. **冲突**：canonical 为唯一事实源；旧表视为历史输入，不一致以 canonical 为准。
4. **旧表后续编辑**：迁移期旧表**只读历史**；chat/mcp 的编辑入口改为操作 canonical，不允许绕过 service 改旧表制造分叉。
5. **canonical 归档/删除**：旧记录**保留**（历史输入不动），其 `canonical_plan_id` 置空或标 archived，**不级联删旧表**。

---

## 6. 方案编排状态机（v0.7 / v0.8）

#10 不只是流程图，要落到可持久化、可恢复的状态模型。

```text
PlanSession        # 一次"需求 → 主方案"编排
  id, work_item FK (null 允许)
  entrypoint  choices: workflow|chat
  status      choices: decomposing|routing|recalling|clarifying|researching|merging|done|failed
  current_plan_version FK PlanVersion (null)

RepoResearchTask   # 每仓一个并行调研子 agent
  session FK, repository FK
  subagent_session FK subagent.SubAgentSession (null until dispatched)
  status      choices: pending|running|done|failed|stale
  partial_plan FK PartialPlan (null)
  routed_confidence  # 来自 RepoRouterV2

PartialPlan        # 单仓调研产出（结构化，见 §7）
  research_task FK, content (JSON), valid (bool), invalidated_reason

Clarification      # 澄清问答
  session FK, question, answer (null), answered_at
  affected_partials (M2M RepoResearchTask)   # 回答后哪些 partial 要重跑

ArchitectMerge     # 架构师融合产出
  session FK, merged_plan_version FK PlanVersion
  validation_status choices: passed|failed, validation_report (JSON)

RepoCodingTask     # v0.8 多仓 wave 编码
  plan_version FK, repository FK, wave int
  depends_on (M2M self)        # 跨仓依赖（DAG）
  status, subagent_session FK
  produced_artifacts (JSON)    # 注入下游 wave 的产物（API 契约/diff）
```

**关键规则（可靠恢复的核心）：**
- **失败重试**：`RepoResearchTask`/`RepoCodingTask` 失败 → 单仓重试，不重跑整 session。
- **调研过期 invalidation**：仓库被重新索引（commit 变化）→ 关联 `PartialPlan.valid=False`，标 `stale`，融合前需重跑。
- **澄清后重跑**：`Clarification` 回答 → 仅 `affected_partials` 重跑，其余 partial 复用。
- **wave 调度**：`RepoCodingTask` 按 `depends_on` 拓扑分层；上游 `produced_artifacts` 注入下游 prompt/global_context。

### 6.1 SDD 扩展点（v0.7/v0.8 提前预留，v0.9 做全）

- `PlanSession`：若涉及仓库被标 SDD（`Repository.facets["methodology"]="SDD"`）→ 融合产物**额外生成 spec draft**（`Document(document_type=sdd_spec)`）。
- `RepoCodingTask`：标 `follow_openspec=True` → 编码容器 system prompt 注入 openspec 指引。
- 完整 spec 状态机/评审/gate/关联在 v0.9，但模型字段与扩展点 v0.7/v0.8 先留。

---

## 7. 结构化产物 schema

### PartialPlan（单仓）
```text
{ repository_id, research_summary, proposed_changes[],
  candidate_files[], api_contracts_exposed[],      # 本仓对外暴露的契约
  dependencies_on_other_repos[] }                  # 依赖其他仓的契约
```

### MergedPlan（主方案，PlanVersion.content）
```text
{ title, summary,
  api_contracts[],          # 跨仓契约汇总
  dependency_dag,           # 跨仓依赖顺序（拓扑）
  data_migrations[],        # 数据迁移
  compat_risks[],           # 兼容风险
  release_order[],          # 发布顺序
  rollback_plan,            # 回滚策略
  execution_plan[] }        # 每任务: repository_id + coding_instruction + dependencies
```

### PlanValidator（让架构师 agent 不只是"更贵的总结器"）
校验项：契约一致性（暴露↔依赖匹配）、依赖 DAG 无环、迁移顺序合理、兼容风险已标注、发布顺序与依赖一致、回滚完整。失败 → `ArchitectMerge.validation_status=failed` + 报告，要求重融合或澄清。（扩展现有 `verify_plan`，并修其 schema 漂移 bug，见 PREFLIGHT。）

---

## 8. 知识图谱投影如何引用脊柱

- `knowledge.KnowledgeEntity` 保持现有 natural key 对齐 `WorkItem`；新增对 `delivery` 模型的引用（FK 或 natural key），作**只读 RAG 投影**。
- 摄取管线（`knowledge/sources`）从 `delivery` 取权威数据生成版本化快照，**不反向成为操作态事实源**（INV-3）。
- 新增 `feishu_bitable`、`feishu_document` normalizer 时，源数据先经 `delivery` 的 service upsert，再投影入图。

---

## 9. 排除文件：安全边界 + purge 模式 + 数据面矩阵

### 9.1 安全边界（产品化措辞）

承诺：**"被排除文件从 Friday 的索引、检索、MCP、grep、agent、任务容器中不可见（fail-closed，INV-4）"**。
**不承诺**："从本地 git object / Git 历史物理消失"——bare 镜像对象可能残留，靠工具层 denylist 兜底。UI/文档必须如实说明，避免过度安全承诺。

### 9.2 两种 purge 模式（不混一个按钮）

| 模式 | 适用 | 覆盖范围 |
|------|------|----------|
| **普通排除** | 一般不想索引的文件/目录 | 清派生索引（Qdrant 主+overlay / ChunkRegistry / codegraph / repo_summaries / index_nodes）+ 各 clone 点过滤 + 工具 denylist（未来访问） |
| **敏感清理** | 命中密钥/敏感信息 | 普通排除 **+** 操作记录可控清理：message parts、agent trace（ActionLog）、`TaskResult`、`CodeChangeArchive` diff、knowledge content、prompt snapshot、错误日志可控范围 |

### 9.3 数据面矩阵

| 数据面 | 含敏感正文? | 普通排除 | 敏感清理 | 现状/手段 |
|--------|-----------|---------|---------|-----------|
| Qdrant 主 collection | 是 | ✓ | ✓ | `delete_by_file_path`（已有） |
| Qdrant overlay | 是 | ✓ | ✓ | 缺口：需扩 per-file 删 |
| ChunkRegistry / ChunkEdge | 是 | ✓ | ✓ | 部分（pre_delete 清边），单文件待补 |
| codegraph（Symbol/Edge/Endpoint） | 路径/符号 | ✓ | ✓ | `adelete_for_files`（已有） |
| repo_summaries / index_nodes | 摘要 | ✓ | ✓ | 缺口：重建 |
| bare 镜像 / worktree | 是 | denylist | denylist + 重建/重克隆 | 缺口：无 purge API |
| task 容器工作树 | 是 | clone 后过滤 | clone 后过滤 | 需传 exclude 列表进容器 |
| `CodeChangeArchive` diff | 是 | — | ✓ | 缺口：file 级 scrub |
| chat message parts / ActionLog trace | 可能 | — | ✓ | 缺口：可控范围清理 |
| `TaskResult` | 可能 | — | ✓ | 缺口 |
| prompt snapshot / 错误日志 | 可能 | — | ✓（可控） | 缺口 |
| 备份数据 | 可能 | — | ⚠ 应用层不强保证 | 基础设施层，文档化 caveat |

---

## 10. 事件 / trace taxonomy（v0.7 起产出，v0.10 对外 adapter）

统一内部事件词表（progress/trace，非 CoT，INV-5）。未来 OpenAI/Anthropic API 只是不同 adapter：

```text
work_item.syncing
knowledge.recalling
repo.routing
repo.research.started / repo.research.completed / repo.research.failed
clarification.asked / clarification.answered
plan.merge.started / plan.merge.completed
plan.validation.failed
coding.wave.started / coding.wave.completed
```

v0.7 编排即按此产出（落 trace），v0.10 暴露时复用同一 taxonomy + adapter 映射到 reasoning_summary / progress event。

---

## 11. 模型 → 里程碑落地

| 模型 / 能力 | 里程碑 |
|------------|--------|
| `WorkItem` + `WorkItemService.upsert` + `WorkItemSyncState` + `WorkItemRelation` | v0.6 首阶段 |
| `WorkItemCommentEvent` | v0.6 |
| `Document`（区分外部/内部） | v0.6 |
| `ReleaseBatch/Record/Artifact` + Bitable adapter | v0.6 |
| `TechnicalPlan/PlanVersion` + `TechnicalPlanService` + 迁移 | v0.7 |
| `PlanSession/RepoResearchTask/PartialPlan/Clarification/ArchitectMerge` + PlanValidator | v0.7 |
| `RepoCodingTask`（wave/DAG/产物注入） | v0.8 |
| SDD 字段/状态机/gate/评审/关联（扩展点 v0.7/v0.8 先留） | v0.9 |
| 排除文件 purge 两模式 + 数据面治理 | v0.5 |
| 事件 taxonomy（产出） | v0.7（对外 v0.10） |
| `AuditEvent`（横切治理） | 审计里程碑 |

---

# 实现级细化（§12 起）

> 以下为落地实现的细节补充：具体 Django 字段、服务方法签名、状态转移表、事件 payload 规格、真实数据字段附录、关键时序。供 plan-phase 直接参考。

## 12. 模型字段详表（delivery app，Django 级）

> 约定：`id` 一律 `UUIDField(primary_key, default=uuid4)`；时间戳 `DateTimeField`；`event_time` 存飞书 epoch 毫秒换算后的 aware datetime。索引在表末列出。

### 12.1 `WorkItem`

| 字段 | 类型 | 说明 |
|------|------|------|
| `feishu_project_key` | `CharField(64)` | 飞书项目 hash（如 `00000000...`） |
| `work_item_type` | `CharField(32)` | 开放集：story/issue/version/... |
| `work_item_id` | `BigIntegerField` | 飞书 int64 工作项 ID |
| `feishu_project_simple_name` | `CharField(128, blank)` | URL slug（example_platform），建/解析 URL 用 |
| `project` | `FK(projects.Project, null, SET_NULL)` | Friday 空间，历史导入可空 |
| `origin` | `CharField(choices)` | feishu_webhook / manual / bitable_import / mr_reverse |
| `title` | `CharField(512)` | mirror |
| `status_state_key` | `CharField(64)` | mirror（story 不透明 / issue=OPEN） |
| `status_sub_stage` | `CharField(64, blank)` | mirror |
| `status_display_name` | `CharField(128, blank)` | 取自 current_nodes/state_times |
| `is_archived_state` / `is_init_state` | `BooleanField` | mirror |
| `feishu_fields` | `JSONField(default=list)` | 完整 `fields[]` 对象数组（保 field_name/type/alias） |
| `prd_url` / `tech_doc_url` | `URLField(blank)` | 由别名字段提取 |
| `business_line_normalized` / `module_normalized` | `CharField(blank)` | enhanced，可空 |
| `internal_note` | `TextField(blank)` | enhanced |
| `feishu_chat_id` | `CharField(blank)` | writeback |
| `field_provenance` | `JSONField(default=dict)` | `{field: source}` 最近更新来源 |
| `last_synced_at` | `DateTimeField(null)` | 最近 sync |
| `created_at` / `updated_at` | auto | |
| `event_time` | `DateTimeField` | 飞书侧业务时间 |

**约束/索引**：`unique_together=(feishu_project_key, work_item_type, work_item_id)`（强制 INV-1）；`index(project, work_item_type)`；`index(status_state_key)`。

### 12.2 `WorkItemSyncState`（按 facet 完整度）

| 字段 | 类型 |
|------|------|
| `work_item` | `FK(WorkItem, CASCADE)` |
| `facet` | `CharField(choices: basic_fields|prd_body|tech_doc|comments|relations)` |
| `status` | `CharField(choices: complete|partial|missing|stale)` |
| `source` | `CharField(choices: feishu_webhook|manual|bitable_import|mr_reverse)` |
| `last_synced_at` | `DateTimeField(null)` |
| `error` | `TextField(blank)` |

`unique_together=(work_item, facet)`。

### 12.3 `WorkItemRelation`（派生自关联字段，PF-10）

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_work_item` | `FK(WorkItem, CASCADE, related_name=out_relations)` | |
| `target_work_item` | `FK(WorkItem, CASCADE, related_name=in_relations, null)` | 目标可能尚未 upsert |
| `target_external_id` | `BigIntegerField(null)` | 目标飞书 id（target 未落库时占位） |
| `relation_type` | `CharField(choices)` | belongs_to_project / sprint / version / related |
| `source_field_key` | `CharField(64)` | 派生来源字段（field_000008 / planning_sprint / ...） |
| `origin` | `CharField(choices: feishu_field|feishu_relation_api|friday)` | 主路径 feishu_field |

`unique_together=(source_work_item, relation_type, target_external_id, source_field_key)`。

### 12.4 `WorkItemCommentEvent` / `WorkItemStatusEvent`（append-only）

`WorkItemCommentEvent`：`work_item FK`、`feishu_comment_id CharField`、`thread_parent_id CharField(blank)`、`event_type(created|replied|edited|deleted|approval)`、`author CharField`、`body TextField`、`attachments JSONField`、`approval_semantic(none|approve|reject)`、`event_time`、`ingested_at`。索引 `(work_item, event_time)`。

`WorkItemStatusEvent`：`work_item FK`、`pre_state_key/cur_state_key`、`pre_sub_stage/cur_sub_stage`、`operator`、`event_time`。来源：`WorkitemStatusEvent` webhook + work item 响应内 `work_item_status.history[]` 回填。

### 12.5 `Document` / `DocumentVersion`

`Document`：`document_type(prd|tech_plan|release_note|sdd_spec|other)`、`source_kind(external_feishu|internal_generated)`、`external_ref CharField(blank)`（飞书 doc token）、`canonical_url URLField(blank)`、`content_storage(snapshot|reference|both)`、`current_version FK(DocumentVersion, null)`、`last_synced_at`、`writeback_allowed Bool`、`work_item FK(null)`、`feishu_tenant CharField`（如 acme，多租户区分）。

`DocumentVersion`：`document FK`、`version Int`、`supersedes FK(self,null)`、`content TextField`、`content_hash`、`created_at`。

### 12.6 `ReleaseBatch` / `ReleaseRecord` / `ReleaseArtifact`

见 §4；字段级：`ReleaseBatch(name, released_at, source, external_ref, raw_row JSON)`；`ReleaseRecord(batch FK, work_item FK null, work_item_external_id BigInt null, status, note, raw_row JSON)`；`ReleaseArtifact(release_record FK, artifact_type(mr|branch|commit|diff|release_note|doc), ref, payload JSON)`。`raw_row` 保留 Bitable 原始行，adapter 演进不丢数据。

### 12.7 `TechnicalPlan` / `PlanVersion`

`TechnicalPlan`：`work_item FK(null)`、`origin(chat|mcp|workflow|orchestration)`、`current_version FK(PlanVersion,null)`、`status(draft|under_review|approved|superseded|archived)`、`created_at/updated_at`。
`PlanVersion`：`plan FK`、`version Int`、`supersedes FK(self,null)`、`content JSONField`（MergedPlan schema §7）、`content_hash`、`created_at`。

## 13. 服务契约（唯一写入入口）

### 13.1 `WorkItemService`

```python
async def upsert(
    identity: WorkItemIdentity,      # (project_key, work_item_type, work_item_id)
    source: str,                     # feishu_webhook|manual|bitable_import|mr_reverse
    *, fetch: bool = True,           # 是否回源飞书补全
) -> WorkItem
```

步骤（保证 INV-1/INV-6）：
1. 按三元组 `select_for_update` 取/建 `WorkItem`（幂等键）。
2. `fetch=True` → `get_work_item(type 正确)`（修 PF-09）拉详情；按 facet 记 `WorkItemSyncState`（complete/partial/missing/stale）。
3. 刷新 **mirror** 字段；**不动 enhanced**；`writeback` 字段仅由专门流程改。
4. 解析 `feishu_fields` 派生：`prd_url`(别名 prd_url)、`status_display_name`(current_nodes/state_times)、关联字段 → `WorkItemRelation`（belongs_to_project/sprint/version）。
5. 写 `field_provenance` + `last_synced_at`；发 `work_item.synced` 事件。
6. 失败：部分 facet 失败不回滚整体；落 `WorkItemSyncState.error` + 重试标记。

### 13.2 `TechnicalPlanService`（= PlanProjectionService）

```python
def resolve(ref: PlanRef) -> TechnicalPlan          # 任意来源标识 → canonical（按规则创建/lazy 迁移）
def create_from(origin, payload) -> TechnicalPlan    # 新编排 eager 建 canonical
def link(old_record, canonical) -> None              # 回填 canonical_plan_id 软链
```

读优先级与生命周期规则见 §5.4（旧表只读、冲突以 canonical 为准、归档不级联）。

## 14. 编排状态机转移表（PlanSession）

| 当前状态 | 事件/条件 | 下一状态 | 副作用 |
|----------|-----------|----------|--------|
| `decomposing` | 拆分完成 | `routing` | 产出子任务/业务线划分 |
| `routing` | RepoRouterV2 返回候选仓 | `recalling` | 写候选仓 + confidence |
| `recalling` | 历史/相似/缺陷/复盘召回完成 | `clarifying` | 注入召回上下文 |
| `clarifying` | 无待澄清 或 全部已答 | `researching` | — |
| `clarifying` | 有待澄清 | `clarifying`(挂起) | 发 `Clarification`，等用户 |
| `researching` | 筛选后对需深入仓 fan-out 子 agent | `researching`(等待) | 建 `RepoResearchTask` + 派容器 |
| `researching` | 所有 `RepoResearchTask` done/failed | `merging` | barrier 通过 |
| `merging` | 架构师融合 + `PlanValidator` 通过 | `done` | 写 `PlanVersion`(MergedPlan) |
| `merging` | `PlanValidator` 失败 | `clarifying` 或 `researching` | 按报告回退重跑 |
| 任意 | 不可恢复错误 | `failed` | 落结构化 error |

**子任务级状态：**
- `RepoResearchTask`: `pending → running → done|failed|stale`。失败→单仓重试；仓库重新索引(commit 变)→关联 `PartialPlan.valid=False` 置 `stale`，融合前重跑。
- `Clarification` 回答 → 仅 `affected_partials` 内的 `RepoResearchTask` 重跑，其余复用。
- `RepoCodingTask`(v0.8): `pending → running → done|failed`；按 `depends_on` 拓扑分 wave，wave N 全 done 才触发 wave N+1；`produced_artifacts` 注入下游 prompt。

## 15. 事件 payload 规格（trace taxonomy）

统一信封：`{event, session_id, work_item_id?, ts, payload}`。progress/trace（非 CoT，INV-5）。

| event | payload 关键字段 |
|-------|------------------|
| `work_item.syncing` | `{work_item_id, facets:[...]}` |
| `knowledge.recalling` | `{query, kinds:[work_item,tech_plan,code_change], hits}` |
| `repo.routing` | `{candidates:[{repo_id, confidence}]}` |
| `repo.research.started` | `{repo_id, task_id, focus}` |
| `repo.research.completed` | `{repo_id, task_id, summary, candidate_files, api_contracts_exposed}` |
| `repo.research.failed` | `{repo_id, task_id, error}` |
| `clarification.asked` | `{clarification_id, question}` |
| `clarification.answered` | `{clarification_id, answer, affected_partials:[...]}` |
| `plan.merge.started` | `{partials:[repo_id...]}` |
| `plan.merge.completed` | `{plan_version_id}` |
| `plan.validation.failed` | `{reasons:[...]}` |
| `plan.session.failed` | `{error}` |
| `coding.wave.started` | `{wave, repo_ids:[...]}` |
| `coding.wave.completed` | `{wave, results:[{repo_id, mr_url?}]}` |

v0.10 对外 API：OpenAI adapter → `reasoning_summary` 文本流；Anthropic adapter → thinking block；皆由同一事件流映射，不暴露原始 CoT。

## 16. 真实数据字段附录（example_platform 实测，2026-06-14）

> 实地拉取确认，供 normalizer/字段映射实现直接参考。

**自然键 / 顶层**：`project_key=000000000000000000000001`、`simple_name=example_platform`、`updated_at`=epoch 毫秒、`work_item_type_key`(story/issue/...)、`pattern=Node`、`template_id`/`template_type`。

**状态**（story 1000000002）：`work_item_status.state_key="fi46o4r6m"` + `history[]`(每项 state_key/updated_at/updated_by) + `current_nodes=[{id:state_2, name:"Sprint计划"}]` + `state_times=[{state_key, name, start_time, end_time}]`。issue 的 state 直接为 `OPEN`。

**关键字段别名 / key（story）**：

| 用途 | field_key | alias | 类型 | 样例值 |
|------|-----------|-------|------|--------|
| 需求文档 | `field_000001` | `prd_url` | link | `<tenant>.feishu.cn/docx/<doc_token>` |
| 小组(业务线) | `field_000002` | `example_platform_group` | select | "示例组A" |
| 所属项目(父) | `field_000008` | — | work_item_related_multi_select | `[1000000004]` |
| 所属迭代 | `planning_sprint` | `planning_sprint` | work_item_related_multi_select | `[6290075691]` |
| 规划/上车版本 | `planning_version`/`actual_online_version` | 同名 | work_item_related_multi_select | `[]` |
| AI 审查状态 | `field_000003` | — | select | "待AI审查" |
| 当前负责人 | `current_status_operator` | 同名 | multi_user | `[...]` |
| 描述 | `description` | — | multi_text | — |

**缺陷(issue 1000000006)额外字段**：`priority`(P1)、`issue_operator`/`issue_reporter`(multi_user)、`field_000004`(实际结果)、`field_000005`(复现步骤)、`field_000006`(设备系统)、`planning_sprint`、`issue_stage`(发现阶段)、`tags`(缺陷标签)、`field_000007`(缺陷原因归类)。

**字段对象形状**：`{field_key, field_name(人类标签), field_value, field_type_key, field_alias}`，select 类 value 为 `{label, value}`，关联类为 `[id...]`。

## 17. 关键流程时序

**A. WorkItem upsert（webhook 触发）**
```
飞书 WorkitemStatusEvent → webhook 验签(webhook_token)
  → WorkItemService.upsert(identity, source=feishu_webhook)
  → select_for_update 三元组 → get_work_item(正确 type)
  → 刷新 mirror + 派生(prd_url/status_display_name/relations) + WorkItemStatusEvent(cur/pre)
  → WorkItemSyncState(facet 完整度) → 发 work_item.synced
  → knowledge 投影摄取(异步)
```

**B. 方案编排（v0.7）**
```
PlanSession(decomposing → routing → recalling → clarifying → researching → merging → done)
  routing: RepoRouterV2 → 候选仓
  researching: 筛选 → fan-out RepoResearchTask(容器, 隔离) → BarrierManager
  merging: 架构师子 agent → MergedPlan → PlanValidator → PlanVersion
  全程发 trace 事件(§15)
```

**C. 排除文件清理（v0.5）**
```
exclude 规则变更 → 对账任务
  普通排除: Qdrant(主+overlay) + ChunkRegistry + codegraph + summaries/index_nodes + denylist
  敏感清理: 上述 + message parts/ActionLog/TaskResult/CodeChangeArchive/prompt snapshot/错误日志
  → 重建摘要 → 审计埋点(AuditEvent)
```
