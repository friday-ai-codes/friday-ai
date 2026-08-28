# Phase 144: 仓库召回与 Capture 回放 - Research

**Researched:** 2026-08-28
**Domain:** Django/adrf MCP + delivery_knowledge 向量召回 + SessionCapture 只读回放 + RetrievalTrace
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### 仓库优先的召回契约
- 会话知识检索必须以 `repository_id` 为必选主作用域；`project_id` 仅为可选的交集过滤条件，不能替代仓库或扩大仓库授权范围。
- 检索只返回 Phase 143 已入图、`EntityKind.DOCUMENT` 且 `source_kind="session_capture"` 的中高价值精华；原始 Capture 问答与 low 样本不进入向量召回。
- 在 `DeliveryKnowledgeSearchService`/底层 recall 增加显式 `source_kinds` 闭集过滤能力，调用点必须传 `["session_capture"]`；不能依靠 document kind 或标题约定间接识别。
- `pack_project_context` 与交付知识检索的允许源白名单显式加入 `session_capture`，并继续沿用现有 `resolve_allowed_repository_ids`/`resolve_allowed_project_ids` 权限收口；项目过滤只收窄，不放宽。

#### Capture id 原文回放
- 提供按 Capture UUID 的只读回放入口，返回 `capture_id`、结构化 `question`/`answer`、模型/客户端/会话/分支元数据、仓库/项目挂钩、tier/status/reason 与时间戳；不返回隐藏 CoT、凭证或内部重试错误细节。
- 回放正文唯一来源是 `initiatives.SessionCapture`；禁止查询、扫描或拼接 Interaction Ledger / ToolCallRecord / RetrievalTrace payload 作为正文。
- 权限 fail-closed：创建者本人可读；若 Capture 挂仓库/项目，还必须满足当前仓库可见性与项目访问约束，未授权与不存在统一返回不泄漏存在性的 404。
- 回放入口保持纯只读、无状态推进、无重新评估或入图副作用；大前端页面不是验收前提，薄 MCP/REST read endpoint 与测试足够完成本 Phase。

#### 默认分支项目匹配防错
- `main`、`master`、`develop` 以及仓库配置的 `default_branch` 属于默认分支；在没有显式 `ProjectBranch` 或可解析 work item 的情况下，不得仅凭唯一 `RepoAssociation` 返回 `matched=true`。
- `LookupProjectByBranchView` 第三源在默认分支上跳过项目注入，可返回候选及明确 `binding_source`/reason 供人工确认；不得把候选上下文打包进响应。
- 显式 `ProjectBranch` 绑定与 `feat/...-m{id}-...` 工作项命名继续优先并可在默认分支上命中；修复只禁止“默认分支 + 仓关联”作为唯一证据，不破坏前两源。
- Capture 写路径继续以仓库挂钩为主，不能因 lookup 不唯一而拒收、清空仓库 FK 或退化为 `branch_unresolved`；读写解析边界需由回归测试同时锁定。

#### 召回观测与双链一致性
- MCP 会话知识检索使用 `McpToolView._record(..., traces=...)` 写 RetrievalTrace；Chat 工具复用 `_record_chat_retrieval`，两链都记录 source、repository/project 过滤维度、result_count、scores/top_score、duration_ms 与 `source_kind`。
- RetrievalTrace payload 只含标量、计数、分数和标识，不含 query、精华正文、原始问答或 Ledger body；统一由现有 ledger 脱敏入口再防护。
- Trace 写入始终 best-effort；记录失败不得改变检索结果、HTTP 状态或对话 ToolResult，空结果也应保留计数为零的可观测事件。
- MCP 与 Chat 必须委托同一 `DeliveryKnowledgeSearchService` 和同一 `session_capture` 白名单/权限策略；测试需证明两链过滤和失败降级一致，禁止各写一套查询。

### Claude's Discretion
- 回放入口最终命名、采用 MCP read tool 还是薄 REST detail view、serializer 内部拆分由实现者决定；必须保证按 Capture id、只读、404 防枚举与不读 Ledger。
- `source_kinds` 过滤落在 service 还是 vector recall 层由实现者按现有 Qdrant payload 决定，但必须是显式参数且对其他调用点默认零回归。

