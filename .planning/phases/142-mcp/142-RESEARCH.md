# Phase 142: MCP 会话回写契约 - Research

**Researched:** 2026-08-28
**Domain:** Django MCP 写工具契约（serializer / view / url / schema snapshot / npm `mcp/src/tools.ts`）接到 Phase 141 `CaptureService`
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 新工具名固定为 `report_session_knowledge`；必填字段只有非空 `question` 与 `answer`，其中 `answer` 是客户端可见答案精华，不是 transcript 或隐藏思维链。
- 可选元数据完整覆盖 `repository_id`、`git_url`、`branch_name`、`project_id`、`session_id`、`response_model`、`provider`、`input_tokens`、`output_tokens` 与 `client`；不可得字段由既有 `CaptureService` 归一为 `unknown`/`unspecified`，服务端不猜测。
- 成功响应固定包含 `accepted=true`、`capture_id`、`reason`、解析后的可空 `repository_id`/`project_id`、`idempotent_hit` 与 `run_id`；`accepted=true` 的唯一含义是 Capture 已持久化，不承诺已挂钩或已入 RAG。
- 缺少认证或必填问答继续按既有 MCP 基类/DRF 返回 401/400；仓库未解析、项目未解析/未授权/不匹配等业务挂钩结果返回 200，且必须先有 Capture 行。
- View 只做 `_begin`、serializer 校验、调用 `CaptureService.persist`、`_record` 和响应映射；不得直接写 `SessionCapture`，也不得调用 `_resolve_report_project_id` 作为接受门闩。
- 透传 `request.user` 与 `initiated_by_user_id=request.user.id`，并把客户端仓库、项目、会话、模型元数据原样交给 Phase 141 的仓库优先挂钩状态机。
- `repo_unresolved`、`repo_ambiguous`、`project_unresolved`、`project_unauthorized`、`project_repo_mismatch`、`unanchored` 等 `reason` 只描述挂钩结果；不得复用 `branch_unresolved` 表示未收。
- 重试继续复用 Phase 141 的 `(initiated_by_user_id, session_id, question_hash)` first-write-wins 幂等键；命中既有 Capture 时仍返回 `accepted=true` 与原 `capture_id`，不覆盖首次答案或挂钩原因。
- `ReportSessionKnowledgeRequestSerializer`、`TOOL_SCHEMA_SNAPSHOT["report_session_knowledge"]` 与 `mcp/src/tools.ts` 必须使用同一请求键集；snapshot 同时锁定完整响应键集。
- npm 工具注解按非破坏、可幂等的 Friday 内部写操作登记，不能标为只读；工具描述明确“已收 Capture”与“已入知识库”是两回事。
- 扩展现有 `test_schema_snapshot.py`、`test_mcp_package_alignment.py` 与针对新 view 的契约测试，使服务端、snapshot 或 npm 任一面漏字段/漏工具都直接失败。
- 本阶段不借机修整 `report_project_knowledge` 已存在的 snapshot 漂移；新工具从第一天完整对齐，旧工具兼容面原样保留。
- `report_project_knowledge` 继续服务“已定位项目的 MEMORY/RESEARCH 沉淀”，保留项目门闩、质量门、draft/active 与 git-diff 路径；不得扩成 Capture 入口。
- 新工具继续复用 `McpToolView` 的 PAT/JWT 用户身份、`InteractionRun`、RequestMetric 与脱敏 Ledger 记录，但 Ledger 只作调用审计，不作为 Capture 或 RAG 正文。
- 日志与工具留痕不得复制未脱敏问答、git URL、凭证或 token；正文持久化脱敏仍以 `CaptureService` 为唯一安全边界。
- 为旧 `report_project_knowledge` 保留并运行零回归测试，显式断言新工具不会新增 `ProjectMemory`、调用 `MemoryService.append` 或改变 `branch_unresolved` 旧语义。

### Claude's Discretion
- serializer 的具体长度上限、`client` 是否用闭集 ChoiceField、类/测试文件内部拆分由实现者按现有 DRF 与 MCP 约定决定，但不得缩减已锁定的可选元数据。
- response serializer 是否独立成类可由实现者决定；snapshot 与实际响应键必须一致。

