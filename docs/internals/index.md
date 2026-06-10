---
title: 架构总览
---

# 架构总览

Friday AI 由四个组件构成，跨进程协作完成「需求 → 代码」的自动化链路。

<FlowDiagram :layers="[
  {
    nodes: [
      { title: 'Web 控制台', badge: 'Vue 3', desc: '流程编辑器 · Chat · Galaxy 图谱' },
      { title: '飞书 / Git 平台', desc: '事件触发 · 审批卡片 · PR / MR 回写' },
    ],
    arrow: 'HTTP / WebSocket · 事件与回调',
    bidirectional: true,
  },
  {
    nodes: [
      {
        title: 'Server',
        badge: 'Django ASGI',
        accent: true,
        desc: ['REST · WebSocket · 工作流引擎', '代码智能（Graph RAG）· Provider 层'],
      },
    ],
    arrow: 'WS 任务派发 + HTTP 回调',
  },
  {
    nodes: [
      { title: 'Runner', badge: 'Go', desc: 'FIFO 队列 + 并发调度' },
    ],
    arrow: 'docker run / k8s job',
  },
  {
    nodes: [
      { title: 'Task 容器', badge: 'Python', desc: 'claude-agent-sdk 编码代理' },
    ],
  },
]" />

## 组件职责

| 组件 | 路径 | 职责 | 关键入口 |
| --- | --- | --- | --- |
| Server | `server/` | REST + WebSocket API、工作流引擎、代码智能（codegraph / RAG）、Provider 与凭据管理 | `friday/asgi.py`（HTTP→Django，WS→channels） |
| Web | `web/` | 控制台、流程编辑器、Web Chat、Galaxy 图谱 | `src/main.ts` |
| Runner | `runner/` | 注册到 server，接收任务派发，在 Docker / k8s 中运行任务容器 | `cmd/friday-runner/main.go`（cobra：`run` / `register` / `service`） |
| Task | `task/` | 容器内运行 claude-agent-sdk 编码代理，完成 clone、编码、提交、推送 | `cli/`（`friday-task`） |

## 后端分层

Django 应用按限界上下文划分（`accounts`、`projects`、`repositories`、`workflows`、`runners`、`chat`、`codegraph`、`feishu`、`mcp_tools` 等），每个 app 拥有自己的 `models/`、`api/`（DRF 视图与序列化器）和 `urls.py`。

| 层 | 位置 | 说明 |
| --- | --- | --- |
| API 层 | `server/<app>/api/` | adrf 异步 DRF 视图，JWT（Cookie）认证 |
| 服务层 | `server/services/` | 无状态领域逻辑：RAG、git 平台、Provider 解析、索引器 —— 视图和工作流节点共用 |
| 引擎层 | `server/workflows/engine/`、`server/workflows/nodes/` | DAG 调度与节点执行，见[工作流引擎](/internals/workflow-engine) |
| 数据层 | `server/<app>/models/` | Django ORM + migrations |
| Agent 核心 | `server/agents/core/` | Agent 状态、事件、结果与领域异常 |

### 异步约束

整个后端是 async-first 的：adrf 异步视图、channels consumer、`sync_to_async` 桥接 ORM。两条硬规则：

- 异步上下文访问 ORM 必须经过 `sync_to_async`，不允许裸调用；
- 工作流引擎在后台线程中自建事件循环（`_run_in_thread`），与 ASGI 主循环隔离，避免长任务阻塞请求处理。

### 实时通道

执行状态、Runner 心跳、Chat 流式输出都通过 WebSocket（channels）推送；REST 只负责 CRUD 与命令。生产环境使用 Redis Channel Layer，本地开发可退化为内存实现。

## 核心数据流

### 工作流执行（主链路）

<FlowPipeline :steps="['触发器命中', '引擎持久化 + DAG 调度', 'AI 方案 / 等待确认', 'Runner 派发 Claude Code', '回调进度', 'PR / MR 回写']" />

1. 触发：飞书事件 / 手动 / Webhook 命中触发器节点；
2. 引擎将 `WorkflowExecution` 与各 `NodeExecution` 持久化，按 DAG 拓扑调度节点；
3. AI 节点经服务层调用 Provider 生成方案，等待类节点挂起直到飞书字段满足条件；
4. 编码节点把任务经 WebSocket 派发给 Runner，Runner 启动 Task 容器执行 Claude Code；
5. Task 容器经 HTTP 回调上报进度与结果，server 推送 WebSocket 更新前端，并把 PR / MR 与轨迹回写飞书。

### Chat / RAG（次链路）

Web Chat 选择已索引仓库后，模型可调用检索与代码浏览工具；检索经 Qdrant 混合搜索 + 图谱扩散返回组合证据，详见[代码智能层](/internals/code-intelligence)。

## 状态管理

- 后端：执行状态持久化在 `WorkflowExecution` / `NodeExecution`；调试 / 暂停等瞬态在模块级 `_debug_sessions`（`engine/scheduler.py`）；
- 前端：Pinia stores + TanStack Query 服务端缓存；
- 跨进程契约：server ↔ runner 的 WebSocket + HTTP 回调协议必须在 `server/runners/`、`runner/internal/ws/` 与 `server/subagent/api/` 之间保持同步。

## 设计原则

- **凭据不进环境变量**：Provider Key、Git Token 运行时从数据库解析（Fernet 加密），见[安全模型](/internals/security)；
- **节点失败不抛出**：节点以 `NodeResult(status="failed")` 返回错误而不是向引擎外抛异常，使重试与错误处理可配置；
- **自动注册**：新工作流节点放入 `server/workflows/nodes/<category>/` 即被注册中心发现，无需手工登记；
- **重试策略**：Task 容器内用 `tenacity`，Runner 用 `go-retryablehttp`。

## 深入阅读

<LinkCards>
  <LinkCard icon="🧩" title="工作流引擎" desc="DAG 调度、节点契约、自动注册与调试" link="/internals/workflow-engine" />
  <LinkCard icon="🛰️" title="Runner 与 Task 执行器" desc="Go 调度器、任务容器与回调协议" link="/internals/runner" />
  <LinkCard icon="🧠" title="代码智能层（Graph RAG）" desc="混合检索、图谱扩散与跨仓 API 关联" link="/internals/code-intelligence" />
  <LinkCard icon="🔐" title="安全模型" desc="凭据加密、fail-closed 初始化、执行隔离与审计" link="/internals/security" />
</LinkCards>