### Deferred Ideas (OUT OF SCOPE)
- Vue Capture 回放工作台、价值档位人工纠偏和批量评测界面留后续版本。
- SessionStart 自动注入近期高价值摘要与跨 Capture 聚合排序留后续版本。
- Cursor / Claude Code 自动采集与 hooks 安装延后到 Phase 145。
- 仓库 ACL 的平台级历史欠债不在本阶段重构；本阶段不得比现有代码/知识检索权限更松。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RECALL-01 | 用户可按 `repository_id` 检索已入图的会话知识；有项目时也可按 `project_id` 检索 | 专用会话检索入口 **必填** `repository_id`，可选 `project_id` 做 **AND 交集**；`search_similar(..., repository_ids=[rid], project_ids=[pid] or None, entity_kinds=["document"], include_document_kind=True, source_kinds=["session_capture"])`。不得用 `project_id` 单独检索会话知识。 |
| RECALL-02 | `pack_project_context` / 交付知识检索白名单显式包含 `session_capture` | Qdrant payload 已索引 `source_kind`（`knowledge/collection.py`）；Phase 143 normalizer 已写 `source_kind="session_capture"`。通用 RAG **不得**把 DOCUMENT 召回收成仅 `session_capture`。Packer/通用 `search_delivery_knowledge` 保持 `source_kinds=None`（全量 DOCUMENT 已含 session_capture）**或**显式 inclusion 列表含 `session_capture`+既有 document 源。专用会话检索才传闭集 `["session_capture"]`。 |
| RECALL-03 | 授权用户按 Capture id 只读回放原始结构化问答；不扫描 Ledger payload 当正文 | 只 `SessionCapture.objects` 读行；正文=`question`/`answer`；禁止 `ToolCallRecord`/`RetrievalTrace`/`arecord_tool_call` 回读。未授权/不存在统一中性 404。 |
| RECALL-04 | 默认分支 `main`/`master`/`develop` 不得单独把 Capture 写到错误项目；lookup 第三源在默认分支上不得 `matched=true` | 修 `LookupProjectByBranchView` 第三源；`Repository.default_branch` 并入默认分支集合。`ReportSessionKnowledgeView` **已不**走第三源（只透传显式 `project_id`）；补回归：`branch_name=main` + 唯一 `RepoAssociation` 且未传 `project_id` → Capture 无 project FK、`accepted=true`。 |
| OBS-03 | MCP 与对话召回链 best-effort 写 `RetrievalTrace`；观测失败不得改变检索业务结果 | 会话检索 MCP 走 `_record(traces=...)`；Chat 走 `_record_chat_retrieval`。payload 无 query/正文。空结果仍写 `result_count=0`。`arecord_retrieval_trace` 已 try/except + `redact_for_ledger`。 |
</phase_requirements>

## Summary

Phase 144 是 **读侧**：把 Phase 143 已写入 `delivery_knowledge` 的 `DOCUMENT` + `source_kind=session_capture` 精华按 **仓库主作用域** 找回来，并按 Capture UUID 从 **独立账本** 回放脱敏后的原始问答。向量层已经具备 `source_kind` KEYWORD 索引与 `project_id="" ∧ repository_id∈allowed` 逃生支，但 `search_similar` / `_build_knowledge_must_filter` **今天没有 `source_kinds` 参数**；仅靠 `entity_kinds=["document"]` 会混入 project_doc / artifact / memory。会话检索必须新增显式闭集过滤。

`lookup_project_by_branch` 第三源（唯一 `RepoAssociation` → `matched=true` + `pack_project_context`）在 `main`/`feat` 上行为相同。IDE 若把该 `project_id` 传给 `report_session_knowledge`，会把默认分支上的 Capture 误挂到仓的唯一关联项目。修复点精确在第三源：默认分支上禁止 `matched=true` 与 context 打包，保留候选。写路径（`CaptureService.persist`）本身不调用第三源，但仍要用回归锁住「未传 project_id 不因仓关联绑项目」。

**Primary recommendation:** 在 `recall_similar_chunks` 增加可选 `source_kinds: list[str] | None = None`（`None`=不加条件，空列表短路 `[]`）；会话 MCP/Chat **薄封装**同一 `DeliveryKnowledgeSearchService.search_similar` 且 **强制** `repository_id` + `source_kinds=["session_capture"]` + `include_document_kind=True`。回放用只读 MCP tool（推荐名 `get_session_capture`）读 `SessionCapture`，三面 schema 对齐。Lookup 用共享 `is_default_branch(branch, repo)` 跳过第三源注入。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 会话知识向量检索（RECALL-01） | API / Backend | — | Qdrant filter + access_scope 只能在服务端强制；浏览器不得直连 Qdrant。 |
| `source_kinds` 闭集过滤 | API / Backend (`knowledge.vector_recall`) | `DeliveryKnowledgeSearchService` 透传 | payload `source_kind` 已索引；过滤必须进 must filter，不能在 hydrate 后丢弃（会泄漏未授权点的存在性到计分侧）。 |
| packer / 通用交付检索白名单（RECALL-02） | API / Backend | — | `pack_project_context._layer_rag` 与 MCP/Chat `search_delivery_knowledge` 已 `include_document_kind=True`；本阶段只保证不排除 `session_capture`。 |
| Capture 原文回放（RECALL-03） | API / Backend | MCP npm 静态 schema | 账本在 Postgres；权限与 404 防枚举必须服务端。 |
| 默认分支第三源守卫（RECALL-04） | API / Backend (`LookupProjectByBranchView`) | — | 匹配语义在 MCP 工具内；写路径只消费显式 `project_id`。 |
| RetrievalTrace 双链（OBS-03） | API / Backend (`interactions.ledger`) | Chat tools | MCP 有 `InteractionRun`；Chat 用 `conversation_id` + `arecord_retrieval_trace(run=None)`。 |
| 权限收口 | API / Backend (`knowledge.access_scope`) | — | 不得新建更松的仓库 ACL；caller ids 只 intersect。 |
| npm MCP 工具发现 | CDN / Static (`mcp/src/tools.ts`) | 服务端 snapshot | 未知工具名会被 npm 白名单拒绝；新工具必须三面齐。 |

