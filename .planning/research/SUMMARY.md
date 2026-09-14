# Project Research Summary

**Project:** Friday AI v0.26.0 MCP 全链路开放与稳定性
**Domain:** 外部 Agent 的 MCP-only 技术蓝图编排控制面（brownfield）
**Researched:** 2026-09-14
**Confidence:** HIGH（仓内能力、依赖与缺口）；MEDIUM（MCP Tasks、宿主通知兼容性）

## Executive Summary

Friday AI 已有完整的 `blueprint/v1` 领域流水线：规格澄清、仓库路由与确认、逐仓调研和方案、融合、AI review、人类终审、确认交接均有 canonical 状态与服务。v0.26.0 的任务不是重写蓝图引擎，而是把现有能力整理成一个安全、可恢复、外部 Agent 仅靠公开 MCP 就能完成的控制面。专家做法是 ports-and-adapters：REST 与 MCP 共享 application command/query service，`process_runtime`、`BlueprintLifecycleService`、`ArtifactService`、`DurableTaskService` 继续作为事实源，MCP 只负责认证、授权、契约校验、状态投影和错误映射。

实时源码确认了研究中的核心漂移：`server/mcp_tools/views.py` 当前有 **55** 个 `tool_name`，`mcp/src/tools.ts` 仅声明 **43** 个，且 npm 测试仍写死 `toHaveLength(43)`。缺失的 12 个是 `graph_query`、`impact_analysis`、`detect_changes`、`list_processes`、`get_process`、`rename_preview`、`trace_call_path`、`search_session_knowledge`、`get_session_capture`、`report_session_knowledge`、`approve_technical_blueprint`、`request_technical_blueprint_changes`。因此必须先建立服务端 canonical registry 和生成 catalog，再开放新工具；否则每增加一个 MCP 能力都会扩大漂移。

推荐采用“显式 operation + accepted/poll”作为稳定基线：长任务秒级返回 `operation_id`、canonical resource 坐标和 `poll_after_ms`，状态由现有 session/artifact/thread/repo-task/durable 数据实时投影；所有 mutation 使用作用域幂等键与 CAS。MCP Tasks、progress notification、elicitation 和远程 Streamable HTTP 只作为后续增强，不作为 v0.26.0 完整链验收前提。最大风险是固定 120 秒超时制造未知结果、HITL 能力只存在于 REST、重复续驱/回调丢失、权限预言机、空载荷伪成功及合成测试替代真实依赖；应以结构化错误、定向恢复、同源权限、语义完整性门禁和真实 canary 关闭这些风险。

## Key Findings

### Recommended Stack

详见 [STACK.md](./STACK.md)。本里程碑**不新增任何 Python 或 npm 运行时依赖**，只复用现有锁定栈并增加仓内生成器、服务与测试：

**Core technologies:**
- Django + adrf：保留 `POST /api/mcp/tools/{name}/` PAT 边界；新 catalog、query、command adapter 遵循 async ORM 约束。
- `@friday-ai-codes/mcp` + `@modelcontextprotocol/sdk@1.29.0`：继续使用 stdio、`ListTools`/`CallTool` 与 Node 内置 `fetch`；不升级 SDK 2.x。
- Python `mcp==1.26.0`（约束 `<2`）：继续服务容器内 `claude-agent-sdk==0.1.58`，不改造成第二套 public FastMCP。
- `process_runtime` + `DurableTaskService` + Procrastinate 3.8.1：驱动长任务、resume、recovery 与 at-least-once 执行；业务不直接依赖 Procrastinate。
- DRF serializers + `jsonschema==4.26.0`：由服务端 registry 生成 input/output schema、manifest、npm catalog 和兼容 snapshot，不引入 OpenAPI generator 或 zod 契约真源。
- PAT + `AccessTokenAuthentication`：MCP 调用者就是 token owner，项目范围从 canonical relation 推导并 fail-closed。
- `structlog`、Interaction Ledger 与既有指标设施：所有新增入口按 caller 记录生命周期，内部高频步骤按 sampling；观测始终 best-effort。

