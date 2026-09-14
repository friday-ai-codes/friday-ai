# Architecture Patterns

**Domain:** Friday AI v0.26.0 公共 MCP 全链路集成
**Researched:** 2026-09-14
**Overall confidence:** HIGH（仓内接缝均以当前源码为准；MCP Tasks 为 2025-11-25 新规范，客户端普及度为 MEDIUM）

> 结论：公共 MCP 应当是**端口适配层**，不是第二套业务后端。MCP 与 REST 都调用同一组
> application service；`process_runtime`、`BlueprintLifecycleService`、`ArtifactService` 和
> `DurableTaskService` 继续分别作为编排、HITL 生命周期、版本产物和后台执行的事实源。
> 新增的 public operation 只保存调用归属、幂等预留及 canonical resource locator，不复制
> session/artifact/repo-task 状态。契约从服务端注册表机械生成 npm 定义并由 CI `--check`。

## Recommended Architecture

```text
MCP client
  │ tools/list + tools/call
  ▼
@friday-ai-codes/mcp（stdio / 后续可增 Streamable HTTP）
  │ generated tool registry；PAT 原样转发；协议错误标准化
  ▼
Django public MCP adapter
  │ authenticate → authorize project/artifact → validate contract
  │ reserve idempotency → call application command/query → record ledger
  ├───────────────┬──────────────────┬─────────────────────┐
  ▼               ▼                  ▼                     ▼
Blueprint        Blueprint          Blueprint              PublicOperation
Context/Access   Gate Commands      Review Commands        Projection Service
Resolver         (HITL)             (HITL)                 (read-only projection)
  │               │                  │                     │
  └───────────────┴─────────┬────────┴─────────────────────┘
                            ▼
       process_runtime / BlueprintLifecycleService / ArtifactService
                            │
                  DB canonical state + append-only events
                            │
        DurableTaskService（resume/recovery；任务 id 不对外）
                            │
           repo_plan → merge → ai_review → human review
```

核心方向：

1. **传输只适配，不编排。** MCP view 不写 ORM、不重做状态转移、不导入另一个 API view 的私有 helper。
2. **状态只投影，不复制。** 对外 `operation_id` 是稳定句柄；状态从
   `ConvergenceSession`、`Artifact`、`BlueprintThread`、`RepoResearchTask` 和 durable job
   汇总得到。
3. **HITL 是显式 command。** 仓库确认、澄清回答、评审批准/驳回、stage 重跑各自走 canonical
   command，并携带不可变版本坐标或 revision，避免在旧快照上做决定。
4. **契约生成代替手工三抄。** Python registry/serializer/response serializer 是输入，
   `TOOL_SCHEMA_SNAPSHOT`、npm tool definitions 与可发布 JSON manifest 是生成物。
5. **显式 operation API 是兼容基线。** 先提供 `start/get/list/cancel-or-retry` 工具；MCP
   2025-11-25 Tasks 可在后续作为同一 operation service 的协议投影，不能取代领域状态。

### Component Boundaries

