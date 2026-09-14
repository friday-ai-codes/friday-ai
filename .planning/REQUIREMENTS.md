# Requirements: v0.26.0 MCP 全链路开放与稳定性

**Defined:** 2026-09-14  
**Status:** Approved  
**Goal:** 让外部 Agent 仅通过公开 MCP 即可稳定完成技术蓝图全链，并具备可恢复、可诊断、
契约不漂移的保障。

## 契约与发布面

- [ ] **PUB-01**: 服务端 registry、HTTP URL、输入/输出 schema、annotations、npm stdio
  `tools/list` 必须由单一事实源生成并完全一致。
- [ ] **PUB-02**: 当前服务端 55 个工具必须全部可从 npm stdio 发现和调用，现缺 12 个工具
  不得继续仅存在于 HTTP 面。
- [ ] **PUB-03**: CI 必须在 `mcp/` 缺失或未 checkout 时失败而非 skip，并用 `--check`
  证明生成产物无漂移。
- [ ] **PUB-04**: 独立 compatibility baseline 必须识别删工具、删字段、新增 required、
  收窄 enum 等 breaking change。
- [ ] **PUB-05**: npm `SERVER_VERSION` 必须与 `package.json` 一致，doctor 能报告客户端与
  服务端 manifest hash、版本和差异。
- [ ] **PUB-06**: 公开工具成功响应提供 `outputSchema` 与机器可消费的
  `structuredContent`；错误使用稳定机器码而非依赖中文文本解析。

## 异步 Operation 与幂等

- [ ] **OPS-01**: 外部 Agent 可幂等发起 technical blueprint，并在秒级获得
  `operation_id/session_id/artifact_id/status/poll_after_ms/next_actions`，请求不等待调研或融合。
- [ ] **OPS-02**: `(actor, project, tool, idempotency_key)` 与 canonical request hash
  原子预留；同 key 同负载复用，同 key 异负载返回 409。
- [ ] **OPS-03**: 请求超时或连接断开后，调用方可用 operation 或同幂等键找回原任务，
  不重复创建 session、artifact、容器或外部副作用。
- [ ] **OPS-04**: 查询 operation 只投影 canonical 状态，不复制蓝图状态机，不暴露 durable
  job ID，也不因轮询隐式推进流程。
- [ ] **OPS-05**: mutation 成功与后台续驱结果分离表达为 `action_committed` 和
  `drive_pending`；续驱失败不得诱导重复提交已生效动作。

## 状态、产物与诊断

- [ ] **STAT-01**: MCP 总状态查询返回稳定状态、当前 stage、进度、等待原因、不可变版本坐标、
  retry 信息和服务端权威 `next_actions`。
- [ ] **STAT-02**: MCP 可查询逐仓 research/repo-plan 的角色、状态、attempt、degraded、
  safe error、产物引用和可重试范围。
- [ ] **STAT-03**: MCP 可查询每轮 merge 的 validation、coverage、gap、back target、
  attempt、artifact version/hash 和 retryable 状态。
- [ ] **STAT-04**: MCP 可查询 review findings、clarifications、orphaned threads、review
  round 与未决 blocker，且不暴露 CoT 或内部堆栈。
- [ ] **STAT-05**: 增量事件查询支持 `since_seq/max_seq/has_more`，事件仅含 allowlisted
  ID、计数、阶段和脱敏摘要。
- [ ] **STAT-06**: Runner 完成但 callback 丢失、durable resume 异常或 lease 恢复时，
  MCP 诊断能给出 `waiting_on/recovery_state/retryable` 与合法恢复动作。
- [ ] **STAT-07**: 关键列表或产物读取失败必须返回结构化 retryable error；不得用
  `200 + []` 伪装成功，合法空结果必须带 `completeness/empty_reason`。

## 规格澄清与仓库确认

- [ ] **GATE-01**: MCP 状态面公开可回答的规格澄清项；普通澄清可继续使用
  `answer_blueprint_clarification` 完成回灌。
- [ ] **GATE-02**: MCP 可读取完整仓库确认门快照，包括仓库、角色、职责、fitness、
  pending research、移除态、gate token 与 ready-to-lock。
- [ ] **GATE-03**: MCP 可按单仓执行 add、remove、reclassify、edit responsibility 和
  upgrade research，并返回新 gate token 与后续动作。
- [ ] **GATE-04**: MCP 可携带 expected gate version/hash 原子确认仓库集；快照陈旧返回
  409，成功后通过既有 resume 链异步进入 repo-plan。
- [ ] **GATE-05**: 未经仓库确认和最终确认的蓝图不得通过任何 MCP/REST/工作流路径进入编码、
  推分支或创建 MR。

## 分仓方案与融合控制

- [ ] **RPLAN-01**: MCP 可读取指定仓库的 canonical repo plan、delivery status、
  attempt、产物版本/hash、引用摘要与未决 thread。
- [ ] **RPLAN-02**: MCP 可按仓对 failed/stale/degraded/empty repo plan 做 CAS 定向重试；
  只增加目标仓 attempt，不改其他仓任务、产物或版本。