**版本硬约束：**
- `@modelcontextprotocol/sdk` 保持 1.x；MCP Tasks 兼容性需真实宿主验证后再声明 capability。
- Python `mcp` 保持 `>=1.25.0,<2`；不得破坏 `claude-agent-sdk` 的 decorator API。
- npm `SERVER_VERSION` 必须来自或等于 `package.json`；当前 `0.2.0` vs package `0.6.0` 是发布阻断项。
- 生产继续使用 Postgres durable；SQLite 仅 dev fallback，诊断响应必须显示 backend/recovery 能力差异。

### Expected Features

详见 [FEATURES.md](./FEATURES.md)。

**Must have（v0.26.0 table stakes）：**
- 服务端 registry、Django URL、input/output schema、annotations、bundled npm catalog 与实际 stdio `tools/list` 完全一致。
- MCP-only 幂等发起：立即返回 operation/session/artifact 坐标，不在请求内等待调研或融合。
- 权威总状态与逐仓、融合、review、事件游标查询；查询纯读，返回 `next_actions`、`poll_after_ms` 和结构化 retry 信息。
- 规格澄清、仓库 gate 快照与 add/remove/reclassify/edit/upgrade/confirm 全部可由 MCP 完成。
- 逐仓方案和融合产物可读；失败域可按单仓或 merge attempt 定向重试，旧产物与 attempt 历史不可覆盖。
- AI finding 独立 `resolve`/`dismiss`；禁止复用 clarification answer。
- 最终 approve/request-changes 在 npm stdio 可发现，并携带 artifact/version/hash CAS 坐标。
- confirmed handoff 对四坐标 fail-closed；完整 payload 落本地权限受限文件，模型只接收路径、hash 和任务摘要。
- 所有 read/write 统一项目范围、动作权限、脱敏、annotations、`structuredContent` 和机器可判错误。
- 真实 canary 经 stdio 走完整链，并覆盖 Qdrant、runner、容器、丢 callback、飞书交互和 handoff hash。

**Should have（差异化能力）：**
- 服务端权威生成 `next_actions[]`，每项给出 tool、原因和 required inputs，外部 Agent 不猜状态机。
- 单仓失败隔离、定向恢复、attempt 链和 immutable artifact version。
- 阶段证据与恢复诊断可见，但不暴露 CoT、内部堆栈或 durable implementation IDs。
- manifest hash、client/server catalog diff 和版本钉扎 doctor，避免 npm/server 交叉版本静默失败。
- `since_seq` 增量事件流，为未来 MCP progress/tasks 提供同源投影。

**Defer（v0.26.x / v2+）：**
- MCP Tasks、progress notifications 和 elicitation 原生映射：只能增强，不能替代 explicit operation/poll。
- cancel：在各 stage 的业务取消语义和外部副作用补偿未定义前不开放。
- Streamable HTTP/OAuth remote MCP、跨租户开放平台、配额与计费。
- 批量 finding、自动批准、任意 block 改写和编码中自动 replan。
- 细粒度 PAT scopes、仓库级 ACL 重构、全局脱敏债清理；若不在本里程碑实现，必须如实记录威胁边界。

### Architecture Approach

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。采用端口适配与 CQRS 风格的 application boundary：MCP/REST adapter 只做 transport concern；command service 是唯一 writer；query/projection service 汇总 canonical 状态；public operation 仅保存 owner、scope、幂等 reservation 和 canonical locator，不复制蓝图状态机。任何 MCP 工具不得调用 REST view、直接写 ORM、直接启动 repo-plan/merge handler，或暴露 Procrastinate job ID。

**Major components:**
1. `McpToolRegistry` 与 contract generator — 服务端单一声明 name、request/response serializer、annotations、scope policy 和 async mode。
2. Generated catalog — 生成版本化 JSON manifest、npm definitions、URL registration projection 和迁移期 snapshot；发布包携带 manifest hash。
3. `BlueprintContextResolver` / `BlueprintAccessPolicy` — REST/MCP 共用 canonical 定位与 fail-closed 项目授权。
4. Gate/Review/Stage command services — 复用 lifecycle、review action 与 stage rerun，统一 CAS、幂等和合法状态迁移。
5. `BlueprintQueryService` — 只读汇总 gate、repo plan、merge、review、handoff 和安全诊断。
6. `PublicOperationService` — 作用域幂等 reservation、canonical locator、状态/事件/next-actions 投影。
7. `process_runtime` / `ArtifactService` / `DurableTaskService` — 保持唯一编排、版本与恢复事实源。