## Project Constraints (from .cursor/rules/)

来自 `.cursor/rules/observability-logging.mdc` 与 `.planning/observability/LOGGING-SPEC.md`（与 CLAUDE.md 可观测段一致）：

- `structlog.get_logger(__name__)`，事件名 snake_case，kv 字段，禁止把变量拼进 message。
- 生命周期 started/completed/failed + `duration_ms`；`category` ∈ {`caller`,`sampling`}；`component` 必填。
- 凭证/token 禁止入日志与 Ledger；`redact_secrets_in_text` / `redact_for_ledger`。
- 触发用户可归因；MCP 走 `McpToolView` 中间件；无新后台任务则不必新 `initiated_by_user_id` 投递。
- 召回：条数 / 耗时 / score → `RetrievalTrace`；**MCP + Chat 两链**；观测 best-effort，`except: pass`。
- 本阶段 **无新 LLM 调用**，不新增 `CallSource`。
- 高频循环禁止 INFO 刷屏（沿用既有 `knowledge_vector_recall_completed`，会话工具级用 `caller` 一次即可）。
- 不引入新 Python/npm 运行时依赖（ROADMAP locked）。

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django + adrf | django≥5.1（仓库 pin） | 异步 MCP `APIView` | 既有 `McpToolView` 生命周期。 [VERIFIED: server/pyproject.toml] |
| djangorestframework | ≥3.15 | serializer / 400 | 与 `TOOL_SCHEMA_SNAPSHOT` 对齐。 [VERIFIED: server/pyproject.toml] |
| qdrant-client | ≥1.9.0 | `models.FieldCondition` / `MatchAny` | `source_kind` 已是 KEYWORD 索引。 [VERIFIED: server/knowledge/collection.py] |
| pytest + pytest-django + pytest-asyncio | pytest 9.0.2 | 契约测试 | `server/pyproject.toml` `[tool.pytest.ini_options]`。 [VERIFIED: uv run pytest --version] |
| structlog | ≥25.5.0 | 结构化日志 | 观测规范强制。 [VERIFIED: server/pyproject.toml] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asgiref `sync_to_async` | Django 捆绑 | ORM 桥 | lookup 第三源、Capture get 已是该模式。 |
| vitest | web/mcp catalog | npm `FRIDAY_TOOLS` 长度 | 新增 MCP 工具时改 `mcp/tests/server.test.ts`。 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 专用 `search_session_knowledge` | 给 `search_delivery_knowledge` 加可选 `source_kinds` + 必填 repo | 通用工具变成会话专用会破坏「query-only」既有契约；**推荐专用工具 + service 层可选参数**。 |
| MCP 回放 | 仅 REST `/api/.../session-captures/{id}/` | 允许（Discretion）；IDE 从 RAG `source_id` 跳转更差。推荐 MCP read tool。 |
| hydrate 后按 `entity.source_kind` 过滤 | Qdrant must filter | 后过滤浪费 top_k、且 demand 分路会混入其它 DOCUMENT。 |

**Installation:** 无新包。不要 `pip`/`npm` 新增运行时依赖。

**Version verification:** 本阶段不安装外部包；pytest **9.0.2**、Python **3.14.2** 已在本机探测。

## Package Legitimacy Audit

> 本阶段 **不安装** 外部包。slopcheck 不适用。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | 无候选 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
IDE / Chat LLM
    │  repository_id (required) + query + optional project_id
    ▼
MCP SearchSessionKnowledgeView  ──┐
Chat search_session_knowledge  ───┼──► DeliveryKnowledgeSearchService.search_similar
                                  │         │
                                  │         ├─ resolve_allowed_project_ids(user, [project] or None)
                                  │         ├─ resolve_allowed_repository_ids(user, [repo], project_ids=allowed)
                                  │         │     空 allowed_projects → []（既有 fail-closed，本阶段不放宽）
                                  │         └─ recall_similar_chunks(..., source_kinds=["session_capture"],
                                  │                entity_kinds=["document"], include_document_kind=True)
                                  │                   │
                                  │                   ▼
                                  │              Qdrant delivery_knowledge
                                  │              must: is_latest, project 闸/逃生支, repo MatchAny,
                                  │                    entity_kind=document, source_kind=session_capture
                                  ▼
                         serialize_search_results (shared DTO)
                                  │
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
     MCP _record(traces=scalars)           Chat _record_chat_retrieval
              │                                       │
              └──────── arecord_retrieval_trace ──────┘
                        redact_for_ledger; 失败吞掉

Replay:
  capture_id → SessionCapture.aget() → _can_read_capture(user)
       否/无行 → 404 同文案
       是 → {question, answer, metadata...}  禁止 Ledger join