### Deferred Ideas (OUT OF SCOPE)
- high/medium/low 评估、durable 状态机与 `session_capture` 入图延后到 Phase 143。
- 仓库/项目召回、Capture 原文回放、默认分支第三源修复和 RetrievalTrace 收口延后到 Phase 144。
- skills 文案、HTTP fallback 与 Cursor / Claude Code hooks 接线延后到 Phase 145。
- 既有 `report_project_knowledge` snapshot 历史漂移不在本阶段顺手修复。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-01 | 用户可通过新工具 `report_session_knowledge` 提交结构化会话回写（必填 `question`/`answer`；可选仓库、分支、会话、项目、`response_model`、`client`） | 新 `McpToolView` + `ReportSessionKnowledgeRequestSerializer`；可选键按 CONTEXT 全集（含 `git_url`/`provider`/`input_tokens`/`output_tokens`）接到 `CaptureService.persist` |
| MCP-02 | 无 `project_id`、仓解析失败或默认分支无法唯一定位项目时，工具仍返回 200 且 `accepted=true` 并产生 Capture 行；`branch_unresolved` 不得表示未收 | View **禁止** `_resolve_report_project_id`；挂钩失败由 persist 写 `link_reason` 仍 create；`reason` 透传 persist 结果；HTTP 200 |
| MCP-03 | 服务端 serializer、`TOOL_SCHEMA_SNAPSHOT` 与 npm `mcp/src/tools.ts` 对 `report_session_knowledge` 三面对齐；缺任一面对齐测试失败 | 扩展 `test_schema_snapshot.py`（urls ↔ snapshot 名集 + 字面量全表）与 `test_mcp_package_alignment.py`（名集）；**新工具另加请求键三面相等**（旧工具不修漂移） |
| MCP-04 | 既有 `report_project_knowledge` 的项目门闩与 git-diff 记忆路径保持零回归，本里程碑不把它扩成 Capture 入口 | 继续跑 `test_report_project_knowledge.py`；新 view 零 Memory/append；旧 `branch_unresolved` 语义不变 |
</phase_requirements>

## Summary

Phase 142 是把 Phase 141 已验证的 `CaptureService.persist` 接到 MCP HTTP 面，并冻结 Cursor / Claude Code 经 `@friday-ai-codes/mcp` 能实际调到的工具契约。生产代码里**尚无** `report_session_knowledge`；141 验证报告已明确该缺口属本阶段。挂钩、脱敏、幂等、unknown 归一、INV-6 写入口都已在 `server/initiatives/services/capture_service.py` 完成，本阶段不得重写状态机。

相邻写工具 `report_project_knowledge` 是**反模式对照**：它用 `_resolve_report_project_id` 当接受门闩，未解析项目时 `accepted=false` + `reason=branch_unresolved` 且不入库。新工具必须相反：Q/A 合法即 persist，挂钩结果只进 `reason`。npm stdio 以 `mcp/src/tools.ts` 的 `FRIDAY_TOOLS` 为静态白名单，只改 Django 而不改 npm 会重现「服务端有、Cursor 调不到」。

**Primary recommendation:** 在 `serializers.py` / `views.py` / `urls.py` / `TOOL_SCHEMA_SNAPSHOT` / `mcp/src/tools.ts` 同步新增 `report_session_knowledge`；view 唯一业务写调用 `CaptureService().persist(actor=request.user, initiated_by_user_id=request.user.id, ...)`；成功一律 HTTP 200 + `accepted=true` + Capture 行可证；三面请求键与 snapshot 响应键用测试锁死；旧工具测试原样保留。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PAT/JWT 鉴权与 InteractionRun | API / Backend | — | `McpToolView._begin` + `IsAuthenticated`；401 `authentication_failed` |
| 请求校验（必填 Q/A、可选元数据） | API / Backend | — | DRF serializer；400 `invalid_params` |
| Capture 脱敏、挂钩、幂等落库 | API / Backend | Database / Storage | 唯一 writer `CaptureService`；INV-6 禁止 view ORM |
| `accepted=true` 语义 | API / Backend | Database / Storage | 以 `initiative_session_captures` 行存在为证，不以 FK 是否非空为证 |
| RequestMetric + Ledger 审计 | API / Backend | Database / Storage | `_record` → `arecord_request_metric` + `arecord_tool_call`（内部 `redact_for_ledger`） |
| npm 工具发现与 HTTP 透传 | Browser / Client（IDE MCP stdio） | API / Backend | `FRIDAY_TOOLS` 白名单；`POST /api/mcp/tools/{name}/` |
| 价值评估 / RAG 入图 | — | — | Phase 143；本阶段禁止 `aschedule_ingestion` / eval |
| Skills / IDE hooks | — | — | Phase 145；本阶段不改 `skills/` 与 `ide_hook_assets.py` |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django | `>=5.1`（仓库 `server/pyproject.toml`） | ORM + URL | 既有后端 |
| djangorestframework + adrf | `>=3.15` / `>=0.1.12` | 异步 `APIView`、Serializer | MCP 全工具同一基类 `McpToolView` |
| CaptureService | 本仓库 Phase 141 | persist | 挂钩/脱敏/幂等已验收 |
| pytest + pytest-django + pytest-asyncio | `>=9.0.2` / `>=4.8` | 契约测试 | `server/tests/mcp_tools/` 惯例 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 既有 | caller 日志 | persist 已打 `session_capture_persist_*`；view **不要**再打问答正文 |
| interactions.ledger | 既有 | ToolCallRecord | 只经 `_record`，禁止手写 Ledger 当正文 |
| `@modelcontextprotocol/sdk` | mcp 包既有 | stdio ListTools/CallTool | 只改 `tools.ts` 定义，不改 SDK |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新 MCP 工具 | 扩展 `report_project_knowledge` | **禁止**（ROADMAP / MCP-04） |
| View 内解析项目再 persist | `_resolve_report_project_id` | 会把默认分支未命中变成「未收」；**禁止** |
| 独立 REST 非 MCP | `/api/projects/...` | 宿主走 MCP 白名单；本阶段只交付 MCP 面 |