| Component | New / Modify | Responsibility | Communicates With |
|-----------|--------------|----------------|-------------------|
| `McpToolRegistry` + contract generator | **NEW** | 每个工具登记名称、版本、request/response serializer、annotations、scope policy、async mode；生成 JSON Schema 2020-12、snapshot 与 npm registry | serializers、URL adapter、CI、`mcp/src` |
| generated npm tools | **MODIFY / GENERATED** | 替换 `mcp/src/tools.ts` 手写 `FRIDAY_TOOLS`；只负责协议声明与 HTTP 路由元数据 | npm MCP server、Django endpoints |
| public MCP blueprint adapters | **NEW** | `_begin`、鉴权、契约校验、调用 command/query、`_record`；零业务写入 | context resolver、commands、operation service |
| `BlueprintContextResolver` | **NEW（从 view helper 提取）** | 由 artifact/session/thread/technical-plan 定位同一 canonical 上下文 | Artifact、ConvergenceSession、WorkItem |
| `BlueprintAccessPolicy` | **NEW（从 REST helper 提取）** | fail-closed 用户、项目成员、artifact 归属与 action 权限校验 | Project membership、context resolver |
| REST blueprint views | **MODIFY** | 改调共享 resolver/policy/commands；继续保留原 URL/响应 | application services |
| `BlueprintGateCommandService` | **NEW / EXTRACT** | confirm/add/remove/reclassify/edit responsibility/upgrade 的唯一 application boundary | `BlueprintLifecycleService`、repo gate lock/patch |
| `BlueprintReviewCommandService` | **NEW / EXTRACT** | answer/resolve/dismiss/approve/reject 的唯一 application boundary | lifecycle、review action service |
| `BlueprintStageControlService` | **MODIFY / WRAP** | 暴露 stage snapshot、整 stage 重跑；复用 `arerun_blueprint_stage` | process runtime、durable resume |
| `BlueprintQueryService` | **NEW / EXTRACT** | gate/review/stage/repo-plan/merge 快照；不返回私有 CoT | canonical models、renderer |
| `PublicOperationService` | **NEW** | 幂等预留、owner/scope 绑定、canonical locator、统一状态投影、分页查询 | session/artifact/thread/repo tasks/durable |
| `PublicMcpOperation` | **NEW，薄信封** | 保存 operation UUID、tool/kind、actor/project、request hash、idempotency scope、canonical IDs；不成为业务状态事实源 | operation service |
| `process_runtime` | **REUSE** | 驱动 stage graph、pause/resume、租约、repo plan/merge/review | lifecycle、artifact、durable |
| `BlueprintLifecycleService` | **REUSE / 小扩展** | 蓝图和 thread 合法状态迁移；所有 HITL writer | command services |
| `DurableTaskService` | **REUSE** | 可靠 resume/recovery、去重与 worker 状态；内部实现细节 | process runtime |
| `ConvergenceSessionEvent` | **REUSE** | append-only progress/event 来源 | operation projection、可选 MCP progress |
| task `submit` MCP | **UNCHANGED** | 容器内 agent 结构化产物提交；不是 public control plane | repo-plan worker、capture |

### Service Extraction Boundaries

当前 REST 已经委托了大部分 canonical writer，但仍把 transport 与 application 逻辑混在一起：

- `blueprint_review_views.py` 的 `_aload_artifact`、`_aload_session`、
  `_aassert_project_scope` 被 `blueprint_stage_views.py` 跨 view 私有导入。应提取为
  `delivery/services/blueprint_context.py` 与 `blueprint_access.py`，REST/MCP 同调。
- `blueprint_gate_views.py` 的 thread 装载、snapshot 组装、锁和 action dispatch 应拆成
  query + command。HTTP status mapping 留在 view；合法状态与 CAS 留在 service。
- `BlueprintReviewActionService`、`BlueprintLifecycleService`、
  `arerun_blueprint_stage` 已是 writer seam，应保留；新 application command 仅做上下文装配、
  授权后参数化调用与返回 DTO，不复制内部逻辑。
- `blueprint_stage_views.py` 的 `_STAGE_STATE_KEYS`、版本行组装属于公共查询投影，移入
  `BlueprintQueryService` 后由 REST/MCP 共用。
- `technical_plan_service.py` 中 canonical blueprint → legacy `repository_tasks` 的映射继续
  只存在一份。MCP 新蓝图查询返回 canonical content；仅旧工具调用兼容投影。

禁止提取成“万能 service”：

- access policy 不做状态迁移；
- query service 不写 ORM；
- operation service 不直接修改 blueprint；
- durable service 不解释业务阶段；
- MCP adapter 不持有 transaction lock 或调用私有 `_a*` view helper。

## Public Tool Surface

工具名应以产品动作而非内部模型命名。具体命名在规格阶段冻结，但能力边界建议如下。

### Operation and Read Tools

| Capability | Semantics | Canonical source |
|------------|-----------|------------------|
| start technical blueprint | 幂等创建/复用 operation；启动现有 `technical_blueprint` process | `delegate_process_runtime` / entrypoint |
| get operation | 返回统一 envelope、当前 phase、pending actions、artifact refs、safe error | operation projection |
| list operations | 仅当前 actor 且按 project scope 过滤；cursor pagination | operation envelope + access policy |
| get blueprint | 返回当前 immutable version coordinates、status、rendered/canonical content | Artifact/ArtifactVersion |
| get repo-plan progress | 每仓状态、attempt、safe error、partial plan refs、dependency wave | RepoResearchTask/PartialPlan/session stage state |
| get merge/review result | merge gates、findings、open threads、current version | Artifact/threads/session |
| get events | cursor-based append-only progress，payload allowlist | ConvergenceSessionEvent |