**契约单一事实源的明确取舍：**
- canonical source 是 Django 侧 declarative registry + serializers，而不是 npm `tools.ts` 或现有手写 snapshot。
- manifest、npm catalog、URL 名集和迁移期 `TOOL_SCHEMA_SNAPSHOT` 由 generator 产生。
- CI 仍保留一份独立、版本化 compatibility baseline 用于 breaking-change 分类；不能让测试从被测 registry 动态 import 后自证一致。
- npm 默认使用 bundled catalog，连接实例后可读取带 PAT 的 server catalog 做 hash/diff 诊断；未知工具仍 fail-closed，不做通配透传。

### Critical Pitfalls

详见 [PITFALLS.md](./PITFALLS.md)。

1. **55 vs 43 静态白名单漂移** — 先建立 registry→generated catalog，CI 缺 npm checkout 必须失败；禁止绝对计数冒充一致性。
2. **120 秒超时把 unknown outcome 当 failed** — mutation 秒级 accepted；abort 后用 operation/idempotency key 对账，不自动重放副作用。
3. **幂等与 drive 重入不足** — `(actor, project, tool, key)` + canonical request hash 原子预留；pending 重放返回同一 operation，参数漂移 409。
4. **回调丢失或 barrier 重复触发** — canonical 状态 + RunnerEvent 对账，callback 只加速；诊断与 recover 工具复用现有 reconciliation/lease。
5. **CAS 后动作成功、续驱失败被混为失败** — 响应区分 `action_committed` 与 `drive_pending`；query 能确认 gate/approve 是否已落库。
6. **HITL 闭集不完整** — repo confirmation、finding resolve/dismiss、approve/reject 缺一不可宣称 MCP-only；未 confirmed 蓝图禁止进入编码。
7. **范围预言机与凭证/正文泄漏** — canonical project membership fail-closed、无权限与不存在同形、错误和 Ledger 脱敏、handoff 不内联。
8. **空载荷伪成功与轮询风暴** — `schema_version/completeness/empty_reason`，关键读失败不返回空数组；`poll_after_ms`、429、query 无副作用。
9. **合成测试冒充真实链** — live canary 状态必须独立报告，skip 只能是 `live_unrun`，不能计为 passed。

## Complete MCP-Only Blueprint Chain

v0.26.0 的验收主链固定为：

```text
start_technical_blueprint
  → get_technical_blueprint_status / events
  → answer_blueprint_clarification（如有）
  → get/update/confirm blueprint repositories（CAS）
  → get/retry repo plans
  → get/retry merge
  → get review
  → resolve/dismiss findings
  → approve 或 request changes（CAS，按 scope 返工）
  → get_confirmed_blueprint_handoff（四坐标复核 + 文件 hash）
```

依赖关系：

```text
generated catalog
  → shared context/access/application services
  → operation + idempotent start/poll
  → read-only full-chain projection
  → repo gate/clarification commands
  → repo-plan/merge retry controls
  → finding/final-review/handoff commands
  → live canary and release pinning
```

任一 query 不得隐式 advance；任一 stage command 不得绕过 `process_runtime`；任一高影响 mutation 必须在 service 内再次做状态和版本 CAS。

## Implications for Roadmap

建议 7 个交付相位。安全、授权、脱敏、观测与兼容性不是末尾补丁，而是每相位退出门禁。

### Phase 1: 契约注册表与生成目录

**Rationale:** 当前 live source 已确认 server=55、npm=43；不先消除四面漂移，后续新增工具不可可靠发现。
**Delivers:** `McpToolRegistry`、serializer-derived input/output schema、版本化 manifest/hash、generated npm catalog、generated URL/snapshot projection、`--check`、breaking diff 分类、`SERVER_VERSION` 对齐和 doctor 基线。
**Addresses:** PUB-01、OUT-01、AUTH-02。
**Avoids:** 静态白名单漂移、子模块 skip 假绿、字段/annotations 漂移、客户端/实例版本谎言。