**Installation:** 无新 Python/npm 运行时依赖（里程碑锁定）。`slopcheck` 本机不可用；本阶段不安装外部包，审计表为空。

**Version verification:** 未新增 registry 包。Django/DRF/pytest 以 `server/pyproject.toml` 为准，不在本阶段 bump。[VERIFIED: server/pyproject.toml]

## Package Legitimacy Audit

> 本阶段不安装外部包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | n/a | 无候选 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*未运行 slopcheck（命令不存在）；因无新包，planner 不必加 `checkpoint:human-verify` 安装门。*

## Architecture Patterns

### System Architecture Diagram

```text
Cursor / Claude Code
        │  MCP CallTool report_session_knowledge
        ▼
mcp/src/server.ts  (FRIDAY_TOOLS 白名单；未知工具直接 isError)
        │  POST {baseUrl}/api/mcp/tools/report_session_knowledge/
        │  Authorization: Bearer PAT
        ▼
McpToolView._begin  ──401──► {error_code: authentication_failed}
        │
        ▼
Serializer.is_valid  ──400──► {error_code: invalid_params}
        │
        ▼
CaptureService.persist(actor=user, initiated_by_user_id=user.id, Q/A + 元数据)
        │     脱敏 + 仓库优先挂钩 + first-write-wins
        │     永不因挂钩失败跳过 create
        ▼
initiative_session_captures 行 (status=pending_eval)
        │
        ▼
_record(run, input, output, traces=[])  ──► RequestMetric source=mcp
                                          ──► ToolCallRecord (redact_for_ledger)
        │
        ▼
HTTP 200 JSON:
  accepted=true, capture_id, reason=link_reason,
  repository_id?, project_id?, idempotent_hit, run_id
```

挂钩失败仍走图中成功路径。`accepted=true` ≠ RAG。Phase 143 才消费 `pending_eval`。

### Recommended Project Structure

```
server/mcp_tools/serializers.py   # ReportSessionKnowledgeRequestSerializer + SNAPSHOT 条目
server/mcp_tools/views.py         # ReportSessionKnowledgeView(McpToolView)
server/mcp_tools/urls.py          # tools/report_session_knowledge/
mcp/src/tools.ts                  # FRIDAY_TOOLS + TOOL_ANNOTATIONS（计数 51→52）
server/tests/mcp_tools/
  test_report_session_knowledge.py   # 新契约 + MCP-02/04 隔离
  test_schema_snapshot.py            # 字面量加条目
  test_mcp_package_alignment.py      # 名集 + 新工具请求键三面
  test_report_project_knowledge.py   # 零回归，不改断言语义
```

不改：`capture_service.py` 挂钩逻辑、`SessionCapture` 模型/migration、`skills/`、`ide_hook_assets.py`、`tools/handlers/skill_steps.py`。

### Pattern 1: McpToolView 写工具壳

**What:** `_begin` → `_validate` → 业务 service → `_record` → `Response`。
**When to use:** 所有 `/api/mcp/tools/*`。
**Example:** `ReportProjectKnowledgeView.post`（`server/mcp_tools/views.py`）。新 view 用同一壳，业务换成 `CaptureService.persist`，**删除**解析门闩分支。

### Pattern 2: 三面契约