### HITL and Control Tools

| Capability | Required concurrency guard | Canonical command |
|------------|----------------------------|-------------------|
| repository gate actions | `thread_id + expected_revision/snapshot_hash` | gate command service → lifecycle |
| answer clarification | `thread_id + expected_thread_status` | review command service → lifecycle |
| resolve/dismiss finding | `thread_id + expected_thread_status` | review action service |
| approve blueprint | `artifact_id + version_id + content_hash` | `aapprove_blueprint` then existing handoff pin |
| reject/request changes | same immutable version coordinates + structured rework scope | existing review action |
| rerun repo-plan/merge stage | `artifact_id + current version/revision + stage` | `arerun_blueprint_stage` |

不要新增独立的“start merge”或“start repo plan”旁路。确认仓库门后由 stage graph 自然进入
`repo_plan`；repo-plan 完成后由 engine 进入 `merge`。人工控制只能是合法 gate action、
clarification answer 或 canonical stage rerun。

## Asynchronous Operation Contract

### Stable Envelope

```json
{
  "operation_id": "uuid",
  "kind": "technical_blueprint",
  "status": "accepted|running|input_required|succeeded|failed|cancelled",
  "phase": "repo_confirmation|repo_plan|merge|ai_review|human_review",
  "terminal": false,
  "progress": {"completed": 2, "total": 5},
  "pending_actions": [{"type": "confirm_repositories", "resource_id": "uuid"}],
  "resources": {
    "session_id": "uuid",
    "artifact_id": "uuid",
    "artifact_version_id": "uuid",
    "content_hash": "sha256"
  },
  "error": null,
  "retry": {"allowed": false, "action": null},
  "poll_after_ms": 2000,
  "updated_at": "RFC3339"
}
```

映射规则必须集中在 `PublicOperationProjection`：

- `ConvergenceSession.created/running/waiting_event` → `accepted/running`；
- `waiting_clarification`、开放的 repo confirmation gate、`pending_review` →
  `input_required`，并列出**允许的** action；
- `Artifact.blueprint_status=confirmed|implemented` → `succeeded`；
- canonical `failed` → `failed`，只暴露稳定 `error.code` 与脱敏摘要；
- repo task 失败但 engine 仍可隔离推进时，operation 仍是 `running` 或 `input_required`，
  不能因为一个子任务直接标整体 failed。

`status` 不写回 `PublicMcpOperation` 作为权威值；允许保存 `last_projected_status` 仅供索引/诊断，
每次响应必须重新校验 canonical source。`durable_job_id` 不对外，因为重排、重试或后端替换都
可能改变它。

### Idempotency

`idempotency_key` 必须按以下复合域唯一，而不是当前
`McpWorkItemTechnicalPlan.idempotency_key` 的裸全局键：

```text
(actor_id, project_id, tool_name, idempotency_key) UNIQUE
request_hash = sha256(canonical_json(validated_input_without_volatile_fields))
```

- 首次请求：事务内 reserve operation，再启动 canonical process，最后绑定 session/artifact。
- 同 key 同 hash：返回同一 operation，不重复 dispatch。
- 同 key 异 hash：409 `idempotency_key_conflict`。
- reserve 后进程崩溃：operation 标记可接管；接管仍先查询 active session / durable
  idempotency key，不能盲目重派。
- 所有 mutation 使用独立 action idempotency key；approve/reject 等还必须做 version CAS。

### MCP Tasks Compatibility

MCP 2025-11-25 已定义 task-augmented `tools/call`、`tasks/get`、`tasks/result`、
`tasks/cancel`，并要求 capability negotiation 与工具级
`execution.taskSupport=optional|required|forbidden`。

本里程碑建议：

1. **先把显式 operation tools 作为所有客户端可用的稳定合同。**
2. 若当前 TypeScript SDK 与目标客户端矩阵验证通过，可把 long-running start tool 标为
   `taskSupport: optional`；task ID 映射到同一个 `operation_id`。
3. `tasks/get/result/cancel` 只调用 `PublicOperationService`，不得建立第二个 task 状态表。
4. 不应标 `required`：旧客户端与 npm 当前静态代理必须继续正常工作。
5. `tasks/cancel` 只有 canonical stage 可安全取消时才开放；不能把“停止轮询”伪装成取消业务。

