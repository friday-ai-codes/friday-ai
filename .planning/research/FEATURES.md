# Feature Research

**Domain:** 面向外部 Agent 的 MCP-only 技术蓝图编排控制面
**Researched:** 2026-09-14
**Confidence:** HIGH（现状与缺口来自 Friday 源码）；HIGH（MCP 长任务、结构化输出与错误语义来自官方规范）

## Feature Landscape

本里程碑的完成标准不是“内部已有蓝图、分仓方案和 REST 页面”，而是外部 Agent 在不调用
Friday Web/REST、不了解数据库模型、也不依赖人工代点页面的前提下，仅通过公开 MCP 完成：

`发起 → 轮询 → 规格澄清 → 仓库确认 → 逐仓方案 → 融合 → AI finding 处置 → 人类终审 → 确认交接`

当前服务端有 55 个 `McpToolView.tool_name`，npm `mcp/src/tools.ts` 只有 43 个。缺失的 12 个中，
与本目标直接相关的是 `approve_technical_blueprint` 和
`request_technical_blueprint_changes`。更大的缺口是：仓库确认门的八个 REST 动作、AI
review finding 的 `resolve`/`dismiss`、逐仓方案与融合的独立状态/产物/重试能力都没有公开
MCP 工具。内部 adapter、模型或 REST 存在不构成“公开能力”。

### Table Stakes（用户期望这些）

下列每项均应是可单独验收的原子能力。