**What:** serializer 字段名 = `TOOL_SCHEMA_SNAPSHOT[name]["request"]` = `tools.ts` `inputSchema.properties` 键。snapshot `response` = 实际 JSON 键（含 `run_id`）。
**When to use:** 每个新 MCP 工具。
**现况:** `test_registered_tools_match_snapshot` 只比 **urls 工具名 ↔ snapshot 键**；`test_mcp_package_tools_match_server_snapshot` 只比 **tools.ts `name:` ↔ snapshot 键**。`report_project_knowledge` 的 snapshot request 仍是 `["project_id","content","source_conversation_id"]`，而 serializer/npm 已有 `branch_name`/`writeback_mode` 等——**历史漂移，本阶段不得修**。[VERIFIED: serializers.py + test_schema_snapshot.py + tools.ts]

### Pattern 3: npm 注解三档

**What:** `query` / `generator` / `executor`。`generator()` 当前是 `readOnlyHint: false` 且 **`idempotentHint: false`**。[VERIFIED: mcp/src/tools.ts]
**When to use:** 新工具按 CONTEXT 要「非破坏、可幂等、非只读」。**不要**直接套 `generator()`（会把幂等标成 false）。应写独立注解对象：`readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: true`, `openWorldHint: false`。

### Anti-Patterns to Avoid

- **把 `_resolve_report_project_id` 当接受条件：** 旧工具未命中项目 → `accepted=false` + `branch_unresolved` 且无草稿。新工具若照抄，MCP-02 直接失败。
- **View 里 `SessionCapture.objects.create`：** INV-6 守卫会红（`test_capture_inv6_guard.py`）。
- **成功返回 201 却让客户端以为失败：** npm `callFridayTool` 用 `resp.ok`（2xx 皆可）。ROADMAP Success #2 锁定挂钩失败也是 **200**；成功路径同样用 **200**，避免与旧工具 draft 的 201 语义混淆。
- **`accepted=false` 表示挂钩失败：** 新工具挂钩失败仍 `accepted=true`。
- **修旧 snapshot：** MCP-03 只要求新工具三面对齐。
- **在 skills 文档写 `report_session_knowledge`：** Phase 145；且 `test_skills_snapshot_guard` 是文档 ⊆ snapshot，本阶段只加 snapshot **不会**因未改 skills 失败。`report_` 前缀已覆盖，无需改正则。
- **把 `client` 写进 SessionCapture：** 模型无该列、persist 无该参数 [VERIFIED: session_capture.py, capture_service.py]。请求必须收该键；view **丢弃、不 persist、不猜测**。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Git URL 挂钩 | View 内再写一套 normalize | `CaptureService` + 既有 `normalize_git_url` | SSH/HTTPS 变体与 `repo_ambiguous` 已测 |
| 项目成员/仓授权 | View 调 access_scope | persist `_resolve_link` | 未授权仍落库并给 `repo_unauthorized` / `project_unauthorized` |
| 幂等 | 客户端 UUID / 条件 update | persist IntegrityError 回读 | 三元组已有 UniqueConstraint |
| 脱敏 | View 再 redact 一遍当唯一边界 | persist 内 `redact_secrets_in_text` | OBS-02 / STORE-03；view 仍勿把明文打进 structlog |
| 鉴权 | 新 permission class | `McpToolView` | PAT + Cookie JWT |
| Ledger | 手写 ToolCallRecord | `_record` → `arecord_tool_call` | 内部已 `redact_for_ledger` |
| 指标 | 自建 QPS | `_record` → `arecord_request_metric` `route=mcp:{tool_name}` | 新入口自动进 MCP 维度 |

**Key insight:** 本阶段复杂度在契约冻结与旧工具隔离，不在挂钩算法。

## Common Pitfalls

### Pitfall 1: 用 `branch_unresolved` 当新工具 reason

**What goes wrong:** MCP-02 失败；与旧工具「未收」同码。
**Why:** `_resolve_report_project_id` 无/多命中固定返回该字符串。
**How to avoid:** 新 view 零引用该 helper。无仓无项目 → persist `unanchored`。`branch_name` 只作为 persist 元数据，**不**用于定位项目。
**Warning signs:** 新测试里出现 `branch_unresolved` 且 `accepted=true` 或无 Capture 行。

### Pitfall 2: persist `reason` 闭集比 CONTEXT 举例更宽

**What goes wrong:** 测试只断言 CONTEXT 列举的 6 个 reason，生产却返回 `linked` / `linked_with_project` / `project_only` / `repo_unauthorized`。
**Why:** `_resolve_link` 成功路径用 `linked*` / `project_only`；仓可见但无写绑定时 `repo_unauthorized`。[VERIFIED: capture_service.py]
**How to avoid:** 响应 `reason` **原样透传** `CapturePersistResult.link_reason`。断言「是挂钩结果、不是未收」；成功挂钩不要误判失败。
**Warning signs:** 合法成员 + 已知 `repository_id` 却 `accepted=false`。

### Pitfall 3: npm 漏工具或漏 properties

