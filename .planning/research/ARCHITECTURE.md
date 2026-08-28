# Architecture Research

**Domain:** Cursor / Claude Code 会话知识回写（仓库挂钩 Capture → 价值评估 → `delivery_knowledge`）
**Researched:** 2026-08-28
**Confidence:** HIGH（接缝均对照当前仓库源码；价值分级与 git remote 归一化实现细节 MEDIUM，需相位内钉死）

> 结论先行：**不要把 v0.25.0 塞进 `report_project_knowledge` + `MemoryService`。**
> 现有写路径以项目为硬挂钩，无项目时 `_resolve_report_project_id` 返回 `branch_unresolved` 并 **200 静默不写**——这正是本里程碑要消灭的行为。
> 应新增 **Capture 账本 + INV-6 CaptureService + 独立 MCP 工具**；MCP 同步只落原始问答；
> 蒸馏与 high/medium/low 评估异步执行；仅中高价值走既有 `aschedule_ingestion` 入 `delivery_knowledge`。
> Interaction Ledger（`McpToolView._record`）只作调用审计，**禁止当 RAG 正文**。

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│ IDE 客户端（Cursor / Claude Code）                                        │
│  skills（friday-memory / friday 路由） + stop / session hooks              │
│  只抽：问题 / 精华答案 / 模型名 / git remote / 分支 / 会话 id              │
│  不上传隐藏思维链；无 git 改动的纯对话也提交                               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ PAT → POST /api/mcp/tools/<new>/
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MCP 工具面  McpToolView 子类（token-only，_begin/_validate/_record）      │
│  鉴权 AccessTokenAuthentication + CookieJWTAuthentication                │
│  同步：解析仓库（id 或 git URL）→ CaptureService.persist（INV-6）         │
│  立即 200 accepted；project 解析失败不得拒绝 Capture                     │
│  Ledger：InteractionRun / ToolCallRecord（审计，非检索）                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ on_commit → run_in_background
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 异步 Friday 蒸馏 + 价值评估（新 call_source）                             │
│  redact_secrets_in_text → LLM distill → high|medium|low                 │
│  low：只更新 Capture 评测字段，不向量化                                   │
│  medium/high：aschedule_ingestion(source_kind=新)                         │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 统一知识库（不新建 Qdrant collection）                                    │
│  KnowledgeEntity + delivery_knowledge                                    │
│  repository_id 必填（能解析时）；project 经 REFERENCES 边可选              │
│  召回：既有 DeliveryKnowledgeSearchService + search_delivery_knowledge    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| IDE skills / hooks | 抽精华上下文、触发 MCP；无 diff 也回写 | 改 `skills/skills/friday-memory/`、`ide_hook_assets.py` 写路径；**不**把 Capture 塞进现有仅 git-diff 的 stop 脚本逻辑而不改条件 |
| npm MCP 客户端 | 工具名白名单与 inputSchema | 改 `mcp/src/tools.ts`；与 `TOOL_SCHEMA_SNAPSHOT` 双向对齐 |
| Django MCP 视图 | PAT 鉴权、校验、同步落 Capture、记 Ledger | **新建** `McpToolView` 子类；`urls.py` 登记 `tools/<name>/` |
| CaptureService（INV-6） | Capture 唯一写入；脱敏；归因 | **新建** service + grep 守卫（照 `test_memory_inv6_guard`） |
| Capture 账本 | 原始问答 ≠ 提炼知识 | **新建** 操作态模型（建议 `initiatives` 或 `knowledge` app，见下） |
| Distill/Eval worker | LLM 提炼 + 价值分档 | **新建**；`use_call_source`；`initiated_by_user_id` 透传 |
| knowledge normalizer | 中高价值 → `IngestionEvent` | **新建** `knowledge/sources/<source_kind>.py` + 注册表一行 |
| `aschedule_ingestion` | 版本翻转 + 向量 + 边 | **复用**，禁止旁路写 Qdrant |
| `DeliveryKnowledgeSearchService` | 按仓 / 按项目召回 | **复用** `repository_ids` / `project_ids`；可选扩 `source_kind` 过滤 |
| `MemoryService` | 项目记忆（成员 fail-closed） | **不改写模型**；本里程碑不把 Capture 自动 `append` 进 `ProjectMemory` |
| `report_project_knowledge` | 项目记忆 draft/active | **保留零回归**；skills 文档与 Capture 工具分工写清 |