## Contract Generation

### Single Source

建议引入 Python declarative registry：

```python
register_tool(
    name="get_blueprint_operation",
    request=GetOperationRequestSerializer,
    response=OperationResponseSerializer,
    scope=Scope.OWNED_PROJECT,
    async_mode=AsyncMode.READ_OPERATION,
    annotations={"readOnlyHint": True, "idempotentHint": True},
)
```

生成链：

```text
Python Tool Registry
  ├─ serializer-derived input/output JSON Schema 2020-12
  ├─ server/contracts/mcp-tools.v1.json + manifest hash
  ├─ TOOL_SCHEMA_SNAPSHOT compatibility projection
  ├─ mcp/src/generated/tools.ts
  └─ docs / contract fixtures
```

仓库已有 `server/contracts/graph-query.v1.json` +
`services/code_graph/query_manifest.py` 的 canonical manifest/hash 模式，可以复用目录和 hash
约定，但 MCP manifest 应由 generator 生成，不能再手改 JSON 与 TypeScript。

### Drift Gates

CI 必须执行：

1. `python manage.py generate_mcp_contracts --check`：工作树不得产生 diff；
2. registry 工具名 = Django URL 工具名 = generated npm 工具名；
3. request/response examples 双向 JSON Schema 校验；
4. npm route/HTTP fallback 只可引用 manifest 中工具；
5. additive/breaking diff 分类：删除工具、删字段、加 required、收窄 enum 为 breaking；
6. manifest hash 在 npm build metadata 中输出，连接诊断可显示 client/server hash；
7. 旧 `TOOL_SCHEMA_SNAPSHOT` 在迁移期由 generator 产出，避免一次性破坏现有测试。

不建议直接从 `TOOL_SCHEMA_SNAPSHOT` 生成 npm：它目前只保存 input/output schema，缺少
权限、annotations、async semantics 和 transport route；也不建议从 `mcp/src/tools.ts`
反向生成服务端，因为验证与权限事实源必须在 fail-closed 的 Django 侧。

## Data Flow

### Start and Poll

```text
tools/call start_technical_blueprint(idempotency_key, work_item/context)
  → npm proxy forwards PAT
  → Django authenticates token
  → ContextResolver resolves work item/project
  → AccessPolicy confirms membership (unknown/missing = deny)
  → serializer validates, operation service reserves scoped key
  → existing process_runtime entrypoint starts/resumes technical_blueprint
  → bind operation → session/artifact, return accepted envelope
  → DurableTaskService drives resume/recovery

tools/call get_blueprint_operation(operation_id)
  → load operation owned by actor
  → re-authorize current project scope
  → project session/artifact/thread/repo-task/event state
  → return status + pending_actions + poll_after_ms
```

### Repository Gate to Merge

```text
get operation → input_required(confirm_repositories)
  → get repository gate snapshot
  → add/remove/reclassify/edit via GateCommandService (CAS)
  → confirm via BlueprintLifecycleService
  → existing resume helper enqueues idempotent drive
  → ProcessEngine: spec_gate → repo_plan
  → per-repo task container submit MCP persists canonical PartialPlan
  → dependency waves finish; failures isolated or clarification thread opened
  → ProcessEngine enters merge
  → blueprint_merge writes new ArtifactVersion through ArtifactService
  → ai_review creates findings/threads
  → operation projects input_required(human_review)
```

### Review and Handoff

```text
get blueprint/review snapshot (version_id + content_hash)
  → answer/resolve/dismiss via ReviewCommandService
  → approve with exact immutable coordinates
  → BlueprintLifecycleService confirms
  → pin_approved_blueprint_handoff maps canonical execution_plan
     to legacy repository_tasks exactly once
  → subsequent coding handoff rechecks artifact/version/hash fail-closed
```

## Authorization and Scope

每个 public MCP request 都执行两层校验：

1. **Authentication:** PAT/JWT 解析为真实 user；匿名、失效、无法关联用户即拒绝。
2. **Object scope:** 从 canonical relation 推导 project（operation → work item/artifact →
   project），并验证成员/action 权限。禁止信任 payload 自报的 `project_id`。

规则：

- operation owner 检查不能替代 project membership；用户离开项目后旧 operation 也不可读。
- artifact/thread/session ID 任一不属于同一 context → 404 或稳定 `resource_not_found`，避免
  泄漏存在性。