| ID | Capability | Public contract / acceptance | Complexity |
|----|------------|------------------------------|------------|
| PUB-01 | 服务端、HTTP URL、snapshot、npm stdio 单一工具清单 | 四面工具名、输入 schema、输出 schema、annotations 完全相等；CI 枚举真实 `McpToolView.tool_name`，禁止手抄白名单 | MEDIUM |
| INIT-01 | MCP-only 幂等发起蓝图 | `start_technical_blueprint`（或收敛后的既有 create）接收 `context_id/project_id/assumptions_tier/idempotency_key`；立即返回 `operation_id/session_id/artifact_id/status/next_actions`，不等待长阶段完成 | MEDIUM |
| INIT-02 | 幂等键负载绑定 | 同 `actor + idempotency_key + canonical_request_hash` 重放返回同一 operation；同 key 不同负载回 `409 idempotency_key_conflict`；在途重放为 `reused/in_progress`，不再建会话/容器 | MEDIUM |
| STAT-01 | 蓝图总状态查询 | `get_technical_blueprint_status(operation_id 或 artifact_id)` 返回稳定枚举、当前 stage、stage 状态、版本坐标、进度计数、等待原因、`next_actions[]`、`retryable`、脱敏错误；纯 GET 语义，不隐式 advance | MEDIUM |
| STAT-02 | 逐仓任务状态查询 | 返回每仓 `repository_id/role/stage/status/attempt/subtask_id/delivery_status/started_at/updated_at/error_code/retryable`；区分 `pending/running/waiting_input/succeeded/failed/stale/degraded` | MEDIUM |
| STAT-03 | 融合状态查询 | 返回 `attempt/validation_status/coverage/min_coverage/gap_count/back_target/back_repository_id/unresolved_count/artifact_version_id`；不得把 `exhausted + 已落版本 + 待人审` 报成 failed | LOW |
| STAT-04 | 增量进度游标 | 查询接受 `since_seq`，返回单调 `events[]/max_seq/has_more`；事件仅含阶段、计数、ID 和脱敏摘要，不暴露 CoT | MEDIUM |
| SPEC-01 | 规格澄清闭环 | 状态返回可操作澄清项 `thread_id/kind/question/options/created_at`；`answer_blueprint_clarification` 要求真实用户答复，同请求返回 `reflow.status/version/conflicts` | 已有，需统一暴露 |
| GATE-01 | 仓库确认门快照 | MCP 查询公开 REST 快照的完整可决策字段：仓库、角色、职责、fitness、pending research、移除态、thread/version token、是否可锁定 | MEDIUM |
| GATE-02 | 仓库集原子变更 | 公开 `add/remove/reclassify/edit_responsibility/upgrade_research`；每次只改一仓，响应含 `requires_research/ready_to_lock/already_running` 与新 gate token | MEDIUM |
| GATE-03 | 仓库门确认 | `confirm_blueprint_repositories` 必带 `expected_gate_version`（或 snapshot hash）；并发变化回 409，成功锁定确切仓集并异步续驱 | MEDIUM |
| RPLAN-01 | 逐仓方案产物读取 | `get_blueprint_repo_plan(artifact_id, repository_id)` 返回 canonical `repo_plan`、`delivery_status`、产物版本/hash、引用摘要、未决 thread IDs；禁止仅返回顶层六段标题 | MEDIUM |
| RPLAN-02 | 单仓显式重试 | `retry_blueprint_repo_plan` 必带 `repository_id/expected_attempt/reason`，只允许 failed/stale/degraded/empty；返回新 attempt/job，不重跑已 ready 的其他仓 | HIGH |
| RPLAN-03 | 单仓职责修订后重跑 | 复用确认门 `edit_responsibility(rerun=true)` 或专用 retry，但必须保留前次产物与 attempt 链，不能原地覆盖 | MEDIUM |
| MERGE-01 | 融合产物读取 | 读取每轮 merge 的 validation report、reconcile counts、coverage gaps、back target、version/hash；正文从 immutable artifact version 读取 | MEDIUM |
| MERGE-02 | 显式重跑融合 | `retry_blueprint_merge` 仅在 retryable 状态受理，要求 `expected_artifact_version_id/content_hash/expected_attempt`；成功只建新轮次，不改旧版本 | HIGH |
| REVIEW-01 | AI review 快照 | MCP 返回 `findings`（含 `thread_id/severity/status/blocking/anchor/脱敏 finding 正文`）、clarifications、orphaned threads、review round、未决 blocker IDs | MEDIUM |
| REVIEW-02 | finding 采纳并标已修复 | `resolve_blueprint_finding(thread_id, reason, expected_status)`；reason 必填；已终态重放为 noop，不覆盖首次结论 | LOW |
| REVIEW-03 | finding 判误报 | `dismiss_blueprint_finding(thread_id, reason, expected_status)`；与 resolve 分工具/分动作，禁止走 clarification answer 后门 | LOW |
| REVIEW-04 | 最终通过 CAS | 公开 npm `approve_technical_blueprint`；必传 `technical_plan_id/artifact_id/artifact_version_id/content_hash`；blocker 或版本漂移回 409；成功钉住 approved 坐标 | 已有服务端，LOW |
| REVIEW-05 | 最终退回与定向返工 | 公开 npm `request_technical_blueprint_changes`；支持 `review/merge/repos/full`，repos 时指定仓；返回新版本、revision round、实际归一后的 rework scope | 已有服务端，LOW |
| HAND-01 | 已确认交接包 | `get_confirmed_blueprint_handoff` 逐项核验 plan/artifact/version/hash，返回 canonical content、confirmed markdown、结构化 repository tasks；任一漂移 409 | 已有，需对齐 |
| HAND-02 | 交接结果可确认落盘 | npm 客户端以资源/文件形式保存完整包，只向模型返回路径、hash、task count；响应明确 `confirmed=true` 和服务端校验坐标 | MEDIUM |
| RETRY-01 | 统一可重试错误模型 | 所有查询/动作错误包含 `error_code/retryable/retry_scope/retry_after_ms/current_state/expected_version`；确定性拒绝不得标 retryable | MEDIUM |
| AUTH-01 | 所有读写统一项目范围 | PAT 即用户；Project-bound 必须 ProjectMember；越权与不存在同形 404；不信请求体自报 project/artifact/thread 归属 | MEDIUM |
| AUTH-02 | 动作级权限声明 | 每个工具 annotations 准确标 `readOnlyHint/idempotentHint/openWorldHint/destructiveHint`；审批、退回、门动作不可误标 query | LOW |
| SEC-01 | 全输出脱敏 | 状态、错误、finding、澄清题、产物标题、上游异常均经统一脱敏；日志只记 ID/计数/机器码，绝不记正文 | MEDIUM |
| OUT-01 | 输入与输出 schema 都是公开契约 | npm 工具提供 `inputSchema`、`outputSchema`，成功返回匹配 `structuredContent`；业务错误是 Agent 可见的 `isError` 结果，不靠解析中文 | MEDIUM |

### 建议的最小公开工具族

工具应按用户动作分开，避免一个万能 `action` 工具隐藏权限与幂等语义。