Lookup (RECALL-04):
  work_item ∪ ProjectBranch  → 可 matched + pack
  else RepoAssociation:
       if is_default_branch(name, repo): candidates only, matched=false, context=""
       else: 唯一命中 matched=true（既有 feat/login-page 行为）
```

### Recommended Project Structure

```
server/knowledge/vector_recall.py          # source_kinds → FieldCondition
server/knowledge/retrieval.py              # search_similar 透传 source_kinds
server/services/project_context_packer.py  # _layer_rag 传 project_ids；不独占 session_capture
server/services/branch_parsing.py          # is_default_branch() 共享 helper
server/mcp_tools/views.py                  # SearchSessionKnowledgeView + GetSessionCaptureView + lookup 第三源
server/mcp_tools/serializers.py            # 请求/响应 + TOOL_SCHEMA_SNAPSHOT
server/mcp_tools/urls.py                   # tools/search_session_knowledge/ + tools/get_session_capture/
server/agents/tools/knowledge_read_tools.py  # Chat 同契约薄封装
server/initiatives/services/capture_access.py  # 可选：只读授权纯函数（无 objects.create）
mcp/src/tools.ts                           # 第 53/54 个工具
server/tests/knowledge/test_vector_recall.py
server/tests/knowledge/test_retrieval.py
server/tests/knowledge/test_session_capture_retrieval.py
server/tests/mcp_tools/test_search_session_knowledge.py
server/tests/mcp_tools/test_get_session_capture.py
server/tests/mcp_tools/test_get_session_capture_schema_pending.py
server/tests/mcp_tools/test_lookup_project_by_branch.py  # 增补
server/tests/agents/tools/test_search_session_knowledge.py
server/tests/initiatives/test_capture_service.py         # 写路径零回归
```

### Pattern 1: 可选 `source_kinds` 零回归透传

**What:** `search_similar(..., source_kinds=None)` 不向 Qdrant 加 `source_kind` 条件。会话调用点传 `["session_capture"]`。
**When to use:** 所有既有 `search_similar` 调用（knowledge REST、`search_delivery_knowledge`、`search_project_context`、packer）保持默认 `None`。
**Example:**

```python
# Source: server/knowledge/vector_recall.py _build_knowledge_must_filter
# 在 entity_kinds 条件之后追加（Qdrant KEYWORD MatchAny）
if source_kinds:
    must.append(
        models.FieldCondition(
            key="source_kind",
            match=models.MatchAny(any=list(source_kinds)),
        )
    )
```

空列表：在 `recall_similar_chunks` 入口与「未知 entity_kinds 两分路皆空」一样 **短路 return []**，不发 embedding。 [VERIFIED: server/knowledge/vector_recall.py entity_kinds 短路]

### Pattern 2: 仓库 AND 可选项目

**What:** Serializer：`repository_id` required UUID；`project_id` optional UUID。Service 调用：

- 无项目：`repository_ids=[str(rid)]`，`project_ids=None`（allowed projects = 用户可见全集，再 intersect 仓）。
- 有项目：`project_ids=[str(pid)]` **且** `repository_ids=[str(rid)]`。`resolve_allowed_repository_ids(..., project_ids=allowed_projects)` 已是 intersect；项目不在可见集 → 仓列表空 → 召回 `[]`（与现网 knowledge 一致，不要 403）。

**不要** 实现 `project_id OR repository_id`。 [VERIFIED: CONTEXT specifics；access_scope caller intersect]

### Pattern 3: DOCUMENT + include_document_kind

会话实体是 `EntityKind.DOCUMENT`。demand 分路仅在 `include_document_kind=True` 时纳入 DOCUMENT。会话调用点 **必须同时** 传 `entity_kinds=["document"]`（或 `EntityKind.DOCUMENT` 字面值）与 `include_document_kind=True`，否则 `demand_kinds` 交集为空直接 `[]`。 [VERIFIED: server/knowledge/vector_recall.py L250–264, L29–32]

### Pattern 4: 回放只读与 404 防枚举

**What:** `GetSessionCaptureView(McpToolView)` POST `capture_id`；`select_related` 后授权；失败与缺失同一 `error_response(..., status_code=404)` 文案（例如「资源不存在」），禁止 403 分流。
**Read set（闭集）:** `id, question, answer, response_model, provider, session_id, branch_name, repository_id, project_id, link_reason, value_tier, status, created_at, updated_at, evaluated_at`。`client` **不在** `SessionCapture` 上（Phase 142 故意不入库），因此回放响应固定省略 `client`；禁止返回猜测值或恒 `null`，更禁止为补 client 去读 `ToolCallRecord.input`。
**禁止字段:** `last_error`、`distilled_essence`（回放合同是原始问答）、token 计数字段若需展示保持字面 `unknown` 字符串、任何 Ledger join。

### Pattern 5: Lookup 第三源默认分支

在 `if not merged and repository_id:` 块内：先查 association 列表；`is_default_branch(branch_name, repository)` 为真时写入 `candidates` + `binding_source`/`skip_reason`（推荐 `repo_association_skipped_default_branch`），**不** `matched=True`、**不**调用 `pack_project_context`。非默认分支保持现网唯一命中 `matched=True`。

```python
# Source: 推荐放入 server/services/branch_parsing.py
_WELL_KNOWN_DEFAULTS = frozenset({"main", "master", "develop"})