- [ ] **RPLAN-03**: 职责修改后重跑保留旧 attempt 与旧产物，不得原地覆盖审计历史。
- [ ] **MERGE-01**: MCP 可读取 immutable merge 产物及 validation/reconcile/coverage 报告。
- [ ] **MERGE-02**: MCP 可携带 expected attempt、artifact version 与 content hash
  重试可恢复的 merge；陈旧坐标返回 409且不创建版本。

## AI Review、终审与交接

- [ ] **REVIEW-01**: MCP 提供独立的 finding resolve 与 dismiss 动作，reason 必填，
  终态重放为 noop 且不覆盖首次 actor/reason。
- [ ] **REVIEW-02**: `answer_blueprint_clarification` 调用 AI finding 必须稳定返回
  `not_answerable`，不得成为绕过 finding 处置的后门。
- [ ] **REVIEW-03**: `approve_technical_blueprint` 与
  `request_technical_blueprint_changes` 必须在 npm stdio 可发现、可调用并有准确 annotations。
- [ ] **REVIEW-04**: 最终 approve 必须校验 technical plan、artifact、version、content hash
  四坐标及 blocker；陈旧版本或未决 blocker 返回 409且不得 pin handoff。
- [ ] **REVIEW-05**: request changes 支持 `review/merge/repos/full` 定向返工并返回实际
  归一 scope；repos 只 stale 指定仓，merge 不重跑 repo，review 只重审。
- [ ] **HAND-01**: confirmed handoff 对四坐标、confirmed 状态与非空 repository tasks
  fail-closed；成功内容与 Friday canonical version 一致。
- [ ] **HAND-02**: npm 以权限受限文件保存完整 handoff，只向模型返回路径、可复算 hash、
  task count 和确认坐标，并具备清理策略。

## 权限、安全与可观测

- [ ] **SEC-01**: 所有 MCP 读写从 artifact/session/thread canonical 关系推导项目范围；
  不信请求体自报归属，非成员与不存在返回同形 404。
- [ ] **SEC-02**: 每个新入口都有 caller started/completed/failed、`duration_ms`、component、
  actor 与 correlation IDs；内部高频步骤使用 sampling。
- [ ] **SEC-03**: 后台 resume/retry 显式传播并 re-bind `initiated_by_user_id`，系统行为标
  `system`；观测失败不得影响业务。
- [ ] **SEC-04**: 状态、错误、finding、澄清、产物摘要、上游异常与 Ledger 全部按既有规则
  脱敏，日志只记录 ID、计数、长度和 hash。
- [ ] **SEC-05**: 查询工具准确声明 read-only/idempotent；审批、退回、gate、retry 工具不得
  误标 query，也不得暴露内部凭证、job ID 或实现堆栈。
- [ ] **SEC-06**: MCP 轮询具备 `poll_after_ms` 和限流/退避语义，避免多客户端 busy-loop
  冲击数据库与 worker。

## 真实链路与发布

- [ ] **LIVE-01**: canary 必须经待发布或已发布 npm stdio 的真实 `tools/call` 完成，不得只
  curl Django HTTP 端点。
- [ ] **LIVE-02**: canary 使用真实已索引 Qdrant 仓与真实 runner/container callback，
  完成路由、调研、分仓方案、融合和 review。
- [ ] **LIVE-03**: canary 故意丢失一次 structured callback，并验证 reconciliation 收敛且
  不产生重复任务、版本或外部副作用。
- [ ] **LIVE-04**: canary 完成一次飞书 HITL 或受控真实凭证交互，并最终验证 handoff
  四坐标、文件 hash 与 repository task count。
- [ ] **LIVE-05**: 报告必须分开记录 `synthetic_passed` 与
  `live_passed/live_failed/live_unrun`；`live_unrun` 阻止宣称完整 MCP-only 已验证。
- [ ] **LIVE-06**: publish gate 必须验证 generated catalog、compatibility baseline、
  package/server version、doctor、secret scan 与安装命令中的 npm 版本钉扎。

## Future Requirements

- **FUTURE-01**: MCP Tasks、progress notifications 和 elicitation 映射到同一 operation
  service；显式 start+poll 始终保留为兼容基线。
- **FUTURE-02**: 为尚未产生外部副作用的 stage 定义业务 cancel 与补偿语义。
- **FUTURE-03**: 批量 finding 处置，但每条仍保留独立 reason 和结果。
- **FUTURE-04**: Streamable HTTP/OAuth remote MCP、跨租户配额与计费。
- **FUTURE-05**: 细粒度 PAT scopes 与仓库级 ACL 重构。

## Out of Scope

| 项目 | 原因 |
|------|------|
| 新增 Celery、Temporal、FastMCP、axios、zod 或第二套契约源 | 复用现有 Django、stdio、durable 与 serializer 栈 |
| 重写 `process_runtime`、Artifact 或 durable queue | 它们继续是 canonical 事实源 |
| 自动批准仓库集或最终蓝图 | 违反 HITL 与版本确认边界 |
| 万能 `manage_blueprint(action=...)` 工具 | 难以表达权限、annotations、幂等和 CAS |
| 查询时隐式推进流程 | 破坏 read-only/idempotent 语义 |
| 任意 block 改写、编码中自动 replan | 绕过 canonical rework 和人工保护 |
| 直接向外暴露容器 submit MCP 或 durable job ID | 内部协议与实现细节不得成为公共 API |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|

---
*Requirements defined: 2026-09-14*