**Quality gates:**
- live registry 恰好枚举当前 55 个 server tools；generated npm `tools/list` 与之集合相等，12 个现缺工具全部补齐。
- npm 测试删除 `toHaveLength(43)`；对齐测试在 npm 目录缺失时 fail，不得 skip。
- input/output schema、annotations、route、manifest hash 全量对拍；生成命令 `--check` 后工作树零 diff。
- breaking 变更（删工具/字段、加 required、收窄 enum）必须被 compatibility baseline 拦截。
- npm `SERVER_VERSION == package.json.version`；doctor 能显示 client/server manifest diff。

### Phase 2: 共享应用服务与安全边界

**Rationale:** MCP 必须成为第二个 adapter，而不是第二套业务规则；先提取共享 seam 才能安全开放写动作。
**Delivers:** `BlueprintContextResolver`、`BlueprintAccessPolicy`、Gate/Review command services、`BlueprintQueryService`、DTO 与统一错误 taxonomy；REST 改用同一服务但保持现有 URL/响应兼容。
**Addresses:** AUTH-01、SEC-01、RETRY-01，以及所有后续工具的 canonical service 前置。
**Avoids:** MCP import REST 私有 helper、第四份权限逻辑、非法 ID 预言机、adapter 直接 ORM/状态迁移。

**Quality gates:**
- REST characterization tests 全绿；MCP/REST 对同一 command 产生相同 canonical 状态。
- 任何 adapter 不 import `delivery.api.*` 私有 helper；query service 无写入，command service 是唯一 writer。
- project 从 artifact/session/thread 关系推导；payload 自报 ID 不可信；非成员与不存在同形 404。
- 日志/错误中的 PAT、URL credential、数据库连接串和正文样本全部脱敏。

### Phase 3: Public Operation、幂等发起与轮询

**Rationale:** 长任务控制面是所有 MCP-only 阶段的公共底座，必须先解决 unknown outcome 和重复副作用。
**Delivers:** 薄 `PublicMcpOperation`、scoped idempotency reservation、`start_technical_blueprint`、get/list operation、稳定 status/phase/resources/error/retry/poll envelope、`since_seq` 事件游标、按工具类型拆分 timeout。
**Addresses:** INIT-01/02、STAT-01/04、RETRY-01。
**Avoids:** 同步 `adrive`、120 秒伪失败、重复 session/artifact/container、busy-loop。

**Quality gates:**
- 相同 actor/key/payload 并发 10 次只产生一个 operation/session/artifact；同 key 不同 payload 返回 409。
- start 在秒级返回 accepted/running/input_required；请求断开不取消 canonical job。
- 连续 poll 100 次不改变 session/artifact/thread/task/version；响应始终含 `poll_after_ms`。
- timeout 后同 key 查询/重放可找回原 operation，外部副作用计数仍为 1。
- operation status 从 canonical source 投影，不以 operation 行自建状态机；durable job ID 不外泄。

### Phase 4: 全链只读状态、产物与诊断

**Rationale:** Agent 在能安全行动或重试前，必须能无副作用地观察每个阶段和失败域。
**Delivers:** technical blueprint status、repository gate、repo task/plan、merge、review、events、callback/Runner/recovery snapshot、completeness 与 next-actions 查询；大产物使用受限本地文件交付。
**Addresses:** STAT-02/03、GATE-01、RPLAN-01、MERGE-01、REVIEW-01、HAND-02 的读半边。
**Avoids:** 200+空数组伪成功、整体状态被单仓失败误标 failed、内部堆栈/CoT 泄漏、poll 触发续驱。