- 无法推导 project、关系缺失、多重歧义一律 deny；不允许“系统默认项目”。
- 后台任务携带 `initiated_by_user_id`，但 worker 不把它当实时授权；授权在入口做，异步动作
  只执行已持久化、不可变的 command intent。
- approve/reject/confirm 等高影响动作应在 service 内再次校验状态与 version CAS。

## Patterns to Follow

### Pattern 1: Ports and Adapters

**What:** REST 与 MCP 是两个 inbound adapter，共享 application command/query。
**When:** 所有既有 REST-only gate/review/stage 能力。
**Why:** transport 只负责 auth、schema 和 HTTP/MCP error mapping，领域规则只有一个 writer。

### Pattern 2: Thin Operation Envelope

**What:** operation 保存幂等与寻址，状态从 canonical 聚合。
**When:** 任何超过一次请求生命周期、可 pause/resume 的调用。
**Why:** durable job、session、artifact 和 HITL thread 各有不同生命周期；将其中任一 ID 直接
当公共 job ID 都会泄漏内部实现。

### Pattern 3: Immutable Decision Coordinates

**What:** 人类决策携带 `artifact_id/version_id/content_hash` 或 thread revision。
**When:** confirm/approve/reject/rerun/edit。
**Why:** 防止用户读取 v3 后误批已经被并发任务推进到 v4 的蓝图。现有 confirmed handoff 已按
artifact/version/hash 三项逐一核验，应推广到所有 public HITL mutation。

### Pattern 4: Event Projection, Not Event Authority

**What:** `ConvergenceSessionEvent` 提供增量进度，当前状态仍读 canonical row。
**When:** `get_operation_events`、MCP progress notification、审计。
**Why:** append-only event 可能延迟或丢失 best-effort 观测事件，不能靠回放决定业务合法性。

### Pattern 5: Safe, Best-Effort Observability

**What:** adapter 记录 caller lifecycle；stage/LLM/repo-loop 用 sampling；Ledger 和指标失败不
影响 command。
**When:** 每个 public tool 与后台 resume。
**Required fields:** `category`、`component`、`duration_ms`、`initiated_by_user_id`、
`operation_id`、`session_id`、`artifact_id`、`request_id/run_id`。
**Redaction:** instruction、clarification answer、upstream error 先
`redact_secrets_in_text`；日志只记正文长度/hash，Ledger 走 `redact_for_ledger`。

## Anti-Patterns to Avoid

### Anti-Pattern 1: MCP View Calls REST View

**What:** MCP import `_aassert_project_scope` 或实例化 REST view。
**Why bad:** 私有 transport helper 成为隐式 API，权限与响应耦合，第三个入口必然继续复制。
**Instead:** 把 context/access/command/query 提取到 `delivery/services`。

### Anti-Pattern 2: Second Blueprint State Machine

**What:** `McpOperation.status` 自行推进 repo-plan/merge/review。
**Why bad:** 与 `ConvergenceSession`/`Artifact.blueprint_status` 竞态，恢复后漂移。
**Instead:** status projection；operation 只保留 idempotency 与 canonical locator。

### Anti-Pattern 3: Expose Durable Job IDs

**What:** 让客户端 poll/cancel Procrastinate job。
**Why bad:** 一次业务 operation 可产生多个 resume job，后端可切换，job 完成也不等于蓝图完成。
**Instead:** 公共 operation ID + canonical projection。

### Anti-Pattern 4: Manual Schema Copies

**What:** 同时手改 serializer snapshot、Django URL、npm `tools.ts` 和文档。
**Why bad:** 当前架构只能靠测试发现部分漂移，response/annotations/scope 无机械来源。
**Instead:** registry → generated manifest/npm/snapshot，CI `--check`。

### Anti-Pattern 5: Generic `perform_action`

**What:** 一个工具接受自由字符串 action 与任意 payload。
**Why bad:** 模型难以正确选参，annotations 无法表达风险，授权容易遗漏，schema 不可演进。
**Instead:** 按资源和风险边界定义 typed tools；底层仍可共享 command dispatcher。

### Anti-Pattern 6: Start Repo Plan or Merge Out of Band

