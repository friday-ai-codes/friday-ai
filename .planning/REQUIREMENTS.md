# Requirements: Friday AI — v0.4.0 工作流系统契约重构

**Defined:** 2026-06-12
**Core Value:** 让团队"开箱即用、安全地"把需求自动变成代码；v0.4.0 收敛工作流系统的编辑态与运行态契约——保存即合法、模板开箱能跑、变量所选即所得、执行状态真实可见。

## v1 Requirements

### 变量引用链路（VAR）

- [x] **VAR-01**: 用户在自建流水线中通过变量选择器选择的上游节点输出引用（`{{nodes.<short_id>.<field>}}`），保存后执行时保证可解析——保存（bulk-update）时同步客户端 short_id 或服务端重写 config 中的节点引用，消除 short_id 漂移
- [x] **VAR-02**: 变量引用解析失败（节点 ID 不存在、字段不存在、未知前缀）时节点显式失败并给出可读错误（指明哪个引用、哪个节点），不再静默替换为空串或保留字面量
- [x] **VAR-03**: 前端所有产生变量引用的入口（变量选择器、端口复制、SmartInput）生成统一格式的引用（统一用 short_id），与后端解析器支持的语法完全一致
- [x] **VAR-04**: 变量解析支持嵌套字段路径（`{{nodes.x.data.name}}` 能取到 `output["data"]["name"]`），并有 `render_template`/`get_template_value` 的专项单元测试覆盖（错误 ID、未知前缀、UUID vs short_id、嵌套路径）

### 内置模板（TPL）

- [x] **TPL-01**: 用户从任一内置模板创建工作流后，不修改任何配置即可成功执行到业务预期结果（修正 `daily_summary` 引用不存在的 `output` 字段、`code_review_pipeline` 节点链路与 `ai_code_review` 实现不符等已知断裂）
- [x] **TPL-02**: 模板自动化校验测试覆盖：每个模板的节点 type 存在于 registry、config 必填字段齐全、`{{ }}` 变量引用的节点 ID 与字段在上游输出 schema 中存在、edge 的 source/target handle 与节点端口定义一致
- [x] **TPL-03**: 模板创建（loader）在实例化前执行与保存相同的图校验，非法模板拒绝创建并返回结构化错误

### 节点定义单一事实源（SSOT）

- [x] **SSOT-01**: 前端节点面板（palette）、配置表单 schema、默认 config 全部以后端 `GET /api/node-types/` 返回为准，删除前端硬编码 `NODE_REGISTRY` 漂移（含幽灵节点 `fetch_project_info` → `fetch_space_info`）
- [x] **SSOT-02**: 前端画布节点的输入/输出 Handle 按后端 NodePort 定义渲染（如 `ai_coding` 的 `plan`、`ai_code_review` 的 `coding_result`、审批节点的 `approved`/`rejected`），替换 `portConfig.ts` 硬编码
- [x] **SSOT-03**: 前后端节点定义一致性有自动化守护：CI 校验前端消费的节点 type/端口与后端 registry 一致（或前端定义完全由后端生成，无需对账）

### 保存校验（VAL）

- [x] **VAL-01**: 后端提供统一 `WorkflowGraphValidator`（DAG 环/入口/孤立节点、edge 节点归属与 handle 合法性、节点 config schema、变量引用可解析性），bulk-update、单节点/边 CRUD、导入、模板创建共用同一校验
- [x] **VAL-02**: 保存非法工作流（含新建节点 config 不合 schema）返回结构化错误（节点 id + 字段路径 + 原因），不再"能保存、一执行就失败"
- [x] **VAL-03**: 前端保存前可调用 dry-run 校验接口，IssuesPanel 展示真实校验警告/错误（当前 `useWorkflowValidationStore` 无任何调用方，面板永不出现）

### 执行引擎（ENG）