**What goes wrong:** Cursor ListTools 没有该工具，或 schema 缺 `git_url` 导致客户端不上报。
**Why:** 历史 23/30 漂移；对齐测试目前只比**工具名**。
**How to avoid:** 名集测试会拦漏工具；**必须新增**「仅针对 `report_session_knowledge`」的请求键三面相等（serializer.fields ↔ snapshot.request ↔ tools.ts properties）。不要把全量 51 工具做字段对齐（会被迫修旧漂移）。
**Warning signs:** `test_mcp_package_tools_match_server_snapshot` 绿但 npm `properties` 缺键。

### Pitfall 4: `client` 或 token 字段类型过严

**What goes wrong:** 客户端传数字 token 或自由 `client` 字符串 → 400，Capture 未收。
**Why:** IntegerField / 过窄 ChoiceField。
**How to avoid:** `input_tokens`/`output_tokens` 用 `CharField`（与模型一致，省略则 persist → `unknown`）。`client` 用可选 `CharField`（闭集 Choice 仅当不缩减「可上报」空间；未知客户端仍应 200 入库）。
**Warning signs:** 仅缺 `client` 的请求 400。

### Pitfall 5: Ledger / 日志带明文 Q/A 或 git_url

**What goes wrong:** OBS-02 / CONTEXT 留痕约束。
**Why:** `_record(input_data=validated)` 会把问答写入 ToolCallRecord；`redact_for_ledger` 去凭证不去 git URL。
**How to avoid:** 不新增 structlog 字段承载 `question`/`answer`/`git_url`。Ledger 走既有 redact 即可（与 `report_project_knowledge` 把 `content` 入 input 同类）；不要在 view 再 log 正文。不要 `traces` 塞问答（RetrievalTrace 属 Phase 144）。
**Warning signs:** 观测测试扫到 token 明文或 git remote。

### Pitfall 6: 把旧工具 201/质量门抄过来

**What goes wrong:** 短答案被 `evaluate_writeback_quality` 拒收；或 201 与「挂钩失败 200」分裂。
**How to avoid:** 无质量门、无 `MemoryService`、无 draft。Q/A 非空即 persist。
**Warning signs:** 新工具测试 import `evaluate_writeback_quality`。

## Code Examples

### CapturePersistResult → MCP 响应映射

```python
# Source: server/initiatives/services/capture_service.py CapturePersistResult
# 映射规则（本阶段规定，非上游现成函数）
output_data = {
    "accepted": True,
    "capture_id": str(result.capture.id),
    "reason": result.link_reason,
    "repository_id": (
        str(result.capture.repository_id) if result.capture.repository_id else None
    ),
    "project_id": (
        str(result.capture.project_id) if result.capture.project_id else None
    ),
    "idempotent_hit": result.idempotent_hit,
    "run_id": str(run.run_id),
}
# HTTP 200；persist 异常则 error_response 5xx，且不得声称 accepted=true
```

### persist 调用（view 唯一写点）

```python
# Source: CaptureService.persist 签名 server/initiatives/services/capture_service.py
result = await CaptureService().persist(
    question=input_data["question"],
    answer=input_data["answer"],
    actor=request.user,
    initiated_by_user_id=request.user.id,
    session_id=input_data.get("session_id"),
    project_id=input_data.get("project_id"),
    repository_id=input_data.get("repository_id"),
    git_url=input_data.get("git_url") or None,
    branch_name=input_data.get("branch_name") or None,
    response_model=input_data.get("response_model"),
    provider=input_data.get("provider"),
    input_tokens=input_data.get("input_tokens"),
    output_tokens=input_data.get("output_tokens"),
    # 不要传 client：persist 无此参数
)
```

### 请求 serializer 键集（锁定）

```python
# 必填: question, answer（allow_blank=False）
# 可选: repository_id (UUID), git_url (CharField max_length<=500),
#       branch_name, project_id (UUID), session_id (CharField max_length=255, 非 UUID),
#       response_model, provider, input_tokens, output_tokens, client
# 长度上限 discretionary；建议 question/answer max_length=20000 对齐 report_project_knowledge.content
```

### npm 工具骨架

```typescript
// Source: mcp/src/tools.ts FRIDAY_TOOLS / TOOL_ANNOTATIONS 模式
{
  name: 'report_session_knowledge',
  description: '提交本轮问题与可见答案精华到 Friday Capture 账本（accepted=true 仅表示已收 Capture，不表示已挂钩仓库或已入知识库/RAG）。不要上传隐藏思维链或全文 transcript。',
  inputSchema: {
    type: 'object',
    additionalProperties: false, // 与 graph_query 等严格工具一致；旧 report_project_knowledge 未设，新工具从第一天锁死
    properties: { /* 与 snapshot request 同键 */ },
    required: ['question', 'answer'],
  },
}
// annotations: 自定义幂等写，不要 generator()
```