**What:** MCP 直接调用 `blueprint_repo_plan` 或 `blueprint_merge` handler。
**Why bad:** 绕过 gate、stage transition、lease、artifact versioning 和 recovery。
**Instead:** gate action / stage rerun → ProcessEngine。

### Anti-Pattern 7: Treat Observability as Transactional

**What:** Ledger、metric 或 log 写失败导致 approve/start 失败。
**Why bad:** 违反“永不反噬业务”，重试可能重复高影响动作。
**Instead:** business transaction 先以 canonical service 保证原子性；观测 best-effort。

## Phase Build Order

### Phase 1 — Contract Foundation

- 建 `McpToolRegistry`、request/response serializer 元数据与 generator。
- 先把现有工具导入 registry，生成与当前 snapshot/npm 等价的产物。
- 加 `--check`、manifest hash、breaking diff 测试。
- **退出条件：** 不改变任一现有工具行为，手改 generated file 会被 CI 拒绝。

### Phase 2 — Shared Application Boundaries

- 提取 `BlueprintContextResolver`、`BlueprintAccessPolicy`。
- 提取 gate/review/stage query 与 command service。
- REST 改调新 seam；characterization tests 固定 HTTP status/response。
- **退出条件：** REST 全绿，任何 adapter 都不 import `delivery.api.*` 私有 helper。

### Phase 3 — Operation Model and Idempotency

- 建薄 `PublicMcpOperation` 与 scoped unique key/request hash。
- 实现 start/get/list projection 和 safe error taxonomy。
- 复用 process_runtime、drive lease 与 durable recovery。
- **退出条件：** 超时重试不重复 session/artifact/repo task；跨用户 key 不冲突也不串数据。

### Phase 4 — Read-Only Full-Chain MCP

- 暴露 operation、blueprint、repo-plan、merge/review、events 查询。
- npm 全部由 manifest 生成；分页和 poll hints 定型。
- **退出条件：** 从 start 到 `input_required` 的每个阶段都能只靠 MCP 观察，不需 REST。

### Phase 5 — Repo Gate and Clarification HITL

- 暴露 repository snapshot/actions/confirm 与 clarification answer。
- 所有 mutation 加 revision/CAS、action idempotency、fail-closed scope。
- **退出条件：** 仅 MCP 可解除 repo confirmation 和 clarification pause，并可靠 resume。

### Phase 6 — Review, Rerun, and Handoff

- 暴露 resolve/dismiss/approve/reject、repo-plan/merge stage rerun。
- approve 沿用 version/hash handoff；旧 `repository_tasks` 兼容映射不复制。
- **退出条件：** 仅 MCP 可从 pending review 推到 confirmed handoff，陈旧决策稳定拒绝。

### Phase 7 — Protocol Tasks and Transport Evolution（可选）

- 在 SDK/client compatibility matrix 通过后增加 task-augmented calls。
- 映射到同一 operation service；显式 get tool 保留。
- 若需要远程公共 MCP，再增加 Streamable HTTP adapter，不改 application service。

**顺序理由：** schema source 必须先稳定，才能安全增加工具；共享 service 必须先于第二 transport；
operation 必须先于任何长任务 mutation；read-only 先验证 scope/projection，再开放 HITL 写动作；
approve/rerun 风险最高最后开放。MCP Tasks 是协议增强，不应阻塞核心全链路。

## Compatibility Constraints

1. 现有 Django `/api/mcp/tools/<name>/` URL、旧工具名、response keys 保持；新增字段仅 optional。
2. `create_work_item_technical_plan` 继续输出 legacy `repository_tasks`、markdown 和
   `technical_plan_id`；canonical blueprint 字段 additive。
3. `McpWorkItemTechnicalPlan` 暂保兼容，不把它升级为所有 operation 的事实源；新 operation
   可引用它。
4. `TOOL_SCHEMA_SNAPSHOT` 在迁移期保留 import API，但改为生成物。
5. npm 静态白名单仍 fail-closed；未知工具不做通配透传。
6. task 容器 submit MCP 与 public MCP namespace/credentials 隔离，不向外暴露内部 capture tools。
7. 旧客户端不支持 MCP Tasks 时仍可通过 explicit operation tools 完成全流程。
8. 任何 response enum 扩展按开放集处理；客户端不得 exhaustive crash。
9. 数据库迁移先部署兼容读写，再发布 npm；server 应接受旧 npm，npm 不应假定新 server。
10. 观测字段 additive 且 best-effort；不得把 Ledger 可用性变成业务 SLA。