**Quality gates:**
- 从 start 到每个 `input_required`/terminal 状态，外部 Agent 仅靠 MCP 可判定当前 phase、等待原因和下一动作。
- confirmed/completed fixture 的 repo task 数与锁定仓集一致；空主载荷必须有 `completeness` 与 `empty_reason`。
- Runner 已完成但 callback 丢失时诊断明确给出 `waiting_on/recovery_state/retryable`。
- query 失败返回结构化 retryable error，绝不伪装为 `[]`；事件 payload 只含 allowlisted ID/计数/脱敏摘要。

### Phase 5: 仓库确认与规格 HITL

**Rationale:** repo gate 是逐仓方案的权威输入，必须先于 repo-plan/merge 控制开放。
**Delivers:** clarification answer、repository gate add/remove/reclassify/edit-responsibility/upgrade-research/confirm；每次 mutation 使用 gate revision/hash CAS 与 action idempotency，成功后通过既有 resume helper 续驱。
**Addresses:** SPEC-01、GATE-02/03。
**Avoids:** 跳过硬确认门、重复确认空仓、确认成功却因续驱失败返回 tool error、自动批准仓集。

**Quality gates:**
- A 读 gate v3、B 改至 v4，A 用 v3 confirm 必须 409 且未锁定。
- `action_committed` 与 `drive_pending` 分开；续驱失败不回滚已提交决定，也不诱导重复确认。
- 仅 MCP 可完成所有 gate 修改并进入 repo-plan；未确认蓝图进入编码/MR 的所有路径零写入。
- clarification 只接受可回答 thread；finding 调此工具稳定返回 `not_answerable`。

### Phase 6: 分仓、融合、评审与确认交接

**Rationale:** 状态与 gate 稳定后再开放高成本 retry 和高影响最终决策，确保最小失败域与不可变版本坐标。
**Delivers:** `retry_blueprint_repo_plan`、`retry_blueprint_merge`、resolve/dismiss finding、approve/request-changes、confirmed handoff；旧 `repository_tasks` 只经现有 canonical mapping 生成。
**Addresses:** RPLAN-02/03、MERGE-02、REVIEW-02/03/04/05、HAND-01/02。
**Avoids:** 全局重跑、旧产物覆盖、finding 走 answer 后门、陈旧 approve、未确认 handoff。

**Quality gates:**
- 三仓一仓失败时只该仓 attempt +1；其他仓 task/partial/version 不变。
- 旧 merge attempt/version/hash 重试返回 409，不创建版本；新轮次保留完整历史。
- resolve/dismiss reason 必填，终态重放 noop 且不覆盖首次 actor/reason。
- 有 open/answered BLOCKER 时 approve 409；全部处置后 exact artifact/version/hash 成功。
- `repos` 返工只 stale 指定仓，`merge` 不重跑 repo，`review` 只重审；响应返回实际归一 scope。
- handoff 对 technical plan/artifact/version/hash 任一漂移、未 confirmed 或零 tasks 均 fail-closed；成功文件 hash 可复算。

### Phase 7: 恢复、安全收口与真实发布 Canary

**Rationale:** 完整链只有在真实依赖、callback loss 和发布包/实例组合下验证后才成立；synthetic green 不能替代 live evidence。
**Delivers:** 显式 recover/retry action、poll rate limits、runner callback reconciliation、live canary harness、双栏报告、版本钉扎安装与 publish guard。
**Addresses:** 恢复诊断、SEC-01、真实 canary、发布兼容。
**Avoids:** callback 僵尸、电平 barrier 重驱、轮询风暴、secret 泄漏、`npx -y` 拉错代、live skip 冒充 passed。

**Quality gates:**
- canary 必须经已发布/待发布 stdio 包 `CallTool`，不能只 curl Django endpoint。
- 使用真实 Qdrant 已知索引仓，检索结果非空；真实 runner 启动容器并完成逐仓方案。
- 故意丢弃一次 structured callback，系统通过 RunnerEvent/reconciliation 收敛，且无重复产物。
- 完成一次真实或受控真实凭证的飞书 HITL 交互；最终 handoff 文件坐标、hash、task count 全部一致。
- 报告明确 `synthetic_passed` 与 `live_passed|live_failed|live_unrun`；`live_unrun` 阻断“完整 MCP-only 已验证”声明。
- publish job 重跑 catalog alignment、package/server version、doctor 和 secret scan；文档安装命令钉 npm 版本。