## Recommended Project Structure

```
server/
├── mcp_tools/
│   ├── views.py              # 新建 Capture 视图；勿把 persist 塞进 ReportProjectKnowledgeView
│   ├── serializers.py        # 新 RequestSerializer + TOOL_SCHEMA_SNAPSHOT 键
│   ├── urls.py               # path tools/<tool_name>/
│   └── services/             # 可选：git URL → Repository 解析 helper 若不想进 repositories
├── initiatives/              # 若 Capture 挂项目可选增强
│   └── services/
│       ├── capture_service.py          # NEW INV-6
│       ├── session_knowledge_eval.py   # NEW distill+value
│       └── ide_hook_assets.py          # MODIFY 写路径：无 git 也调新工具
├── knowledge/
│   ├── sources/__init__.py   # MODIFY 登记 source_kind
│   ├── sources/ide_session.py  # NEW normalizer
│   └── ingestion.py          # 复用 aschedule_ingestion；不改六步序
├── agents/call_source.py     # MODIFY 新枚举值
├── common/logging.py         # 复用 redact_secrets_in_text
mcp/src/tools.ts              # MODIFY FRIDAY_TOOLS
skills/skills/friday-memory/  # MODIFY 路由表 + http-fallback
skills/lib/installer.mjs      # 仅当新增独立 skill 名时改枚举；优先扩 friday-memory
server/tests/mcp_tools/
│   ├── test_mcp_package_alignment.py   # 自动覆盖新工具名
│   └── test_skills_snapshot_guard.py   # SKILL.md 引用 ⊆ snapshot
```

### Structure Rationale

- **`mcp_tools/`：** 对外信任边界已在 `McpToolView`；新工具必须走同一 `_begin` / `_record` / `bind_source(LogSource.MCP)`，否则 PAT 闸门与 `RequestMetric` 会漏。
- **操作态 Capture 与 `knowledge/` 图投影分离：** 与 `McpLearningCase` → `source_kind=learning_case` 同构。写模型可回放评测；读模型只含提炼正文（`IngestionEvent.content` 禁止对话原文）。
- **不进 `interactions/` 当知识：** Ledger 是用量/审计。把问答正文当检索语料会污染 RAG 并违反 PROJECT 三层分离决策。
- **skills 优先改 `friday-memory`：** 召回本就走 `search_delivery_knowledge`；新增独立 `friday-capture` skill 会迫使 installer 枚举、插件列表、hash 同步三处齐动，性价比低。容器 `SKILL_NAMES` 默认同源 `friday-code`/`friday-memory`，扩 memory 即可被编码容器看见。

## Architectural Patterns

### Pattern 1: MCP 同步收、异步炼（对照 learning case / PR review）

**What:** HTTP 200 只保证 Capture 行已提交；蒸馏与入图在 `transaction.on_commit` + `run_in_background`（或 Durable 队列）里做，失败不 5xx、不阻断 IDE。
**When to use:** IDE stop hook / skill 必须毫秒级返回；LLM 评估不可内联在 `post()`。
**Trade-offs:** at-least-once 重复评估 → Capture 上用 `content_hash` + 状态机（`pending_eval` → `evaluated`）幂等；不要在视图里直接 `ainvoke`。

**Example:**