## Scalability Considerations

| Concern | 当前规模 | 多副本 / 10K operations | 更大规模 |
|---------|----------|-------------------------|----------|
| polling | `poll_after_ms` 2–5s | ETag/`updated_at`、指数退避、cursor events | Streamable HTTP progress / queue fanout |
| operation projection | 关联查询可接受 | select-related + repo task aggregate；按 actor/project 索引 | 物化只读摘要，但 canonical recheck |
| duplicate drivers | DB drive lease 已覆盖 | 继续 CAS lease + durable idempotency | 分区 worker，不引入内存锁 |
| event volume | append-only PG | cursor pagination、payload allowlist、保留策略 | 冷归档，业务状态不依赖事件 |
| contract size | 单 manifest | tool pagination/分组，生成时 hash | 版本化 manifest，不动态拼 schema |

## Sources

### Repository Evidence（HIGH）

- `.planning/PROJECT.md`：v0.26.0 scope、requirements、quality gates。
- `server/mcp_tools/views.py`：`McpToolView._begin/_validate/_record` 与现有 transport pattern。
- `server/mcp_tools/serializers.py`：`TOOL_SCHEMA_SNAPSHOT` 当前 canonical snapshot。
- `server/mcp_tools/urls.py`、`mcp/src/tools.ts`、`mcp/src/server.ts`：当前 URL/静态 npm
  whitelist/proxy 三处契约。
- `server/mcp_tools/orchestration_delegate.py`、`technical_plan_service.py`：MCP 已委托
  `process_runtime`，以及 canonical blueprint → legacy handoff 的唯一映射。
- `server/services/process_runtime/engine.py`、`entrypoint.py`、`blueprint_resume.py`：
  stage graph、持久化 resume、lease/recovery。
- `server/services/process_runtime/blueprint_repo_plan.py`、`blueprint_merge.py`、
  `blueprint_stage_rerun.py`：repo wave、merge 与合法重跑边界。
- `server/delivery/api/blueprint_gate_views.py`、`blueprint_review_views.py`、
  `blueprint_stage_views.py`：现有 REST-only HITL 和私有 helper 跨 view 耦合。
- `server/delivery/services/blueprint_lifecycle_service.py`、
  `blueprint_review_action.py`：canonical writer。
- `server/delivery/models/convergence_session.py`、
  `convergence_session_event.py`、`research_task.py`、`artifact.py`、
  `blueprint_thread.py`：状态和事件事实源。
- `server/durable/service.py`、`tasks.py`、`tasks_impl.py`、`handlers.py`：durable 抽象和
  blueprint resume handler。
- `server/contracts/graph-query.v1.json`、
  `server/services/code_graph/query_manifest.py`：现有 canonical manifest + stable hash 模式。
- `task/core/agent_submit_mcp.py`：容器内 submit MCP 的 schema validation/capture 边界。

### Protocol Sources

- [MCP Tools specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
  — input/output schema、tool annotations、`execution.taskSupport`（HIGH，官方）。
- [MCP Tasks specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
  — capability negotiation、`tasks/get/result/cancel`、task-augmented tool calls（HIGH，官方）。
- [MCP Authorization specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
  — OAuth-based HTTP transport authorization；不替代 Friday object scope（HIGH，官方）。
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
  — MCP tool schema dialect 基础（HIGH，官方）。

## Open Questions for Phase Planning

1. v0.26.0 是否只支持现有 stdio npm proxy，还是同时要求远程 Streamable HTTP；这会影响 OAuth
   工作量，但不改变 application boundaries。
2. “cancel”对 `technical_blueprint` 各 stage 的业务语义尚未定义；未定义前只提供 retry/rerun，
   不暴露伪取消。
3. project 的 action-level RBAC 当前主要是 membership；approve/reject 是否需要新角色权限，
   应在 Phase 2 固定 policy。
4. gate snapshot 的 revision/hash 当前是否已有稳定字段需在实现前确认；若无，应由 command
   service 生成 deterministic hash，而不是让 MCP adapter 自算。
5. MCP Tasks 的实际客户端支持矩阵需要在 Phase 7 以当前 SDK 和 Cursor/Claude Code 做集成测试。

---
*Architecture research for Friday AI v0.26.0 MCP full-chain integration.*