def is_default_branch(branch_name: str, default_branch: str | None = None) -> bool:
    name = (branch_name or "").strip()
    if not name:
        return False
    extras = {default_branch.strip()} if default_branch and default_branch.strip() else set()
    return name in _WELL_KNOWN_DEFAULTS | extras
```

分支名按 git 大小写敏感做 **精确匹配**，不要 `.lower()`。无 `repository_id` 时仍用三件套字面量判断（第三源本就不跑）。

### Anti-Patterns to Avoid

- **用标题/kind=document 识别会话知识：** 会召回项目 5 文件与工件。必须 `source_kinds`。
- **packer RAG 只传 `source_kinds=["session_capture"]`：** 会丢掉 project_doc/memory/artifact，破坏 CTX-01。RECALL-02 是 **inclusion** 不是 exclusive filter。
- **放宽 `if not allowed_projects: return []`：** 违反「不比现有 ACL 更松」。无项目可见用户会话检索继续空结果。
- **回放读 Ledger 补 client/CoT：** 违反 STORE/RECALL 三层分离。
- **第三源跳过时仍 pack context：** 泄漏项目上下文。
- **因 lookup 不匹配拒绝 Capture：** MCP-02 已锁 `accepted=true`。
- **Chat 与 MCP 各写 Qdrant filter：** OBS-03 / CONTEXT 禁止。
- **会话 RetrievalTrace 写入 title/query/text：** 现网 `SearchDeliveryKnowledgeView` traces **含 title**；会话工具 **不得**复制该模式。 [VERIFIED: server/mcp_tools/views.py L3366–3377]
- **INV-6 旁路 `SessionCapture.objects.create`：** 回放只 get。
- **新 CallSource / 新 EntityKind / 新 collection。**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 向量权限闸 | 手写 Qdrant filter 副本 | `_build_knowledge_must_filter` | 逃生支/空串孤儿点已踩过坑。 |
| 项目/仓可见性 | 新 RepositoryPermission | `resolve_allowed_*` | Capture 写入已用同一套。 |
| DTO 字段 | Chat/MCP 各序列化 | `knowledge.exposure.serialize_search_results` | Phase 16 防漂移。 |
| Trace 脱敏 | 会话工具内再写 redact | `arecord_retrieval_trace` → `redact_for_ledger` | 已覆盖 MCP+Chat。 |
| 分支 work_item 解析 | 新正则 | `parse_work_item_id_from_branch` | lookup 前两源零回归。 |
| 工具发现 | 只改 Django urls | serializer snapshot + `mcp/src/tools.ts` + vitest 长度 | Phase 142 三面合同。 |

**Key insight:** 入图侧已把精华变成普通 DOCUMENT 点；本阶段的正确性几乎全在 **filter 闭集 + 仓库必填 + 默认分支第三源 + 账本回放不碰 Ledger**。

## Common Pitfalls

### Pitfall 1: `include_document_kind` 漏传

**What goes wrong:** `source_kinds=["session_capture"]` 但 DOCUMENT 不在 demand 白名单 → 恒空。
**Why:** entity_kinds 与分路白名单求交。
**How to avoid:** 会话封装函数固定三件套：`entity_kinds=["document"]`, `include_document_kind=True`, `source_kinds=["session_capture"]`。
**Warning signs:** 集成测试 mock Qdrant 都有点但 HTTP total=0。

### Pitfall 2: 无锚 Capture 的 project_id 空串

**What goes wrong:** 仅仓挂钩的中高 Capture，向量 `project_id=""`。纯 `project_id ∈ allowed` 闸会漏掉，除非走逃生支。
**Why:** normalizer 允许无项目无边事件。 [VERIFIED: server/knowledge/sources/session_capture.py L165–181]
**How to avoid:** 继续走 `_build_knowledge_must_filter` 全函数，会话检索 **必须**带非空 `allowed_repository_ids`（来自必填 repository_id ∩ access_scope）。
**Warning signs:** 有仓无项目的精华搜不到。

### Pitfall 3: 通用检索加默认 source_kinds

**What goes wrong:** `search_similar` 默认过滤 session_capture 或反过来默认只搜 session_capture。
**How to avoid:** 默认 `None`；知识 REST `knowledge/api/views.py` 不加该参数。
**Warning signs:** `test_vector_recall.py` / delivery knowledge 工具测试红。

### Pitfall 4: Lookup 测试只改 feat 分支

**What goes wrong:** `test_repo_association_fallback_single_match` 用 `feat/login-page` 必须 **继续** `matched=true`。
**How to avoid:** 新增 `branch_name=main`（及 `master`/`develop`/自定义 `default_branch=trunk`）用例，不要改现有 feat 断言。
**Warning signs:** 人工命名分支召回回归失败。

### Pitfall 5: 观测反噬

**What goes wrong:** `_record` 抛错导致 500；Chat `arecord` 未包 try。
**How to avoid:** Chat 已有 `_record_chat_retrieval` try/except。MCP `_record` 若内部 trace 失败需确认 `arecord_retrieval_trace` 不抛——`record_retrieval_trace` 已吞异常。会话 traces 在 `_record` 之前组装，组装期不要 IO。空结果也要 traces（一条汇总 chunk 即可，避免按 result 行展开正文）。
**Warning signs:** monkeypatch `RetrievalTrace.objects.create` 后 HTTP 非 200。

### Pitfall 6: npm 分波计数不独立

**What goes wrong:** Wave 0 提前写 54 导致 npm 无法绿，或 Plan 04 search-only 阶段仍期待 52/54。
**How to avoid:** Wave 0=52；Plan 04 加 search=53；Plan 05 加 get=54。每波同步 `FRIDAY_TOOLS`、完整 `TOOL_SCHEMA_SNAPSHOT` 与 package alignment；get-only RED 放独立文件。
**Warning signs:** 对齐测试红。

### Pitfall 7: 回放返回 `last_error`

**What goes wrong:** 内部重试细节泄漏。
**How to avoid:** serializer 显式 fields allowlist。

## Code Examples

### 会话检索 service 调用（两链共用 helper）

```python
# 推荐：initiatives 或 knowledge 内一小函数，MCP view 与 Chat tool 只调它
results = await DeliveryKnowledgeSearchService().search_similar(
    query,
    user=user,
    top_k=top_k,
    repository_ids=[str(repository_id)],
    project_ids=[str(project_id)] if project_id else None,
    entity_kinds=["document"],
    include_document_kind=True,
    source_kinds=["session_capture"],
)
```

### 会话 RetrievalTrace payload（闭集）

```python
{
    "source": "mcp_search_session_knowledge",  # chat: chat_search_session_knowledge
    "repository_id": str(repository_id),
    "project_id": str(project_id) if project_id else "",
    "source_kind": "session_capture",
    "result_count": len(serialized),
    "scores": [item.get("score") or 0 for item in serialized],
    "top_score": max(scores) if scores else 0,
    "duration_ms": duration_ms,
}
# 禁止: query, title, text, question, answer, essence, ledger
```

空结果仍 append **一条**上述 payload（`result_count=0`, `scores=[]`）。

### Capture 读授权（推荐语义）

CONTEXT「创建者本人可读；若挂仓库/项目还必须满足可见性」与 REQUIREMENTS「授权用户」同时成立时，实现：

1. 行不存在 → 404。
2. `user.is_superuser` → 可读（与 knowledge search superuser 全集一致，不放宽匿名）。
3. `initiated_by_user_id == str(user.id)`：
   - 若 `repository_id` 非空：`str(repo) in resolve_allowed_repository_ids(user, [rid])`，否则 404。
   - 若 `project_id` 非空：`str(pid) in resolve_allowed_project_ids(user, [pid])` 且保持现网 Capture 写入用的成员约束（`ProjectMember` / public_org 与 `access_scope` 对齐），否则 404。
   - 双 FK 皆空（unanchored）：仅创建者。
4. 非创建者：**不要**仅凭仓成员回放原文（原文比 RAG 精华更敏感）。仓成员继续走向量精华，不走 Q/A 回放。若产品要队友回放，属扩大授权，本阶段 **不放宽**（与 deferred ACL 一致）。

[ASSUMED] 非创建者拒绝回放——CONTEXT 写「创建者本人可读」，REQUIREMENTS 写「授权用户」；上面取 **创建者 ∩ 挂钩可见性**，不把仓内任意成员当授权回放主体。

### Lookup 第三源伪代码

```python
if not merged and repository_id:
    association_projects = await self._lookup_by_repo_association(repository_id)
    repo = await Repository.objects.filter(id=repository_id).afirst()
    default = repo.default_branch if repo else None
    if is_default_branch(branch_name, default):
        output_data["candidates"] = [_project_summary(p) for p in association_projects]
        output_data["matched"] = False
        output_data["binding_source"] = "repo_association_skipped_default_branch"
        # context 保持 ""
    else:
        for p in association_projects:
            merged.setdefault(p.id, p)