```python
# MCP post：只 persist + schedule
capture = await CaptureService().create(...)  # redact + INV-6
await schedule_session_eval(
    capture_id=capture.id,
    initiated_by_user_id=str(request.user.id),
)
return Response({"accepted": True, "capture_id": str(capture.id), "run_id": str(run.run_id)})

# worker：call_source 新值；medium/high 才 aschedule_ingestion
async def eval_capture(capture_id, *, initiated_by_user_id=None):
    with use_call_source(CallSource.IDE_SESSION_EVAL):  # 名称相位钉死
        distilled, tier = await SessionKnowledgeEvaluator().run(capture)
    await CaptureService().record_eval(capture_id, distilled=distilled, tier=tier)
    if tier in ("high", "medium"):
        await aschedule_ingestion(
            IngestionRequest(
                source_kind="ide_session_knowledge",
                source_id=str(capture_id),
                trigger="ide_session_eval",
            ),
            initiated_by_user_id=initiated_by_user_id,
        )
```

对照：`MemoryService._schedule_materialization` → `aschedule_ingestion`；`pr_review_capture.py` 的 `use_call_source(PR_REVIEW_CAPTURE)`。**不要**对照 `ReportProjectKnowledgeView._maybe_distill`（那是请求内 best-effort，会拉长 hook）。

### Pattern 2: 仓库主挂钩、项目可选（对照 lookup 三源，但语义相反）

**What:** 接受条件是「能留下一条 Capture」，不是「能唯一命中 Project」。
**When to use:** 零散提问、未绑 `ProjectBranch`、人工分支名。
**Trade-offs:** 无 `repository_id` 时仍落库（`resolution_status=unresolved_repo`），召回只能靠后续补标或全局检索；禁止用 `branch_unresolved` 当拒绝码。

解析顺序（意见）：

1. 显式 `repository_id`（UUID）且仓存在 → 采用。
2. 否则 `git_url` / `remote_url` 经归一化匹配 `Repository.git_url`（库内已 HTTPS，见 `ssh_git_url_to_https`）。
3. `project_id` 可选：合法且用户为成员则可写 FK + 入图 `REFERENCES` 到项目节点；非成员 **不拒绝 Capture**（与 `record_hook_writeback` 的 `not_member` 静默跳过整条写入相反）。
4. `branch_name` **仅元数据**，不参与接受/拒绝。

`_resolve_report_project_id` / `_resolve_projects_by_branch` **可被 git 解析 helper 复用内部查询，但不得作为 Capture 的门闩**。

### Pattern 3: 入图复用 kind、用 `source_kind` 分流（对照 `mcp_repository_analysis`）

**What:** 不新增第九个 `EntityKind`（改枚举 = uuid5 空间与 `kentity_kind_valid` 迁移）。提炼正文用 `EntityKind.DOCUMENT` + `source_kind="ide_session_knowledge"`（名称相位锁定），`origin=EntityOrigin.MCP`，`repository_id` 写入 `KnowledgeEntity`。
**When to use:** 短精华片段，不是 `McpLearningCase` 的 problem/root_cause schema。
**Trade-offs:** `search_delivery_knowledge` 已 `include_document_kind=True`，新知识会进通用文档召回——这是期望（按仓 `repository_ids` 过滤）。若产品要「只搜会话知识」，加 `source_kind` 过滤或 `entity_kinds` 文档约定，而不是新 kind。

**不要**用 `LEARNING_CASE`：会与 Phase 100 结构化案例混排，且 `search_learning_cases` 假设 case 字段。

**不要**把原文放进 `IngestionEvent.content`：ingestion 注释写明「对话原文禁止出现在此」；原文只在 Capture 表。`payload` 可放摘要 id、tier、model，不复制全文。

### Pattern 4: 对外契约三处同改

**What:** 服务端 snapshot、npm `tools.ts`、skills 文档同一工具名同一键集。
**When to use:** 任何 MCP 工具增删字段。
**Trade-offs:** `TOOL_SCHEMA_SNAPSHOT` 的 `report_project_knowledge` **请求键仍是旧三键**（`project_id/content/source_conversation_id`），与真实 serializer（含 `branch_name`/`writeback_mode`）已漂移——**本里程碑不要顺手「修齐」旧工具**，避免无声明的客户端破坏。新工具从第一天就把 snapshot 写成完整键集。

