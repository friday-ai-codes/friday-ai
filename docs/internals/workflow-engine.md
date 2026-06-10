---
title: 工作流引擎
---

# 工作流引擎

工作流引擎负责把前端流程编辑器里画出的 DAG 变成可调度、可观测、可调试的执行过程。代码位于 `server/workflows/`。

## 总体结构

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| DAG 模型 | `engine/dag.py` | 节点 / 边的拓扑结构与校验 |
| 调度器 | `engine/scheduler.py` | 拓扑调度、并发执行、重试、调试 / 暂停 |
| 节点基类 | `nodes/base.py` | 所有可执行节点的契约 |
| 注册中心 | `nodes/registry.py` | 自动发现并注册节点类型（单例） |
| 执行模型 | `models/execution.py` | `WorkflowExecution` / `NodeExecution` 持久化 |
| WS consumer | `consumers.py` | 把执行状态实时推送给前端 |

## 节点契约

每个节点是 `BaseNode` 的子类，声明四件事：

1. **元信息**：`node_type`、显示名、`NodeCategory`（`trigger` / `action` / `control` / `integration` / `ai`）；
2. **端口**：输入 / 输出 `NodePort` 列表，带 `PortType`（`string` / `number` / `object` / `array` / `file` / `any`）、必填性与 JSON Schema（描述 object/array 端口的具体字段结构）；
3. **配置**：节点配置项经 `jsonschema` 校验；
4. **执行**：实现异步执行方法，返回 `NodeResult`。

```python
@dataclass
class NodeResult:
    status: Literal["success", "failed", ...]
    outputs: dict      # 写入输出端口
    error: str | None  # 失败原因
    branch: str | None # 分支 handle（控制流节点选择走哪条出边）
```

关键约定：**节点失败以 `NodeResult(status="failed", error=...)` 返回，不向引擎外抛异常**。这样重试次数、错误处理策略可以作为 `NodeExecution` 的字段配置，而不是散落在 try/except 里。

`ExecutionContext` 负责把节点输入、上游输出与全局变量（`GlobalVariable`）传入节点，并标准化输出与分支 handle。

## 节点注册

`NodeRegistry` 是模块级单例，启动时遍历 `workflows/nodes/<category>/` 包，靠模块导入副作用完成注册，并合并前端 `node-definitions.json` 中的 UI schema（图标、颜色、表单布局）。

**新增节点只需要把 `BaseNode` 子类放进对应分类目录**，后端能力与前端编辑器条目会同时出现。

内置节点分类一览（详细配置见[工作流指南](/guide/workflows)）：

| 分类 | 目录 | 代表节点 |
| --- | --- | --- |
| 触发器 | `nodes/triggers/` | `feishu_event_trigger`、`manual_trigger`、`webhook_trigger` |
| AI | `nodes/ai/` | AI 技术方案、AI 编码指派器、`ai_code_review` |
| 控制流 | `nodes/control/` | 条件分支、等待飞书字段 |
| 动作 | `nodes/actions/` | 数据加工、通知 |
| Git | `nodes/git/` | 分支 / MR 操作 |
| 集成 | `nodes/integrations/` | `fetch_work_item`、`notify_feishu`、`fetch_group_chat`、`join_group_chat` |

## 调度模型

调度器按 DAG 拓扑推进：

- **线程隔离**：每次执行在后台线程中自建事件循环（`_run_in_thread`），daemon 线程不阻塞 ASGI 主循环；ORM 访问统一经 `sync_to_async` 桥接；
- **持久化先行**：调度前先落库 `WorkflowExecution` 与全部 `NodeExecution`，进程重启后可以从持久化状态恢复视图；
- **分支语义**：控制流节点通过 `NodeResult.branch` 选择出边，未命中的分支整条子图标记跳过；
- **等待类节点**：「等待飞书字段」等节点把执行挂起为等待事件状态，由飞书回调唤醒，支持超时（默认 7 天）；
- **调试与暂停**：调试会话保存在模块级 `_debug_sessions` 字典中（瞬态，不落库），支持单步、断点与变量查看。

## 实时状态推送

节点状态每次变更都会通过 channels 推送到前端（`FF_ENABLE_WORKFLOW_WEBSOCKET` 控制），前端 DAG 视图实时着色。WebSocket 不可用时前端回退轮询。

## 扩展：写一个自定义节点

```python
# server/workflows/nodes/actions/my_node.py
from workflows.nodes.base import BaseNode, NodeCategory, NodePort, NodeResult, PortType


class MyNode(BaseNode):
    node_type = "my_node"
    name = "我的节点"
    category = NodeCategory.ACTION

    inputs = [NodePort(name="text", label="输入文本", port_type=PortType.STRING)]
    outputs = [NodePort(name="result", label="结果", port_type=PortType.STRING)]

    async def execute(self, context) -> NodeResult:
        text = context.get_input("text")
        return NodeResult(status="success", outputs={"result": text.upper()})
```

放入目录后重启 server，节点即出现在流程编辑器中。如需自定义图标与表单布局，在 `web/.../node-definitions.json` 中补充对应 UI schema。

## 下一步

<LinkCards>
  <LinkCard icon="🧩" title="工作流指南" desc="全部 32 种节点的配置项与使用方式" link="/guide/workflows" />
  <LinkCard icon="🛰️" title="Runner 与 Task 执行器" desc="runner_dispatched 节点的执行链路" link="/internals/runner" />
</LinkCards>