```

`binding_source` 目前只在 `matched` 时写入 traces；跳过时应出现在 **HTTP body**（CONTEXT：供人工确认），snapshot 需加可选响应键（既有 lookup 响应键扩展必须三面同步）。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 无 `source_kinds` | Qdrant payload 已有索引字段但未过滤 | Phase 15 collection schema | 本阶段接上 MatchAny |
| DOCUMENT 靠 `include_document_kind` 混召 | 会话闭集 `session_capture` | Phase 143 入图 | 专用入口避免污染 |
| 第三源唯一 association → matched | 默认分支跳过注入 | Phase 144 | 阻止错误 project_id 回流写路径 |
| Chat `search_delivery_knowledge` 无 RetrievalTrace | 会话工具强制 `_record_chat_retrieval` | Phase 102 只给 knowledge_read_tools 留痕 | 不要指望改通用 delivery 工具完成本 REQ |

**Deprecated/outdated:** 无。不要新建 Qdrant collection。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 非创建者即使可见仓库也不得回放原始 Q/A | Pattern 4 / 回放授权 | 若产品要队友回放，计划需改授权函数与测试 |
| A2 | git 分支名大小写敏感，不做 casefold | Pattern 5 | `Main` 不会被当默认分支 |
| A3 | 回放响应省略 `client`（模型字段不在账本） | Pattern 4 | 已锁定：固定省略，禁止 null 占位或读取 Ledger |
| A4 | packer/通用检索不传 exclusive `source_kinds=["session_capture"]` | RECALL-02 | 若讨论阶段要求 packer RAG **只**出会话精华，会破坏项目上下文 |

## Open Questions — RESOLVED

1. **RESOLVED — packer 使用 inclusion 语义，不建立排他白名单。**
   - `_layer_rag` 补传 `project_ids=[str(project_id)]`，`source_kinds=None`；测试钉死 `session_capture` 与既有 DOCUMENT 源都可出现，不发明不完整 frozenset。

2. **RESOLVED — lookup unmatched 响应新增 `binding_source`。**
   - 默认分支第三源跳过时固定为 `repo_association_skipped_default_branch`；更新服务端 snapshot，npm 请求 schema 无变化。

3. **RESOLVED — Chat 新增独立 `search_session_knowledge` 工具。**
   - 参数对齐 MCP，必填 `repository_id`、可选 `project_id` AND 收窄；不扩展以 bound project 为主的 `search_project_context`。

4. **RESOLVED — 回放响应省略 `client`。**
   - `SessionCapture` 没有该字段；回放只读账本真源，禁止读取 Ledger 补齐。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | pytest / Django | ✓ | 3.14.2 | — |
| uv + pytest | 契约测试 | ✓ | pytest 9.0.2 | — |
| Node | mcp vitest | ✓ | v24.18.1 | — |
| Qdrant | 向量召回 | 测试 mock `_hybrid_query` | — | 单测不连真实 Qdrant（`--disable-socket`） |
| PostgreSQL | 非本阶段 | 默认 SQLite 套件 | — | 沿用 pytest addopts |

**Missing dependencies with no fallback:** none

**Missing dependencies with fallback:** 真实 Qdrant E2E 非本阶段必达；用 `test_vector_recall.py` 的 filter 断言 + monkeypatch hybrid。

Step 2.6: 已探测；无阻塞。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/knowledge/test_vector_recall.py tests/mcp_tools/test_lookup_project_by_branch.py tests/mcp_tools/test_retrieval_trace.py -q --tb=short` |
| Full suite command | `cd server && uv run pytest tests/knowledge/test_vector_recall.py tests/knowledge/test_retrieval.py tests/knowledge/test_session_capture_retrieval.py tests/mcp_tools/test_search_session_knowledge.py tests/mcp_tools/test_get_session_capture.py tests/mcp_tools/test_lookup_project_by_branch.py tests/mcp_tools/test_retrieval_trace.py tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_get_session_capture_schema_pending.py tests/agents/tools/test_search_session_knowledge.py tests/services/test_project_context_packer.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_access.py tests/knowledge/test_session_capture_source.py -q --tb=short` 以及 `cd mcp && npm test -- tests/server.test.ts` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RECALL-01 | 缺 `repository_id` → 400；有仓过滤；`project_id` AND 收窄；未授权仓 → 空 results 200 | unit/integration | `uv run pytest tests/mcp_tools/test_search_session_knowledge.py -x` | ❌ Wave 0 |
| RECALL-01 | Qdrant must 含 `source_kind` MatchAny `session_capture`；`source_kinds=None` 不含该条件 | unit | `uv run pytest tests/knowledge/test_vector_recall.py -x` | ✅ 扩展现有 |
| RECALL-01 | 真实 helper 精确传 repository/project/DOCUMENT/include/source kwargs；真实 search_similar 把 source_kinds 传给 recall | unit | `uv run pytest tests/knowledge/test_session_capture_retrieval.py tests/knowledge/test_retrieval.py -x` | ❌ Plan 02 |
| RECALL-02 | packer `_layer_rag` 仍 include_document_kind；不 exclusive-filter；session_capture 可出现 | unit | mock `search_similar` | ❌ Wave 0（可放 `tests/services/` 或 packer 测试） |
| RECALL-03 | 创建者 200 含 question/answer；他用户/无行 404 同 body；源码/测试断言无 Ledger 查询 | integration | `uv run pytest tests/mcp_tools/test_get_session_capture.py -x` | ❌ Wave 0 |
| RECALL-04 | `main`+唯一 association → matched false、context 空、有 candidates；`feat/login-page` 仍 matched true；`ProjectBranch` on main 仍 matched | integration | `uv run pytest tests/mcp_tools/test_lookup_project_by_branch.py -x` | ✅ 扩展 |
| RECALL-04 | persist `branch_name=main` 无 project_id + 唯一 association → project FK 空、accepted | integration | `uv run pytest tests/mcp_tools/test_report_session_knowledge.py -x` | ✅ 扩展 |
| OBS-03 | MCP/Chat traces 无 query/正文；create boom 后仍 200/success；空结果 result_count=0 | unit | retrieval_trace + 新会话测试 | ✅ + ❌ Wave 0 |
| MCP-03 延续 | 新工具三面键 + FRIDAY_TOOLS 分波长度 52→53→54 | unit | alignment + vitest | ✅ 分波改计数 |

