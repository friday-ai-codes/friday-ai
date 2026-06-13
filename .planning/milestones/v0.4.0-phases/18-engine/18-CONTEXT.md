# Phase 18: 执行引擎状态机修复 - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 推荐答案自动采纳，用户授权全程 smart 决策)

<domain>
## Phase Boundary

执行引擎的运行态语义真实可信——等待就是 suspended、分支按 handle 路由、触发数据可引用、死锁有诊断，不再出现"显示完成实际没跑完 / 永远 running"。覆盖 ENG-01（waiting_event 完成判定与挂起可见）、ENG-02（分支路由两路径一致 + skipped 标记）、ENG-03（trigger_data 注入）、ENG-04（死锁诊断转 failed）、ENG-05（target_handle 语义收敛 + 引擎回归测试）。

不在本阶段范围：保存校验（Phase 20）、前端状态枚举展示对齐（Phase 21，仅要求后端状态真实）、触发器表生成（Phase 21）。

</domain>

<decisions>
## Implementation Decisions

### waiting_event 完成判定（ENG-01）
- 调度主循环结束时若存在 waiting_event 节点：执行整体状态必须为 suspended，绝不判 completed
- suspended 状态通过现有 API 序列化与 WS hooks（execution_suspended 事件已存在）对前端真实可见；本阶段保证后端状态与事件正确，前端展示细节归 Phase 21
- 回调续跑（事件到达）后从挂起点恢复调度，恢复后语义与主循环一致

### 分支路由一致性（ENG-02）
- 以 `next_handle` × 边 `source_handle` 匹配为唯一路由语义；调度主循环与回调续跑两条路径共用同一路由函数（消除重复实现）
- 未选中分支的下游节点标记 skipped（级联：仅当节点所有入边都来自 skipped/未选中路径时才 skip；汇合节点只要有一条活路径就执行）
- skipped 是终态之一，参与"执行完成"判定

### trigger_data 注入（ENG-03）
- 任意触发方式（飞书事件、手动、API）创建 WorkflowExecution 时统一写入 trigger_data；手动/API 触发缺省注入 `{source: "manual"|"api", ...payload}`
- `{{trigger.*}}` 解析复用 Phase 17 定稿的 template_resolver 路径与失败语义（trigger 前缀字段缺失维持现状宽松语义——Phase 17 已锁定，不在本阶段扩大严格化）

### 死锁诊断（ENG-04）
- 判定条件：有 pending 节点但无 ready 节点且无 waiting/running 节点 → 执行明确转 failed
- 错误信息列出每个 pending 节点在等待哪些未满足的依赖（节点 short_id + 缺失的上游/handle），结构化写入 execution.error_message（与 Phase 17 错误结构风格一致）
- 不做自动恢复/破环，只诊断报错

### target_handle 语义（ENG-05）
- 决策：保留字段并实现其语义——节点输入收集时按入边 target_handle 将上游输出归集到对应输入端口名下（与 Phase 19 的 NodePort 定义对齐）；若实现成本超预期，回退方案为显式移除字段并统一文档/前端，但优先实现
- 调度、分支、死锁、等待四类引擎核心路径必须有自动化回归测试（pytest，server/tests/workflows/）

### Claude's Discretion
- 路由函数抽取位置（scheduler 内部函数 vs engine 子模块）
- skipped 级联算法实现细节
- 测试夹具组织方式

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/workflows/engine/scheduler.py` — 主调度循环；:953-969 next_handle 写入 `_next_handle`；:1411-1419 回调续跑路由（已按 handle 读取）；:655-660 amark_suspended 已存在；:822/:987 waiting_event 分支
- `server/workflows/models/execution.py` — ExecutionStatus 含 SUSPENDED/WAITING_EVENT；mark_suspended/mark_waiting_event 方法齐备
- Phase 17 产物：`server/workflows/engine/template_resolver.py`（trigger 前缀解析）、结构化 error_message 约定
- `server/workflows/engine/dag.py` — get_successors(node_id, handle) 已支持 handle 参数

### Established Patterns
- NodeResult(status=...) 不向引擎外抛异常；hooks.trigger 事件广播（WS）
- 引擎测试在 server/tests/workflows/（Phase 17 已扩至 368 个用例全绿）

### Integration Points
- Phase 21 消费：suspended 状态 API/WS 可见、死锁 failed 的 error_message、执行状态枚举
- Phase 20 消费：模板端到端执行依赖本阶段路由正确

</code_context>

<specifics>
## Specific Ideas

- 调度主循环与回调续跑"同一路由函数"是核心抓手——审计发现两路径行为漂移即源于重复实现
- 死锁诊断错误结构与 Phase 17 的 reference/reason/available 风格保持一致（中文一句话 + JSON 行）

</specifics>

<deferred>
## Deferred Ideas

- 执行级重试/断点续跑增强（非本阶段需求）
- 前端 suspended 态 UI 设计（Phase 21）

</deferred>

---

*Phase: 18-engine*
*Context gathered: 2026-06-12 via autonomous smart discuss*