### urls

```python
# Source: server/mcp_tools/urls.py report_project_knowledge 旁
path(
    "tools/report_session_knowledge/",
    ReportSessionKnowledgeView.as_view(),
    name="mcp-tool-report-session-knowledge",
)
# 完整路径: POST /api/mcp/tools/report_session_knowledge/
# [VERIFIED: server/friday/urls.py path("mcp/", include("mcp_tools.urls"))]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| IDE 收工只走 `report_project_knowledge`（项目门闩） | 会话 Q/A 走独立 Capture 工具 | v0.25.0 / Phase 142 | 无项目也能收 |
| 141 仅 service 测试调用 persist | MCP HTTP 为宿主入口 | Phase 142 | npm 白名单必须同步 |
| snapshot 与 serializer 可漂移 | 新工具字段级三面锁 | 本阶段 | 旧工具维持现状 |

**Deprecated/outdated:**

- 用 `branch_unresolved` 表示「会话知识未收」——仅旧记忆工具 fail-soft 跳过写入。
- 把 Interaction Ledger payload 当 Capture 正文（v0.17 已锁；141 已分离）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 请求收 `client`，SessionCapture 不加列；经 MCP `_record` 审计元数据保留（audit-not-model） | Don't Hand-Roll / Pitfall 4；Open Questions #1 RESOLVED | 用户若要按 client 过滤 Capture 表，另开 STORE 增量 |
| A2 | 成功 HTTP 状态用 200 而非 201 | Pitfall 6 | 若产品要坚持 REST「创建 201」，npm 仍可工作（`resp.ok`）；与 ROADMAP 字面「返回 200」冲突时以 CONTEXT/ROADMAP 200 为准 |

**若表为空则无需确认：** 其余挂钩/鉴权/snapshot 行为均有代码引用。A1/A2 为 discretionary 边界上的实现选择，CONTEXT 已把 HTTP 200 与可选键锁定；A1 是唯一真正的模型缺口说明。

## Open Questions

1. **`client` 是否要在后续相位加列？** — **RESOLVED（本阶段）**
   - Decision: 142 只接线公开请求键，不改 SessionCapture / CaptureService 签名。`client` 经 serializer 接受，并由既有 `McpToolView._record` → redacted `ToolCallRecord.input` 作为 audit metadata 保留（audit-not-model）；不静默从公开 schema 删除该键。按 IDE 宿主切片过滤若需要，另开 STORE 增量加列，不在 142 做 migration。
   - What we know: 141 模型无 `client`；persist 无参数。

2. **字段级对齐是否扩展到全部工具？** — **RESOLVED**
   - Decision: **仅**新工具 `report_session_knowledge` 字段级三面相等；禁止全量 51 工具 properties 对齐，也不修 `report_project_knowledge` 历史 snapshot 漂移。
   - What we know: 旧 `report_project_knowledge` snapshot 已漂。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | pytest | ✓ | 3.14.2 | — |
| uv | `cd server && uv run pytest` | ✓ | 0.12.0 | `pytest` in venv |
| Node | 非本阶段必跑 mcp vitest | ✓ | v24.18.1 | MCP 契约由 Python 读 `tools.ts` |
| slopcheck | 新包审计 | ✗ | — | 无新包，跳过 |
| Context7 / graphify | 库文档 / 图谱 | ✗ | graphify disabled | 以仓库源码为权威 |

**Missing dependencies with no fallback:** none for this phase

**Missing dependencies with fallback:** slopcheck, graphify（已跳过）

Step 2.6: 本阶段无新外部服务；测试用 Django SQLite + `mcp_client` PAT fixture。

## Validation Architecture

`workflow.nyquist_validation` = true（`.planning/config.json`）。`tdd_mode` = false，但仍须可自动化验收。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥9.0.2 + pytest-django + pytest-asyncio |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/mcp_tools/test_report_session_knowledge.py tests/mcp_tools/test_schema_snapshot.py tests/mcp_tools/test_mcp_package_alignment.py tests/mcp_tools/test_report_project_knowledge.py tests/initiatives/test_capture_inv6_guard.py -q --tb=short` |
| Full suite command | `cd server && uv run pytest tests/mcp_tools/ tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_memory_inv6_guard.py -q --tb=short` |