### Sampling Rate

- **Per task commit:** 该任务触及的单文件 pytest `-x`
- **Per wave merge:** Wave 0 collect-only + npm 52；Plan 02/03 窄测；Plan 04 完整 search snapshot/package + npm 53（排除 get-only pending RED）；Plan 05 Full suite + npm 54
- **Phase gate:** 上表全绿 + ruff 触及的生产文件

### Wave 0 Gaps

- [ ] `server/tests/mcp_tools/test_search_session_knowledge.py` — RECALL-01/02/OBS-03 MCP
- [ ] `server/tests/mcp_tools/test_get_session_capture.py` — RECALL-03
- [ ] `server/tests/agents/tools/test_search_session_knowledge.py` — Chat 同过滤 + 无正文 trace
- [ ] `test_vector_recall.py` 增 `source_kinds` 条件 / None 零回归
- [ ] `test_lookup_project_by_branch.py` 增默认分支第三源
- [ ] `test_report_session_knowledge.py` 增默认分支不绑项目
- [ ] packer RAG 回归（session_capture inclusion）
- [ ] `mcp/tests/server.test.ts` 分波独立全绿：Wave 0 保持 52；Plan 04 加 search 后 53；Plan 05 加 get 后 54
- [ ] Framework install: 无

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `McpToolView` AccessToken + CookieJWT；未认证 401 |
| V3 Session Management | no | 无新会话机制 |
| V4 Access Control | yes | `resolve_allowed_*` intersect；回放创建者∩挂钩；404 防枚举 |
| V5 Input Validation | yes | DRF serializer UUID/max_length；`top_k` 1–20 对齐既有知识工具 |
| V6 Cryptography | no | 无新加密；沿用账本已脱敏字段 |