守卫：`test_mcp_package_alignment.py`、`test_skills_snapshot_guard.py`。

## Data Flow

### Request Flow

```
IDE skill/hook
    ↓  PAT Bearer
POST /api/mcp/tools/<capture_tool>/
    ↓  McpToolView._begin（bind_source=mcp，InteractionRun）
Serializer（question, answer, answer_model, repository_id|git_url, branch, session, project_id?）
    ↓  redact_secrets_in_text（问答字段）
CaptureService.create  →  Capture 行（status=pending_eval）
    ↓  _record Ledger（input 已脱敏）
200 { accepted, capture_id, repository_resolved, project_bound, run_id }
    ↓  on_commit background
SessionKnowledgeEvaluator（call_source 新值）
    ↓  tier
low → Capture 更新，停
medium/high → aschedule_ingestion → normalizer → ingest_events
    ↓
Qdrant delivery_knowledge + KnowledgeEntity(repository_id, 可选 REFERENCES→project)
```

### State Management

```
Capture.status: pending_eval → evaluated | eval_failed
Capture.value_tier: null → high|medium|low
KnowledgeEntityVersion: 仅 evaluated 且 medium/high 后存在；content_hash 短路幂等
InteractionRun: 与 Capture 通过 run_id / metadata 关联，不互为正文
```

### Key Data Flows

1. **同步接受（MCP-01/02）：** 无 `project_id`、分支绑不到项目、git URL 暂解析失败 → 仍 `accepted=true`（或明确 `accepted=true` + `repository_resolved=false`）。唯一硬拒绝：未认证、serializer 缺问答必填。对照现状 `report_project_knowledge` 在 `resolved_pid is None` 时 `accepted=false, reason=branch_unresolved`。
2. **异步入图（EVAL-01）：** 与 `project_memory` 物化相同入口 `aschedule_ingestion`；`initiated_by_user_id` 必须从 MCP `request.user.id` 传入，worker `bind_task_context`。未知 `source_kind` 会 `KeyError`（`get_normalizer` 响亮失败）——注册表必须与 worker 同批上线。
3. **召回：** `search_delivery_knowledge` 已支持 `repository_ids` / `project_ids`。lookup 读路径（`pack_project_context`）是否自动带上新 `source_kind` 由 packer 的 kind 白名单决定——**相位需显式打开**，否则「入了库但 IDE 召不回」。Capture 回放走 **新建只读 REST 或 MCP `get_session_capture`**，不要扫 Ledger。
4. **可选项目增强：** 若 `project_id` 有效且成员，normalizer 出 `REFERENCES` 边到 `ProjectKnowledgeGraphService` 项目节点（`project_memory.py` 同款）。不调用 `MemoryService.append`，避免 MEM-04 / 成员静默丢数与 Capture「先收」冲突。

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 单团队 / 现网量级 | `run_in_background` 足够；Capture 表按 `created_at` + `repository_id` 索引 |
| 多 IDE 高频 stop hook | 客户端去抖 + 服务端 `session_id+content_hash` 幂等；评估进 Durable 队列（`DurableTaskService`）避免和索引抢线程 |
| 全员始终在线会话 | 低价值占比会很高：必须先分档再 embed，否则 Qdrant 被闲聊填满 |

### Scaling Priorities

1. **First bottleneck:** 同步路径里做 LLM（hook 超时 / IDE 卡死）。预防：persist-only。
2. **Second bottleneck:** 低价值全文向量化。预防：仅 medium/high 调 `aschedule_ingestion`；`vectorize=False` 不用于「有正文但低价值」——低价值应 **不调度 ingest**，而不是 metadata-only 登记（那仍占 PG 实体）。

## Anti-Patterns

### Anti-Pattern 1: 扩展 `report_project_knowledge` 兼作 Capture