`addopts` 已排除 `perf`/`integration`/`slow`/`postgres_queue`。MCP 工具测用 `pytest.mark.django_db`；写库+async 用 `transaction=True`（见 `test_report_project_knowledge.py`）。

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCP-01 | 认证用户 POST 必填 Q/A + 可选元数据 → 200 `accepted` + `capture_id` | integration | `uv run pytest tests/mcp_tools/test_report_session_knowledge.py::test_member_report_persists_capture -x` | ❌ Wave 0 |
| MCP-01 | 缺 Q 或 A → 400 `invalid_params` | integration | `...::test_missing_question_or_answer_400` | ❌ Wave 0 |
| MCP-01 | 匿名 → 401 `authentication_failed` | integration | `...::test_missing_token_401` | ❌ Wave 0 |
| MCP-02 | 无 project/repo → 200 `accepted=true`，行存在，`reason=unanchored` | integration | `...::test_unanchored_still_accepted` | ❌ Wave 0 |
| MCP-02 | 坏 git_url → 200 `accepted=true`，`reason=repo_unresolved`，有行 | integration | `...::test_unresolved_repo_still_accepted` | ❌ Wave 0 |
| MCP-02 | 仅 `branch_name=main`（无 project_id）→ 200 `accepted=true`，**不是** `branch_unresolved` | integration | `...::test_default_branch_does_not_mean_rejected` | ❌ Wave 0 |
| MCP-02 | 响应 `reason` 透传 persist，含 `repo_unauthorized` 等 | integration | `...::test_link_reason_passthrough` | ❌ Wave 0 |
| MCP-01/02 | 幂等重试 → 同行 `capture_id`，`idempotent_hit=true`，答案不覆盖 | integration | `...::test_idempotent_hit_keeps_first_write` | ❌ Wave 0 |
| MCP-03 | urls 名集 == snapshot 键（含新工具） | unit | `test_schema_snapshot.py::test_registered_tools_match_snapshot` | ✅ 需改字面量 |
| MCP-03 | snapshot 字面量含新工具 request/response 全键 | unit | `test_mcp_read_tool_schema_snapshot` | ✅ 需改巨型 dict |
| MCP-03 | npm 工具名 == snapshot | unit | `test_mcp_package_alignment.py::test_mcp_package_tools_match_server_snapshot` | ✅ 改 tools.ts 即绿 |
| MCP-03 | **新工具** serializer ↔ snapshot.request ↔ tools.ts properties | unit | `test_mcp_package_alignment.py` 新增 `test_report_session_knowledge_request_keys_aligned` | ❌ Wave 0 |
| MCP-04 | 旧 `test_report_project_knowledge.py` 全绿（含 `branch_unresolved` 未收） | integration | `test_report_project_knowledge.py -q` | ✅ |
| MCP-04 | 新工具不增加 `ProjectMemory`、不走 `MemoryService.append` | integration | `...::test_session_tool_does_not_write_project_memory` | ❌ Wave 0 |
| STORE-03 | view 无 `SessionCapture.objects.create` | unit | `test_capture_inv6_guard.py` | ✅ 无改则持续守护 |
| OBS-02 | 密钥不进 Capture 行（persist 已测）；MCP 测可再断言行内无 sk- | integration | `...::test_redaction_on_mcp_path` | ❌ Wave 0 建议 |

### Sampling Rate

- **Per task commit:** Quick run command 上表
- **Per wave merge:** Full suite command 上表
- **Phase gate:** Full suite green before `/gsd-verify-work`；并跑既有 `test_report_project_knowledge.py` 全文件

### Wave 0 Gaps

- [ ] `server/tests/mcp_tools/test_report_session_knowledge.py` — MCP-01/02/04 契约
- [ ] `test_mcp_package_alignment.py` — `report_session_knowledge` 请求键三面（从 `ReportSessionKnowledgeRequestSerializer().fields`、snapshot、`tools.ts` 解析 `properties`）
- [ ] `test_schema_snapshot.py` 与 `TOOL_SCHEMA_SNAPSHOT` 同步加条目（非新文件）
- [ ] Framework install: 无 — 已有 pytest

既有 `mcp_client` / `access_user` fixture（`server/tests/mcp_tools/conftest.py`、`server/tests/conftest.py`）可复用。仓挂钩用例复用 `repository` fixture + 把 user 放进 space（参考 `test_capture_service.py` 与 `repository_in_user_space`）。

**141 行为测试不要当 MCP 合同重复实现一遍挂钩矩阵**；MCP 测选代表性路径（unanchored / unresolved / idempotent / 授权仓），细矩阵仍以 `test_capture_service.py` 为准。

## Security Domain