### Known Threat Patterns for session recall/replay

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR 猜 Capture UUID | Information disclosure | 存在与无权限同一 404 |
| 用 Ledger 拼出原文 | Information disclosure | 回放禁止 join；静态扫描测试禁 `arecord_tool_call`/`ToolCallRecord` 于回放模块 |
| 向量点跨项目泄漏 | Information disclosure | 不放宽 allowed_projects 空短路；repo 必填且 intersect |
| Trace 写入 query/精华 | Information disclosure | payload allowlist；`redact_for_ledger` 二道门 |
| 默认分支错误项目注入 | Tampering（错误挂钩） | 第三源 skip；写路径无 project_id 不绑项目 |
| 观测失败变 500 | Denial of service | best-effort traces |

## Sources

### Primary (HIGH confidence)

- `server/knowledge/retrieval.py` — `search_similar` 签名与 `allowed_projects` 空短路
- `server/knowledge/vector_recall.py` — filter / DOCUMENT 分路 / entity_kinds 短路
- `server/knowledge/collection.py` — `source_kind` KEYWORD 索引
- `server/knowledge/vector_ops.py` — payload 写入 `source_kind`；空 project_id 写 `""`
- `server/knowledge/sources/session_capture.py` — 精华-only DOCUMENT
- `server/knowledge/access_scope.py` — intersect 不放宽
- `server/mcp_tools/views.py` — SearchDeliveryKnowledge、Lookup 三源、ReportSessionKnowledge、McpToolView._record
- `server/services/project_context_packer.py` — `_layer_rag` / `_write_trace`（含 query，会话工具勿抄）
- `server/agents/tools/knowledge_read_tools.py` — `_record_chat_retrieval`
- `server/agents/tools/delivery_knowledge_tools.py` — 通用检索无 session filter、无强制 trace
- `server/initiatives/models/session_capture.py` — 回放字段真源
- `server/interactions/ledger.py` — `record_retrieval_trace` best-effort + redact
- `server/tests/mcp_tools/test_lookup_project_by_branch.py` — feat 第三源合同
- `.planning/observability/LOGGING-SPEC.md` §7/§9
- `.planning/phases/141-capture/141-VERIFICATION.md` / `142-VERIFICATION.md` / `143-VERIFICATION.md`

### Secondary (MEDIUM confidence)

- ROADMAP Phase 144 Success Criteria 与 REQUIREMENTS RECALL/OBS 对照 CONTEXT 锁定句

### Tertiary (LOW confidence)

- 非创建者回放策略（Assumptions A1）

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — 无新库；pytest/Django/Qdrant 均仓库内核实
- Architecture: HIGH — 调用链与缺口均有源码行级证据
- Pitfalls: HIGH — 分路白名单、逃生支、lookup feat 回归、npm 52 均已踩过或测试锁住

**Research date:** 2026-08-28
**Valid until:** 2026-09-27（brownfield 读侧；Qdrant schema 未计划变更）