- [x] **ENG-01**: 修复 `waiting_event` 与完成判定的状态机不一致：存在等待事件节点时执行不得被误判为 completed；挂起（suspended）状态对前端真实可见
- [x] **ENG-02**: 调度主循环与回调续跑路径行为一致：均按节点结果的 `next_handle` 与边的 `source_handle` 路由条件分支，未选中分支正确 skipped
- [x] **ENG-03**: 执行上下文注入 `trigger_data`，`{{trigger.*}}` 引用在所有触发方式下可解析
- [x] **ENG-04**: DAG 死锁（有 pending 但无 ready 且无等待节点）明确转 failed 并附诊断信息（哪些节点在等哪些依赖），不留无限 running
- [x] **ENG-05**: 节点输入收集尊重 `target_handle` 语义（或明确移除该字段并统一文档/前端展示），消除"端口名存实亡"的双轨模型；引擎核心路径（调度、分支、死锁、等待）有自动化回归测试

### 触发模型（TRIG）

- [x] **TRIG-01**: 修复飞书触发同步字段断裂：画布 `feishu_event_trigger` 节点保存后 `WorkflowTrigger` 表正确生成（统一 `event_type`/`event_types` 字段），飞书事件能匹配到工作流
- [x] **TRIG-02**: `schedule` 触发类型不再是假功能：实现定时调度 handler（django-apscheduler 注册 → dispatch），或从模型/UI 中移除该选项
- [x] **TRIG-03**: 触发分发失败不再被静默吞掉：dispatch 异常记录到可查询的位置（执行记录或事件日志），用户能看到"触发了但没跑起来"的原因

### 执行可观测（OBS）

- [x] **OBS-01**: 执行详情页节点失败时清晰展示错误信息（error_message、失败的变量引用、重试情况），用户不再把"节点失败"误感知为"卡住"
- [x] **OBS-02**: 执行详情页 WebSocket 断线时自动降级 REST 轮询（与列表页一致），长时执行 UI 不冻结；执行进度以服务端权威值为准
- [x] **OBS-03**: 执行整体状态（running/suspended/waiting_approval/failed）在列表与详情页如实展示，前端状态枚举与后端 `ExecutionStatus` 对齐（清除前端引用的不存在状态值）

## v2 Requirements

### 工作流增强（WFE）

- **WFE-01**: 编辑器内"试运行单节点"（mock 上游输出调试单个节点配置）
- **WFE-02**: bulk-update 边改为 upsert（稳定 edge id），支持增量 diff 与审计
- **WFE-03**: `_debug_sessions` 调试会话迁出模块级 dict（Redis/DB），支持多 worker 部署
- **WFE-04**: 工作流版本快照与回滚

## Out of Scope

| Feature | Reason |
|---------|--------|
| 推倒重写执行引擎（DAG/Engine/BaseNode） | 骨架可用，问题在契约与校验前移；重写风险远大于收敛 |
| 更换 vue-flow / 前端编辑器框架 | 编辑器交互本身不是痛点，契约才是 |
| 新增工作流节点类型 | 本里程碑聚焦修复与重构，不扩功能面 |
| 多 worker 水平扩展执行引擎 | 线程模型重构是独立大工程，先把单实例语义修对（WFE-03 留 v2） |
| 工作流市场 / 模板分享 | 先让内置模板能跑，分享生态以后再说 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VAR-01 | Phase 17 | Complete |
| VAR-02 | Phase 17 | Complete |
| VAR-03 | Phase 17 | Complete |
| VAR-04 | Phase 17 | Complete |
| ENG-01 | Phase 18 | Complete |
| ENG-02 | Phase 18 | Complete |
| ENG-03 | Phase 18 | Complete |
| ENG-04 | Phase 18 | Complete |
| ENG-05 | Phase 18 | Complete |
| SSOT-01 | Phase 19 | Complete |
| SSOT-02 | Phase 19 | Complete |
| SSOT-03 | Phase 19 | Complete |
| VAL-01 | Phase 20 | Complete |
| VAL-02 | Phase 20 | Complete |
| VAL-03 | Phase 20 | Complete |
| TPL-01 | Phase 20 | Complete |
| TPL-02 | Phase 20 | Complete |
| TPL-03 | Phase 20 | Complete |
| TRIG-01 | Phase 21 | Complete |
| TRIG-02 | Phase 21 | Complete |
| TRIG-03 | Phase 21 | Complete |
| OBS-01 | Phase 21 | Complete |
| OBS-02 | Phase 21 | Complete |
| OBS-03 | Phase 21 | Complete |

**Coverage:** 24/24 v1 requirements mapped（无孤儿、无重复）

---
*Requirements defined: 2026-06-12*