`security_enforcement` 启用；ASVS Level 1。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `AccessTokenAuthentication` + `CookieJWTAuthentication`；匿名 401 |
| V3 Session Management | no | 无浏览器 session cookie 新逻辑；PAT 既有 |
| V4 Access Control | yes | persist 挂钩用 `resolve_allowed_*` + 项目成员；未授权不绑 FK **仍落库**（与只读 scope 分离，141 已锁） |
| V5 Input Validation | yes | DRF Serializer；`allow_blank=False` 于 Q/A |
| V6 Cryptography | no | 不新造加密；凭证仍走既有 token 存储 |

### Known Threat Patterns for MCP Capture 写入

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 未认证写入 | Spoofing | `IsAuthenticated` + `_begin` auth None → 401 |
| 问答夹带 API key | Information Disclosure | `CaptureService` `redact_secrets_in_text`；Ledger `redact_for_ledger` |
| 把未授权仓/项目写进 FK | Elevation of Privilege | persist 不绑 FK；仍 `accepted=true`（故意：永不丢账） |
| 用 Ledger 当 RAG 正文 | Information Disclosure | 禁止 RetrievalTrace 塞问答；召回属 144 |
| 幂等键碰撞覆盖他人答案 | Tampering | 键含 `initiated_by_user_id`；跨用户同 session 字符串不碰撞 |
| 客户端伪造 `accepted` | Tampering | 服务端恒输出 `True` 仅当 persist 返回；测试以 DB 行证明 |
| 扩展旧工具绕过 draft 门 | Elevation of Privilege | MCP-04：禁止改 `ReportProjectKnowledgeView` 行为 |

## Project Constraints (from .cursor/rules/)

来源：`.cursor/rules/observability-logging.mdc` + `LOGGING-SPEC.md`。

- 用 `structlog.get_logger(__name__)`；事件 snake_case；kv 字段；禁止把变量拼进 message。
- 脱敏不可绕过：`redact_credentials` / `redact_secrets_in_text` / ledger `redact_for_ledger`。
- 入口用户由中间件注入；MCP `_begin` 已 `bind_source(LogSource.MCP)`。
- 新 MCP 入口：`_record` 已写 RequestMetric（`source=mcp`, `labels.call_source=tool_name`）——**不要**再发明第二套 QPS。
- Capture persist 已有 `session_capture_persist_started/completed/failed`（caller, component=knowledge, `duration_ms` 在 completed/failed）。View **不要**重复打带正文的 lifecycle。
- 观测 best-effort，不反噬 persist。
- 本阶段 **不** 新增 `call_source=session_capture_eval`（Phase 143）；**不** 写 RetrievalTrace（Phase 144）。
- 无新 LLM 调用点。

## Sources

### Primary (HIGH confidence)

- `.planning/phases/142-mcp/142-CONTEXT.md` — 锁定决策
- `.planning/ROADMAP.md` Phase 142 Success Criteria；`.planning/REQUIREMENTS.md` MCP-01..04
- `.planning/phases/141-capture/141-VERIFICATION.md` — persist 已验收、MCP 未接
- `server/initiatives/services/capture_service.py` — persist 签名与 `link_reason`
- `server/initiatives/models/session_capture.py` — 无 `client` 列
- `server/mcp_tools/views.py` — `McpToolView`、`ReportProjectKnowledgeView`、`_resolve_report_project_id`
- `server/mcp_tools/serializers.py` — `TOOL_SCHEMA_SNAPSHOT`；旧工具 request 漂移
- `server/mcp_tools/urls.py` + `server/friday/urls.py` — `/api/mcp/tools/`
- `mcp/src/tools.ts` + `mcp/src/server.ts` — 51 工具白名单、`resp.ok`、`generator()` 非幂等
- `server/tests/mcp_tools/test_schema_snapshot.py`、`test_mcp_package_alignment.py`、`test_skills_snapshot_guard.py`、`test_report_project_knowledge.py`
- `server/tests/initiatives/test_capture_inv6_guard.py`
- `.planning/observability/LOGGING-SPEC.md` §10 `session_capture_persist_*`

### Secondary (MEDIUM confidence)

- Phase 141 PATTERNS / 03–04 SUMMARY — 挂钩与观测边界
- `server/interactions/ledger.py` — `arecord_tool_call` 必经 `redact_for_ledger`

### Tertiary (LOW confidence)

- Graphify：`.planning/config` 中 graphify 未启用，无图谱交叉边。

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — 零新依赖，全是仓库内 MCP + Capture
- Architecture: HIGH — view 接线与反模式均有源码
- Pitfalls: HIGH — 旧工具门闩、snapshot 漂移、npm 白名单均已在测试注释中记录

**Research date:** 2026-08-28
**Valid until:** 2026-09-27（内部契约；30 天）