### Phase Ordering Rationale

- 契约生成必须先于功能扩张；否则 server/npm 漂移会在每个后续相位重复。
- 共享 application services 必须先于 MCP writer；否则 REST/MCP 会形成两个状态机和两套权限。
- operation/idempotency 必须先于任何长任务 mutation；否则 timeout/retry 会复制昂贵副作用。
- read-only projection 先于 HITL/retry，确保 Agent 基于机器可判状态行动。
- repository gate 先于 repo-plan，repo-plan 先于 merge，finding 处置先于 approve，approve 先于 handoff。
- 真实 canary 最后整链执行，但其 fixtures、开关与凭证计划应从 Phase 1 建档，不能到发布前才设计。

## Explicit Non-Goals

- 不新增 Python/npm 运行时依赖，不引入 Celery、Temporal、FastMCP、axios、zod 契约层或 OpenAPI generator。
- 不重写 `process_runtime`、`BlueprintLifecycleService`、Artifact 或 durable queue；不建立第二套蓝图/task 状态机。
- 不以 MCP Tasks、progress notification、elicitation 或 Streamable HTTP 作为 v0.26.0 完整链前提。
- 不开放任意蓝图 block 改写、自动批准、批量 finding、未定义的 cancel 或编码中自动 replan。
- 不把 public MCP operation 绑定到 durable job ID，不允许客户端直接 poll/cancel Procrastinate。
- 不改变容器内 submit MCP 的内部 namespace/credentials，也不向外暴露 capture tools。
- 不在本研究交付中修改生产代码；后续实现也不得顺手改动无关 provider、前端或用户现有 MCP worktree 修改。

## Cross-Cutting Quality Gates

以下门禁适用于每个实现相位，任一失败不得进入下一相位：

- **Canonical services:** REST/MCP 调用相同 command/query service；MCP adapter 无领域写入。
- **Async contract:** 长写请求 accepted+poll；无同步等待调研墙钟；查询严格纯读。
- **Idempotency/CAS:** 外部副作用有 reservation/request hash；HITL 和 retry 有 revision/version/hash guard。
- **Authorization:** PAT owner + canonical project membership；无法推导、关系歧义、越权一律 fail-closed。
- **Observability:** `started/completed/failed`、`category`、`component`、`duration_ms`、actor 和 correlation IDs 齐全；后台显式 `initiated_by_user_id`。
- **Redaction:** upstream error、finding、clarification、handoff summary 和 Ledger 入库分别走既有 redaction；日志只记 ID/计数/长度/hash。
- **Fail-soft observability:** log/metric/Ledger 失败不影响业务事务。
- **Semantic completeness:** terminal/confirmed 响应不得以空主载荷表示成功；schema/completeness/hash 可验证。
- **Compatibility:** 旧 URL/工具名/required keys 保持；新增字段 additive；server 先兼容部署，npm 后发布。
- **Evidence:** 每项能力同时有 service test、HTTP adapter test、stdio contract test；live 证据与 synthetic 证据分开。

### Research Flags

规划时建议做深入 research：
- **Phase 1:** registry 如何同时生成 URL、snapshot 与 TypeScript，且保留独立 compatibility baseline；需先冻结 manifest versioning/breaking rules。
- **Phase 3:** operation reservation 崩溃接管、active session 对账和现有 `McpWorkItemTechnicalPlan` 兼容关系。
- **Phase 4:** callback/Runner/durable/lease 的安全公共投影字段，避免泄漏内部实现又能指导恢复。
- **Phase 7:** 当前 Cursor、Claude Code 对 MCP Tasks/progress 的真实支持矩阵，以及 Qdrant/runner/飞书 canary 凭证和隔离策略。