**What people do:** 给现有工具加 `question`/`answer` 字段，无项目时改成「也写点什么」。
**Why it's wrong:** 该工具 INV-6 出口是 `ProjectMemory` / `ProjectDoc`，成员校验与 `branch_unresolved` 门闩与 STORE-01/MCP-02 相反；`TOOL_SCHEMA_SNAPSHOT` 已与真实请求键漂移，再扩会让 npm/skills 契约更烂。
**Do this instead:** 新工具名（建议 `report_session_knowledge` 或 `capture_ide_session`，相位锁定）。`friday-memory` 路由：会话问答 → 新工具；项目决策沉淀 → 仍 `report_project_knowledge`。

### Anti-Pattern 2: 用 Interaction Ledger / ToolCallRecord.input 做 RAG

**What people do:** `_record` 已存 input，直接检索 Ledger。
**Why it's wrong:** PROJECT 决策「原始 Capture / 提炼知识 / Ledger 三层分离」；Ledger 有用量语义，且未走 `chunk_knowledge_text` / 权限 `space_id`。
**Do this instead:** Capture 表回放；`delivery_knowledge` 检索提炼稿。

### Anti-Pattern 3: 无项目就 `record_hook_writeback`

**What people do:** 复用 HOOK-02 active 直写记忆。
**Why it's wrong:** 无项目无法 `append`；非成员返回 `not_member` 整单丢弃；记忆物化 `source_kind=project_memory` 是项目文档投影，不是仓级会话知识。
**Do this instead:** Capture 不依赖成员；项目边可选 fail-soft。

### Anti-Pattern 4: 新 Qdrant collection 或新 EntityKind

**What people do:** 「会话知识要隔离」就新建 collection / `EntityKind.SESSION`。
**Why it's wrong:** v0.17.0 统一知识库决策；新 kind 触发 PK 派生空间与约束迁移。隔离用 `source_kind` + `repository_id` payload。
**Do this instead:** 登记 `_NORMALIZERS["ide_session_knowledge"]`。

### Anti-Pattern 5: Stop hook 仍要求 git diff 才提交

**What people do:** 只改服务端，客户端 `content` 在无 `git diff` 时打印空串并跳过。
**Why it's wrong:** SKILL-01 / PROJECT「无 git 改动的纯对话也回写」；现 `ide_hook_assets._stop_writeback_script` 正是「无 recent/changes 则空串不 POST」。
**Do this instead:** hook/skill 从会话摘要/问题答案构造 payload；git 仅为可选上下文。Codex 弱 hook 靠 skill 主动调 MCP，不依赖 stop。

### Anti-Pattern 6: 评估 call_source 复用 `ide_hook_distill`