| Tool | Kind | Required keys | Stable success keys |
|------|------|---------------|---------------------|
| `start_technical_blueprint` | mutation/job | `context_id`, `idempotency_key` | `operation_id`, `session_id`, `artifact_id`, `status`, `next_actions` |
| `get_technical_blueprint_status` | query | `artifact_id`, `since_seq?` | `status`, `stage`, `progress`, `repo_tasks`, `merge`, `review`, `next_actions`, `max_seq` |
| `get_blueprint_repository_gate` | query | `artifact_id` | `gate_version`, `repos`, `pending_research_repository_ids`, `ready_to_lock` |
| `update_blueprint_repository` | mutation | `artifact_id`, `action`, `repository_id`, `expected_gate_version` | `applied`, `gate_version`, `requires_research`, `next_actions` |
| `confirm_blueprint_repositories` | approval | `artifact_id`, `expected_gate_version` | `locked`, `locked_repo_count`, `auto_removed_repository_ids`, `resume_job_id` |
| `get_blueprint_repo_plan` | query | `artifact_id`, `repository_id` | `status`, `attempt`, `artifact`, `open_question_thread_ids` |
| `retry_blueprint_repo_plan` | mutation/job | `artifact_id`, `repository_id`, `expected_attempt`, `reason` | `accepted`, `attempt`, `job_id` |
| `get_blueprint_merge` | query | `artifact_id` | `validation_status`, `attempt`, `report`, `version`, `retryable` |
| `retry_blueprint_merge` | mutation/job | `artifact_id`, `expected_attempt`, `artifact_version_id`, `content_hash` | `accepted`, `attempt`, `job_id` |
| `get_blueprint_review` | query | `artifact_id` | `findings`, `clarifications`, `orphaned_threads`, `unresolved_blockers` |
| `resolve_blueprint_finding` | mutation | `artifact_id`, `thread_id`, `reason`, `expected_status` | `status`, `thread_id`, `resume_job_id` |
| `dismiss_blueprint_finding` | mutation | 同上 | 同上 |
| `approve_technical_blueprint` | approval | 四坐标 | `confirmed`, `version_no`, `content_hash`, `repository_task_count` |
| `request_technical_blueprint_changes` | rejection/job | `artifact_id`, `rework_scope`, `rework_repository_ids?` | `revision_round`, `rework_scope`, `reworked_repository_count`, `resume_job_id` |
| `get_confirmed_blueprint_handoff` | query | 四坐标 | `confirmed`, `canonical_content`, `markdown`, `repository_tasks` |

`answer_blueprint_clarification` 保留现名。`get_technical_blueprint` 可继续承担正文读取，但不应
兼任完整 control-plane status；当前响应没有 gate、逐仓 attempt/error、merge report、AI
findings 和 next action，无法支撑可靠 Agent 决策。

### Differentiators（竞争优势）

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| `next_actions[]` 由服务端状态机权威生成 | Agent 不必猜“下一步该调哪个工具” | MEDIUM | 每项含 `action/tool/reason/required_inputs`；权限不足时不推荐不可执行动作 |
| 单仓失败隔离与定向恢复 | 一个仓失败不让多仓蓝图全盘重跑 | HIGH | 复用 `RepoResearchTask.attempt`、`PartialPlan` 历史和现有定向 dispatch |
| 版本四坐标交接 | 人审看到、批准、编码消费的是同一不可变版本 | MEDIUM | `technical_plan_id + artifact_id + version_id + content_hash` 已有基础 |
| 分阶段证据可查 | 可解释仓库选择、API 波次、融合缺口与 finding | MEDIUM | 返回引用 ID/定位，不暴露私有推理链 |
| 恢复诊断可见 | 把 durable resume、runner callback、stalled recovery 的结果转成用户可行动状态 | HIGH | 不直接公开内部堆栈；公开 `waiting_on/last_transition/recovery_state` |
| MCP Tasks 协议渐进增强 | 支持新客户端的 task/progress，同时兼容旧客户端轮询 | HIGH | tool 声明 `execution.taskSupport`; 轮询仍是必备 fallback |

### Anti-Features（常被要求、往往有害）