可按既有模式直接规划：
- **Phase 2:** context/access/application service 提取，有现有 REST views、lifecycle 与 review action seam 可对照。
- **Phase 5:** gate commands 已有 REST 语义和 canonical lifecycle。
- **Phase 6:** finding、approve/reject、stage rerun 和 handoff 已有 writer seam；重点是 MCP adapter、CAS 与测试，不需重研领域模型。

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | 版本来自 lockfile 与现有集成点；结论是不新增依赖 |
| Features | HIGH | 缺口与完整链可由 live views、REST-only actions 和 npm catalog 直接核对 |
| Architecture | HIGH | canonical services、process runtime、artifact、durable seams 已存在 |
| Pitfalls | HIGH | 55/43、120s、skip、版本漂移和 callback recovery 均有仓内证据 |
| MCP Tasks / host support | MEDIUM | 规范与 SDK 存在，但 Cursor/Claude Code 实际协商和通知覆盖未完成 canary |
| Live external integrations | MEDIUM | Qdrant/runner/飞书历史测试债明确，需 Phase 7 真实环境验证 |

**Overall confidence:** HIGH

### Gaps to Address

- **工具命名冻结：** `get_technical_blueprint_status` 与 `get_blueprint_operation` 两套研究命名需在 requirements 阶段选定；推荐 operation 为通用 envelope、blueprint status 为领域详单，两者职责不重叠。
- **是否新增 operation model：** 可先评估现有 session/technical-plan reservation 是否能承载 owner/scope/key/hash；若无法表达跨工具稳定句柄，再建薄表，禁止复制状态。
- **Gate token：** 若现有 REST snapshot 无稳定 revision，应在 shared command/query service 生成 deterministic snapshot hash，不能在 MCP adapter 自算。
- **Action-level RBAC：** 当前主要是 project membership；approve/reject 是否需要更高角色必须在 Phase 2 冻结，未知时 fail-closed。
- **Rate limiting：** 现有 MCP 面缺专用 limiter；若不新增依赖，应复用 Django/cache/DB 设施并定义多副本一致性边界。
- **Handoff 文件策略：** 需要明确 TTL、清理、mode 0o600 和 skill 禁止回读全文；不应把完整 canonical content 再内联到模型。
- **Catalog runtime refresh：** bundled catalog 是可靠基线；server catalog 只用于 hash/diff 或安全刷新。不得声明 `tools.listChanged`，除非 stdio 通知与宿主重拉已被 canary 证明。
- **Published package truth:** worktree 对齐不等于 npm registry 已发布；Phase 7 必须验证 tarball/dist，不只验证源码。

## Sources

### Primary（HIGH confidence）
- [STACK.md](./STACK.md) — 锁定版本、零新增依赖、stdio/HTTP/durable 取舍。
- [FEATURES.md](./FEATURES.md) — MCP-only 原子能力、依赖、验收测试。
- [ARCHITECTURE.md](./ARCHITECTURE.md) — application boundaries、operation projection、生成契约与 phase order。
- [PITFALLS.md](./PITFALLS.md) — live 漂移、超时、回调、权限、发布与 canary 风险。
- [PROJECT.md](../PROJECT.md) — v0.26.0 目标、brownfield 基线与锁定约束。
- `server/mcp_tools/views.py` — 55 个 live `McpToolView.tool_name`。
- `server/mcp_tools/serializers.py`、`server/mcp_tools/urls.py` — 当前 snapshot 与 HTTP 面。
- `mcp/src/tools.ts`、`mcp/src/server.ts`、`mcp/tests/server.test.ts` — 43 个 npm 工具、120 秒 timeout、未知拒绝、版本与硬编码计数。
- `server/delivery/api/blueprint_*_views.py`、`server/delivery/services/` — REST-only gate/review 与 canonical writer seams。
- `server/services/process_runtime/`、`server/durable/` — stage graph、repo plan、merge、resume/recovery 与 at-least-once。
- MCP 官方 Tools、Tasks、Progress、Authorization 规范与 JSON Schema Draft 2020-12。

### Secondary（MEDIUM confidence）
- Cursor / Claude Code 对 MCP Tasks、progress、elicitation 的实际支持矩阵，待真实宿主 canary。
- npm registry 已发布 tarball 与当前 worktree 的一致性，待 publish phase 验证。

---
*Research completed: 2026-09-14*
*Ready for roadmap: yes*