**What people do:** 图省事用 Phase 86 枚举。
**Why it's wrong:** `ide_hook_distill` 语义是「active 记忆精炼」；指标会与会话价值评估混维。LOGGING-SPEC §4.1 要求新 LLM 点新值。
**Do this instead:** 新增例如 `ide_session_eval`（蒸馏+打分可同一值若单轮；若两轮 LLM 则 `ide_session_distill` + `ide_session_value`）。同步改 `CallSource`、LOGGING-SPEC 表、测试基数。

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Cursor hooks | `.cursor/hooks.json` `stop` + always-on rules | `beforeSubmitPrompt` **不能注入**；采集靠 skill + stop。无 PAT → exit 0 |
| Claude Code hooks | `Stop` + 可选 `UserPromptSubmit` | 读路径已有 inject；写路径合并同一 `settings.json` `hooks` |
| Codex | 无可靠 stop | skill + 手动/CI 脚本；不要假装 always-on 采集 |
| `@friday-ai-codes/mcp` | HTTP 调 Django `/api/mcp/tools/*` | `tools.ts` 未知名直接拒绝；发版可 Deferred（对齐 v0.22 D-15），**源码必须绿** |
| `@friday-ai-codes/skills` | `npx @friday-ai-codes/skills install` | 改 `friday-memory` + `http-fallback.md`；installer 列表仅在新 skill 目录时改 |
| LLM Provider | `provider_config` + `use_call_source` | 凭证不走 env；评估失败标 `eval_failed` 保留 Capture |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| MCP view ↔ CaptureService | 直接 async 调用 | INV-6：视图不得 `Capture.objects.create` |
| CaptureService ↔ Evaluator | `run_in_background` / Durable | 透传 `initiated_by_user_id`；异常 swallow + 状态位 |
| Evaluator ↔ ingestion | `IngestionRequest` | 仅 medium/high；`source_id=capture UUID` |
| normalizer ↔ GraphStore | 只经 `IngestionEvent.edges` | 禁止 normalizer 直接 `graph_store.add_edge` |
| Capture ↔ Ledger | `run_id` 关联 | 单向；Ledger 不反哺检索 |
| Capture ↔ MemoryService | **无写入边** | 产品若以后「提升为项目记忆」另开确认流 |
| 新工具 ↔ `lookup_project_by_branch` | 无门闩依赖 | 召回仍用 lookup/packer；写入不要求 matched |
| git URL ↔ `Repository.git_url` | 归一化匹配 | 复用 `ssh_git_url_to_https`；多行命中记 unresolved 仍收 Capture |
| 观测 | structlog `category=caller`（MCP persist）/`sampling`（eval 步） | `component=mcp_tools` / `knowledge`；`redact_secrets_in_text` 问答与异常；`error=str(exc)` 必须脱敏 |
| 权限 | PAT = 令牌所有者 RBAC | 仓级 ACL 仍是「登录即可读存在的仓」（CONCERNS）；写入 Capture 不扩大读权限；入图后召回走既有 search fail-closed |

### New vs Modify（质量门）

| 项 | 判定 | 文件 |
|----|------|------|
| Capture 模型 + CaptureService | **NEW** | `initiatives`（贴近 IDE/项目）或 `knowledge`（贴近入图）；推荐 **initiatives**：与 hook 资产同域，knowledge 只消费 `source_id` |
| MCP 工具 + serializer + url | **NEW** 工具，**MODIFY** 登记表 | `views.py` / `serializers.py` / `urls.py` |
| git remote 解析 | **NEW** helper | `repositories/` 服务函数，MCP 与 hook 共用 |
| Distill + value eval | **NEW** | 勿塞进 `MemoryDistiller.distill_hook_writeback` |
| `CallSource` + LOGGING-SPEC §4.1 | **MODIFY** | 枚举 + 文档表必须同批 |
| `knowledge/sources` 注册表 + normalizer | **MODIFY** + **NEW** 模块 | 未知 kind 会响亮炸 worker |
| `aschedule_ingestion` / 六步序 | **复用，不改算法** | 除非 `IngestionEvent` 要新字段（不需要） |
| `DeliveryKnowledgeSearchService` | **小 MODIFY 或配置** | packer/search 白名单纳入新 `source_kind` |
| `MemoryService` / `record_hook_writeback` | **不改契约** | 零回归 |
| `ReportProjectKnowledgeView` | **不改门闩** | 文档声明分工即可 |
| `ide_hook_assets` 写路径 | **MODIFY** | 无 git 也 POST 新工具；可保留 MEMORY 路径并行 |
| `mcp/src/tools.ts` | **MODIFY** | 新条目 |
| `friday-memory` skill + fallback | **MODIFY** | 守卫：引用名必须在 snapshot 内 |
| `task/assets/skills` hash | **MODIFY 若改了 friday-memory** | `sync_skills.py` 一致性测 |
| 前端工作台 | **本里程碑非必须** | Capture 回放可后置只读 API；小版本不做大前端（对齐 v0.23 约束风格） |
| runner / task / workflow | **不改** | 非本流 |

## Suggested Build Order（依赖）

相位应线性，后者依赖前者的契约稳定：