| Anti-feature | Why Problematic | Alternative |
|--------------|-----------------|-------------|
| “服务端有 View 就算公开” | npm stdio 客户端看不到；当前 55 vs 43 已证明漂移 | 真实注册表生成/校验 HTTP、snapshot、npm 四面 |
| 一个 `manage_blueprint(action=...)` 万能工具 | schema、权限、幂等和 annotations 无法精确表达；Agent 易选错动作 | 查询、批准、退回、resolve、dismiss、retry 分离 |
| 查询工具隐式推进流程 | 轮询次数会改变业务结果，破坏 readOnly/idempotent 语义 | 查询纯读；动作返回 `resume_job_id`，后台续驱 |
| 固定 HTTP 超时内等待完整蓝图 | 超时后结果未知，客户端重试可能重复建蓝图/容器 | 立即返回 operation/task + 幂等键 + 轮询 |
| 自动批准仓库集或最终蓝图 | 绕过 HITL，选错仓和错误契约直接进入编码 | 服务端返回可执行 gate，必须记录真实 actor |
| 用 clarification answer 处置 review finding | `answered` 仍可能阻塞；还绕过 reason 与 resolve/dismiss 语义 | finding 专用 resolve/dismiss |
| 全局“重试蓝图” | 浪费容器、覆盖已成功产物、扩大副作用面 | 最小失败域 retry：repo / merge / resume |
| retry 原地覆盖旧产物 | 无法审计、无法证明 CAS、交接坐标失真 | attempt 链 + immutable artifact versions |
| 200 + 空列表表示依赖读取失败 | Agent 会把“读失败”解释成“没有待办”并错误推进 | 结构化 retryable error；关键清单读失败不得伪空 |
| 把内部异常原文返回 Agent | 可能泄漏 token、URL 凭证、正文与内部路径 | 稳定机器码 + 脱敏 detail + correlation/run ID |
| 仅靠推送，不提供轮询 | MCP 通知可选，客户端可能不实现或断线 | 查询工具/`tasks/get` 始终为事实源 |
| 暴露任意 block 改写给外部 Agent | 容易绕过“AI 不覆盖人工”和最终评审 | 退回 canonical rework；人工编辑仍留受控 UI/专门权限 |

## Feature Dependencies

```text
PUB-01 四面对齐
  └─> INIT-01 / STAT-01 / 所有新工具可被外部发现

INIT-01 幂等发起
  ├─> STAT-01 总状态
  └─> SPEC-01 -> GATE-01/02/03
                    └─> RPLAN-01/02/03
                              └─> MERGE-01/02
                                        └─> REVIEW-01/02/03
                                                  └─> REVIEW-04 或 REVIEW-05
                                                            └─> HAND-01/02

AUTH-01 + SEC-01 + OUT-01 + RETRY-01
  └─> 横切所有查询、动作、状态与交接工具

STAT-04 事件游标
  └─enhances─> MCP Tasks / progress notifications
  └─does-not-replace─> STAT-01 polling
```

### Dependency Notes

- **先对齐发现面，再补功能：** 否则服务端实现继续成为外部不可达能力。
- **状态先于 retry：** 没有机器可判的 `retryable/retry_scope/attempt`，Agent 无法安全决定重试。
- **仓库确认先于分仓方案：** `blueprint_repo_plan` 的权威输入就是确认门锁定集，不能让外部直接跳到 repo plan。
- **finding 处置先于最终 approve：** 当前事务守卫会拦 open/answered BLOCKER；没有 resolve/dismiss，MCP-only 会死锁。
- **approve 先于 handoff：** handoff 已按 confirmed 状态与四坐标 fail-closed，不能提供“预交接”绕路。
- **MCP Tasks 是增强而非首要前置：** 官方规范要求客户端仍应轮询，先建立 Friday 稳定 operation/status 契约，再映射 task。

## MVP Definition

### Launch With（v0.26.0）

- [ ] PUB-01：55 个服务端工具与 HTTP/snapshot/npm 同步；至少把现有 approve/reject 补进 npm。
- [ ] INIT-01/02 + STAT-01/02/03：幂等异步发起与完整诊断状态。
- [ ] GATE-01/02/03：仓库确认门全部决策可由 MCP 完成。
- [ ] RPLAN-01/02 + MERGE-01/02：逐仓与融合的读取、定向重试、CAS。
- [ ] REVIEW-01/02/03/04/05：finding 处置、最终通过、定向退回全部公开。
- [ ] HAND-01/02：确认版本的可校验交接包。
- [ ] AUTH-01/02 + SEC-01 + OUT-01 + RETRY-01：权限、脱敏、结构化结果和错误横切验收。

### Add After Validation（v0.26.x）

- [ ] MCP Tasks / progress notifications 原生映射；保留现有轮询工具。
- [ ] `since_seq` 活动流的分页/订阅优化与客户端断线续读。
- [ ] 操作取消能力，仅允许取消尚未产生外部副作用的 queued/running 子任务。
- [ ] 批量 finding 处置，但每条仍要求独立 reason 与独立结果。

### Future Consideration（v2+）

- [ ] 外部 Agent 任意 block 编辑；风险高，除非增加专门 role 与审计。
- [ ] 自动批准策略；仅可作为显式组织策略且默认关闭。
- [ ] 跨租户开放平台、配额与计费；本里程碑仍是自托管 PAT/RBAC。

