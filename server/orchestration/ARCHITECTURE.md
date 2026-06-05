# 编排层架构说明

## 图结构（Graph Topology）

编排层使用 LangGraph StateGraph 将 Web Chat 会话建模为显式 workflow：

```
START → planning → executing →(条件路由)→ finalizing → END
                       ↑          ↓
                       └── waiting ┘
```

### 节点

| 节点 | 职责 | initial implementation 行为 |
|------|------|----------------|
| `planning` | 接收用户消息，决定执行策略 | 设置 `phase="executing"` |
| `executing` | 执行 Agent 调用，产出结果或阻塞任务 | 根据 `blocking_tasks` 决定阶段转换 |
| `waiting` | 等待阻塞任务完成，调用 `interrupt()` 暂停 | 暂停 graph，resume 值传回结果 |
| `finalizing` | 收尾，标记 workflow 完成 | 设置 `phase="completed"` |

### 条件路由

`route_after_executing(state)` 检查 `state["blocking_tasks"]`：

- **非空** → 路由到 `waiting` 节点
- **空** → 路由到 `finalizing` 节点

### 边

- `START → planning`：固定入口
- `planning → executing`：固定边
- `executing → waiting | finalizing`：条件边
- `waiting → executing`：固定边（interrupt 恢复后回到执行节点继续推理）
- `finalizing → END`：固定出口

## 状态模型（State Model）

### WorkflowState — 编排语义真源

```python
class WorkflowState(TypedDict, total=False):
    run_id: str                          # 运行标识
    phase: str                           # RunPhase.value
    blocking_tasks: list[dict[str, Any]] # 阻塞任务列表
    user_message: str                    # 用户输入
    final_answer: str                    # 最终回复
```

**真源原则**：`WorkflowState` 存储在 LangGraph checkpoint 中，是编排语义的 authoritative source。其他存储（`OrchestrationRun` DB 模型、`Message`、SSE 推送）是此 state 的**投影**，而非反向依赖。

### RunPhase — 阶段枚举

`planning → executing → waiting → finalizing → completed`

`error` 为异常态，`route_after_executing` 中检测到 ERROR 时短路到 END。

### 节点返回值

所有节点函数返回 **部分 state 更新**（`dict`），LangGraph 自动合并到累积 state。节点不返回完整 state，只返回变更的字段。

## 中断/恢复协议（Interrupt / Resume Protocol）

### 暂停

1. `executing` 节点检测到 `blocking_tasks` 非空，设置 `phase="waiting"`
2. `route_after_executing` 路由到 `waiting` 节点
3. `waiting` 节点调用 `interrupt(blocking_tasks)`
4. LangGraph 自动保存 checkpoint，`ainvoke()` 返回当前 state
5. 外部系统可通过 `graph.aget_state(config)` 获取中断信息

### 恢复

1. 阻塞任务完成后，调用 `graph.astream(Command(resume=results), config)`
2. `waiting` 节点重新执行，`interrupt()` 返回 resume 值（`list[BlockingTaskResult]`）
3. 节点将结果存入 `blocking_results`，清空 `blocking_tasks`，设置 `phase="executing"`
4. 沿 `waiting → executing` 边回到执行节点，注入结果上下文生成最终回答
5. `executing` 无新 blocking_tasks 时路由到 `finalizing → END`

### 关键约定

- `thread_id`：标识一个会话的 graph 执行线程，用于定位 checkpoint
- `run_id`：标识一次编排运行，跨 interrupt/resume 保持不变
- **禁止在 `interrupt()` 前放置副作用** — resume 时节点从头重放，副作用会重复执行

## 持久化（Checkpointer）

- **生产环境**：`AsyncSqliteSaver`，独立 SQLite 文件（`data/orchestration_checkpoints.db`），避免与 Django 主库竞争写锁
- **测试环境**：`MemorySaver`，内存存储，测试隔离无需文件清理

## initial implementation 集成点

### initial implementation：ConversationService 迁入 Graph

- **对接点**：`planning_node` 和 `executing_node` 将接入 Agent SDK 调用
- `ConversationService.handle_message()` 的核心逻辑迁入 graph 节点
- `planning_node` 承担原有的意图分析与策略决定
- `executing_node` 承担原有的 Agent 调用与结果处理
- 主流程切换：Web Chat 入口从直接调用 `ConversationService` 改为 `graph.ainvoke()`

### initial implementation：并行阻塞任务与 Barrier

- **对接点**：`blocking_tasks` 列表支持多个并行任务
- `waiting` 节点的 `interrupt()` payload 包含完整任务列表
- 需要引入 barrier 机制：所有任务完成后才 resume
- `BlockingTaskDispatcher` 协议负责任务分发与结果收集
- resume 值从单个 `BlockingTaskResult` 扩展为结果列表

### initial implementation：Runtime、SSE 与前端状态对齐

- **对接点**：graph state 变更触发 SSE 推送
- `phase` 字段变更同步到前端 UI 状态
- `OrchestrationRun` DB 模型作为 graph state 的投影，服务于 API 查询
- 前端通过 SSE 接收实时 phase 转换，不再轮询
- `interrupt` 状态映射到前端 "等待中" UI，`resume` 触发 "继续执行" 反馈