1. **STORE-01 账本 + INV-6**  
   Capture 模型（问答、模型名、`repository_id` 可空、`git_url_raw`、`branch`、`project_id` 可空、`session_id`、hash、status、tier、distilled、`initiated_by_user_id`）+ `CaptureService.create`（脱敏）+ 旁路写表 grep 守卫。  
   **无此步禁止接 MCP。**

2. **归因解析（无 LLM）**  
   `repository_id` XOR 归一化 `git_url` → `Repository`；多命中/零命中策略单测。分支不参与接受。

3. **MCP-01/02 同步工具面**  
   Serializer、`McpToolView`、`urls`、`TOOL_SCHEMA_SNAPSHOT`（完整键）、对齐测试。行为：无项目仍 200 accepted；Ledger `_record`。  
   **此步结束 IDE 可打桩联调，评估可先 no-op 调度。**

4. **EVAL-01 worker + call_source**  
   新枚举、LOGGING-SPEC、`use_call_source`、token/TTFT 上报、`initiated_by_user_id`。低价值不 ingest。幂等：已 `evaluated` 且 hash 不变则跳过。

5. **入图**  
   `_NORMALIZERS` + normalizer（`DOCUMENT` + 仓 `repository_id` + 可选项目 `REFERENCES`）+ 仅 medium/high `aschedule_ingestion`。ingestion 单测用既有 `test_ingestion` 形态。

6. **召回闭环**  
   确认 `search_delivery_knowledge` / `pack_project_context` 能按仓或按项目命中新 `source_kind`；补 RetrievalTrace。Capture 回放只读（评测模式）可本步或紧随。

7. **SKILL-01 客户端**  
   `tools.ts`、`friday-memory`、`http-fallback.md`、`ide_hook_assets`（无 git 也采集）、skills 守卫与 hash。npm publish Deferred。  
   **必须在步骤 3 契约冻结之后**，否则技能文档与 snapshot 互搏。

8. **观测与回归**  
   MCP persist = `caller`；eval 内部步 = `sampling`；禁止 INFO 刷每条 chunk。旧 `report_project_knowledge` 单测全绿。

**不可并行乱序：** 步骤 7 不能先于 3；步骤 5 不能先于 1（`source_id` 无行）；步骤 4 的 call_source 必须先于首次 LLM，否则落入 `unknown`。

## Sources

- 本仓：`server/mcp_tools/views.py`（`McpToolView`、`lookup_project_by_branch`、`_resolve_report_project_id`、`ReportProjectKnowledgeView`）
- 本仓：`server/mcp_tools/serializers.py`（`TOOL_SCHEMA_SNAPSHOT`、`ReportProjectKnowledgeRequestSerializer`）
- 本仓：`server/knowledge/ingestion.py`（`aschedule_ingestion` / `IngestionEvent.content` 纪律）
- 本仓：`server/knowledge/sources/__init__.py`、`project_memory.py`、`learning_case.py`
- 本仓：`server/initiatives/services/memory_service.py`（INV-6、`record_hook_writeback`、物化钩子）
- 本仓：`server/initiatives/services/ide_hook_assets.py`（stop 脚本空内容跳过）
- 本仓：`server/agents/call_source.py`、`.planning/observability/LOGGING-SPEC.md` §4.1
- 本仓：`mcp/src/tools.ts`、`server/tests/mcp_tools/test_mcp_package_alignment.py`、`test_skills_snapshot_guard.py`
- 本仓：`.planning/PROJECT.md` v0.25.0 Active MCP-01/02、SKILL-01、STORE-01、EVAL-01 与 Key Decisions（仓库主挂钩、三层分离、Friday 侧价值评估）
- 本仓：`.planning/codebase/ARCHITECTURE.md`（系统四件套；本能力全部落在 Django MCP + knowledge，不碰 runner/task）

---
*Architecture research for: v0.25.0 IDE session knowledge writeback*
*Researched: 2026-08-28*