## Feature Prioritization Matrix

| Capability group | User Value | Cost | Priority |
|------------------|------------|------|----------|
| 四面工具契约对齐 | HIGH | MEDIUM | P1 |
| 幂等发起 + 完整状态 | HIGH | MEDIUM | P1 |
| 仓库确认门 MCP | HIGH | MEDIUM | P1 |
| 分仓方案/融合查询与 retry | HIGH | HIGH | P1 |
| finding resolve/dismiss | HIGH | LOW | P1 |
| approve/reject npm 暴露 | HIGH | LOW | P1 |
| 四坐标 handoff | HIGH | MEDIUM | P1 |
| 输出 schema / structured errors | HIGH | MEDIUM | P1 |
| MCP Tasks 原生支持 | MEDIUM | HIGH | P2 |
| cancel / bulk actions | MEDIUM | MEDIUM | P2 |
| Agent 任意正文编辑 | LOW/负 | HIGH | 不做 |

## Atomic Contract Tests

1. **发现一致性：** 服务端真实 55 工具集合与 URL、snapshot、npm 集合相等；任一新增只改服务端而漏 npm 时 CI 必红。
2. **发起幂等：** 相同 actor/key/payload 并发 10 次只产生 1 session、1 artifact、每仓至多 1 active container。
3. **幂等冲突：** 同 key 改 `context_id/project_id` 返回 409，原 operation 不变。
4. **纯查询：** 连续调用 status 100 次，session/artifact/thread/task 行与版本号不变。
5. **范围隔离：** 非项目成员查询和动作均与随机不存在 artifact 返回同形 404。
6. **gate CAS：** A 读 gate v3，B 改仓到 v4，A 用 v3 confirm 必须 409 且未锁定。
7. **单仓 retry：** 三仓中一仓 failed，retry 后仅该仓 attempt +1，另两仓 task/partial/version 不变。
8. **merge CAS：** 旧 version/hash 或旧 attempt 重试融合返回 409，不创建新版本。
9. **finding 通道隔离：** clarification answer 调 finding 返回 `not_answerable` 且状态不变；resolve/dismiss reason 为空拒绝。
10. **approve 守卫：** 存在 open/answered BLOCKER 时 approve 409；全部处置后同四坐标成功。
11. **approve CAS：** get 后产生新版本，旧 version/hash approve 409；不得 pin handoff。
12. **退回范围：** `repos` 只 stale 指定仓；`merge` 不重跑 repo；`review` 只重审；响应回实际 scope。
13. **handoff 确认：** 未 confirmed、四坐标任一不匹配、零 repository tasks 均 409；成功包 hash 可复算一致。
14. **失败不伪空：** pending/finding/repo plan 列表读取异常返回 retryable error，绝不 200 + `[]`。
15. **脱敏：** 在错误、finding、澄清、仓级产物中注入 token/URL credential，所有 MCP 响应与调用记录均不出现明文。
16. **旧客户端兼容：** 不支持 MCP Tasks/notifications 的 npm 客户端仅靠 start + poll + actions 可走完整链。

## Sources

- Friday 源码（HIGH）：
  - `server/mcp_tools/views.py`、`serializers.py`、`urls.py`：55 个服务端工具、现有蓝图 get/answer/approve/reject/handoff。
  - `mcp/src/tools.ts`：43 个 npm 工具；缺 approve/reject，且无确认门/finding/分仓方案/融合控制面。
  - `server/delivery/api/blueprint_gate_views.py`：内部仓库确认门八端点及范围/CAS/续驱语义。
  - `server/delivery/api/blueprint_review_views.py`：内部 review 快照、finding resolve/dismiss、approve/reject。
  - `server/services/process_runtime/blueprint_repo_plan.py`：逐仓 `delivery_status`、attempt、单仓隔离、波次与定向重派。
  - `server/services/process_runtime/blueprint_merge.py`：merge 五态、覆盖率 retry/exhausted、版本与未决项。
  - `server/services/process_runtime/blueprint_resume.py`：durable resume、stalled recovery、runner 恢复与人审状态边界。
  - `server/mcp_tools/technical_plan_service.py`：幂等 reservation、四坐标 confirmed handoff。
- MCP 官方规范（HIGH）：
  - https://modelcontextprotocol.io/specification/2025-11-25/server/tools
  - https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks
  - https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress
  - https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation

---
*Feature research for: Friday AI v0.26.0 complete public MCP blueprint orchestration*
*Researched: 2026-09-14*
