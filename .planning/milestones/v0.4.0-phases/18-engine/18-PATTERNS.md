# Phase 18: 执行引擎状态机修复 - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 13 个新建/修改文件
**Analogs found:** 12 / 13（仅"执行级互斥抢锁"无现成 analog）

## File Classification

| New/Modified File | 类型 | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `server/workflows/engine/routing.py` | 新建 | utility（引擎纯函数模块） | transform | `server/workflows/engine/template_resolver.py` | exact（Phase 17 同策略产物） |
| `server/workflows/engine/scheduler.py` | 修改 | service（调度引擎） | event-driven | 自身（修改点行号见下） | self |
| `server/workflows/engine/dag.py` | 修改 | model（内存图结构） | transform | 自身（`afrom_workflow` :76-98） | self |
| `server/workflows/engine/__init__.py` | 修改 | config（barrel 导出） | — | 自身 | exact |
| `server/workflows/triggers/dispatcher.py` | 修改 | service（触发收口） | request-response | 自身（:102-115） | self |
| `server/subagent/api/callbacks.py` | 修改 | controller（回调续跑） | event-driven | `server/tasks/agent_tasks.py:212-272`（可工作的同类路径） | exact |
| `server/feishu/callbacks/coding_callback.py` | 修改（删手工调度器） | controller | event-driven | `server/tasks/agent_tasks.py:212-272` | exact |
| `server/workflows/api/views.py`（resume_from_node trigger_data 继承） | 修改 | controller | request-response | 自身 scheduler.py:1720-1725 | self |
| `server/tests/workflows/test_engine_routing.py` | 新建 | test | — | `test_error_handling.py` + `test_dag.py` | exact |
| `server/tests/workflows/test_engine_waiting.py` | 新建 | test | — | `test_error_handling.py` | exact |
| `server/tests/workflows/test_engine_trigger_data.py` | 新建 | test | — | `test_error_handling.py` + 根 conftest `make_context` | exact |
| `server/tests/workflows/test_engine_deadlock.py` | 新建 | test | — | `test_error_handling.py::TestTemplateResolutionError` | exact |
| `server/tests/workflows/test_engine_inputs.py` | 新建 | test | — | `test_dag.py`（fixture）+ routing 纯函数零 DB 单测 | role-match |
| `server/tests/workflows/conftest.py` | 修改（加工作流工厂夹具） | test fixture | — | `test_engine.py:38-112` 局部 fixture 范式 | exact |

## Pattern Assignments

### `server/workflows/engine/routing.py`（新建，utility / transform）

**Analog:** `server/workflows/engine/template_resolver.py` —— Phase 17 在同一目录、同一动机（纯函数核、零 DB 可测）下的成熟先例，新模块应逐项照抄其结构。

**模块 docstring 模式**（中文、声明契约边界与"不做什么"）：

```1:23:server/workflows/engine/template_resolver.py
"""模板变量解析核心（Phase 17 实现契约）。

本模块是 `render_template` / `get_template_value` 两个 API 共享的纯函数解析核心：
不 import Django ORM、不依赖 ExecutionContext，输入全部为 plain dict，
pytest 零 DB 可测。
// ... 严格语义定界、错误分类枚举 ...
"""
```

routing.py 对应写法：不 import Django ORM、不依赖 WorkflowEngine；输入为 plain dict（`statuses: dict[node_id, status]`、`handles: dict[node_id, next_handle]`）+ DAG 对象；docstring 声明"路由/级联/死锁/输入收集四个纯函数为主循环与回调续跑唯一语义源"。

**输入数据源 dataclass 模式**（调用方构造 plain dict 集合）：

```73:88:server/workflows/engine/template_resolver.py
@dataclass
class ResolutionSources:
    """解析数据源集合（全部为 plain dict，由调用方构造）。
    // ...
    """

    previous_outputs: dict = field(default_factory=dict)
    input_data: dict = field(default_factory=dict)
    workflow_context: dict = field(default_factory=dict)
    node_config: dict = field(default_factory=dict)
    trigger_data: dict = field(default_factory=dict)
    global_values: dict = field(default_factory=dict)
```

routing.py 可仿此定义 `RoutingState`（statuses / handles / 已选中边集合），解决 Pitfall 2（内存 `result["handle"]` 与 DB `output_data._next_handle` 两来源不对称——由调用方填充入参，纯函数不感知来源）。

**模块级常量 + 私有 helper 命名模式**（`_` 前缀、模块顶部正则/枚举）：

```30:40:server/workflows/engine/template_resolver.py
# 合法前缀列表（unknown_prefix 错误的 available 候选）
VALID_PREFIXES = ["input", "context", "config", "nodes", "global", "trigger", "$"]

# UUID 形态键的识别正则（available 候选过滤用，只列 short_id 形态）
_UUID_KEY_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-")
```

**结构化错误信息构造模式**（available 只含键名/元数据，绝不含输出值——死锁诊断 `diagnose_deadlock` 同约束）：

```143:153:server/workflows/engine/template_resolver.py
        else:
            message = f"节点 ID '{node_id}' 不存在。可用的节点 ID: {available}"
        raise TemplateResolutionError(
            template=template,
            reference=path,
            reason="node_not_found",
            available=available,
            message=message,
        )
```

注意差异：死锁诊断不抛异常，而是返回诊断结构由 scheduler 写入 `amark_failed`（引擎"结果不外抛"约定），编码沿用 scheduler.py:1023-1032 模式（见 Shared Patterns）。

**DAG 既有原料**（routing 直接消费，勿重写）：

```189:196:server/workflows/engine/dag.py
    def get_successors(self, node_id: str, handle: str = "default") -> list[DAGNode]:
        """获取指定节点的后继节点"""
        dag_node = self.nodes.get(node_id)
        if not dag_node:
            return []

        successor_ids = dag_node.outgoing.get(handle, set())
        return [self.nodes[sid] for sid in successor_ids if sid in self.nodes]
```

```31:37:server/workflows/engine/dag.py
    @property
    def forward_incoming(self) -> set[str]:
        """前向依赖（排除反馈环 back-edge 的源节点）。

        调度器用此属性判断节点是否可以首次执行。
        """
        return self.incoming - self.back_edge_sources
```

---

### `server/workflows/engine/dag.py`（修改：DAGNode 增加入边明细）

**Analog:** 自身。`incoming_edges: list[(source_id, source_handle, target_handle)]` 的收集点在 `afrom_workflow` 既有循环内顺手追加（sync 版 `from_workflow` :58-72 同步改，两处对称）：

```83:98:server/workflows/engine/dag.py
        async for edge in workflow.edges.all():
            source_id = str(edge.source_node_id)
            target_id = str(edge.target_node_id)
            handle = edge.source_handle

            if source_id in dag.nodes and target_id in dag.nodes:
                dag.nodes[target_id].incoming.add(source_id)

                if handle not in dag.nodes[source_id].outgoing:
                    dag.nodes[source_id].outgoing[handle] = set()
                dag.nodes[source_id].outgoing[handle].add(target_id)

                dag.edges.append(edge)

        dag._detect_back_edges()
        return dag
```

DAGNode 字段声明照抄既有 dataclass 风格（`field(default_factory=...)` + 行尾中文注释，dag.py:14-21）。`edge.target_handle` 在此循环作用域可直接取（WorkflowEdge 完整对象已入 `dag.edges`）。

---

### `server/workflows/engine/scheduler.py`（修改，核心改造点与自身模式）

**改造点 1 — 删除 5s 轮询、挂起判定收口（ENG-01）。** 被替换的现状代码（:635-697）：`all_blocked` 遍历查 DB、`asyncio.sleep(5)` 轮询刷新（:666-677，注意 :672 只写 UUID 单键的缺陷）、死锁只列名字（:686-693）。保留并复用其中的**挂起动作三连**（这是正确写法，问题只在可达性）：

```652:662:server/workflows/engine/scheduler.py
                        if all_blocked:
                            # All paths are blocked on external events - truly suspend
                            logger.info(
                                "workflow_suspended",
                                execution_id=str(execution.id),
                                waiting_nodes=len(waiting_nodes),
                            )
                            await execution.amark_suspended()
                            await self.hooks.trigger("execution_suspended", execution=execution)
                            # Exit the loop - webhook will restart via _continue_after_node
                            return
                        else:
```

**改造点 2 — `_execute_node` 注入 trigger_data（ENG-03 唯一读取侧缺口）：**

```928:938:server/workflows/engine/scheduler.py
                context = ExecutionContext(
                    execution_id=str(execution.id),
                    node_id=str(node.id),
                    node_config=node.config,
                    input_data=input_data,
                    workflow_context=execution.context,
                    previous_outputs=previous_outputs,
                    workflow_execution=execution,
                    node_execution=node_execution,
                    node_snapshots=node_snapshots,
                )
```

在此 kwargs 列表追加 `trigger_data=execution.trigger_data or {}`。

**改造点 3 — next_handle 双来源（Pitfall 2 的事实依据）。** 内存返回值含 `handle`，DB output_data 含 `_next_handle`，routing 入参 `handles` dict 由两处分别填充：

```950:970:server/workflows/engine/scheduler.py
                # 处理结果
                if result.status == "completed":
                    output_with_handle = {**(result.output or {})}
                    if result.next_handle and result.next_handle != "default":
                        output_with_handle["_next_handle"] = result.next_handle
                    await node_execution.amark_completed(output_with_handle)
                    // ... aappend_log + hooks.trigger("node_completed") ...
                    return {
                        "status": "completed",
                        "output": result.output,
                        "handle": result.next_handle,
                    }
```

**改造点 4 — 重入式重建的输出收集（双键，直接复用）：**

```1534:1554:server/workflows/engine/scheduler.py
    async def _collect_all_outputs(self, execution: WorkflowExecution) -> dict:
        """Collect outputs from all completed nodes.

        同时按 UUID 和 short_id 存储，确保模板变量
        {{nodes.<short_id>.field}} 能正确解析。
        """
        completed_nodes = [
            ne async for ne in NodeExecution.objects.filter(
                workflow_execution=execution,
                status=NodeExecutionStatus.COMPLETED,
            ).select_related("node")
        ]

        outputs = {}
        for node_exec in completed_nodes:
            output_data = node_exec.output_data or {}
            outputs[str(node_exec.node_id)] = output_data
            if node_exec.node.short_id:
                outputs[node_exec.node.short_id] = output_data

        return outputs
```

**改造点 5 — `_check_dependencies_ready`（:1517-1532）与 `_check_execution_complete`（:1488-1515）**：前者仅认 COMPLETED（Pitfall 4 根因），随 routing 边感知判定替换；后者按锁定决策把 skipped 计入终态、增加死锁兜底调用。

**改造点 6 — `_collect_inputs`（:1093-1107，两路径共用）改为边感知归集**：现状扁平合并（RESEARCH §5 已摘录），按 Pattern 5 非破坏性叠加规则改写后迁入/委托 routing。

---

### `server/workflows/triggers/dispatcher.py`（修改：trigger_data 补 source 键）

**Analog:** 自身。唯一写入收口点：

```102:115:server/workflows/triggers/dispatcher.py
        # 5. 启动执行
        executions: list["WorkflowExecution"] = []
        for workflow in workflows:
            try:
                input_data = await handler.prepare_input(context, workflow)
                execution = await self.engine.start_execution(
                    workflow=workflow,
                    input_data=input_data,
                    triggered_by=context.triggered_by,
                    trigger_type=context.trigger_type,
                    trigger_data={"raw_payload": context.raw_payload},
                    debug_mode=context.debug_mode,
                    stop_before_node_id=context.stop_before_node_id,
                )
```

改为 `trigger_data={"source": context.trigger_type, "raw_payload": context.raw_payload}`（按 trigger_type 映射 manual/api/feishu/webhook；保留 raw_payload 键零破坏——Pitfall 8 禁止顺手加 `payload` 别名）。失败日志照抄既有 structlog 风格（:123-129）。

---

### `server/subagent/api/callbacks.py` + `server/feishu/callbacks/coding_callback.py`（修改：回调续跑统一）

**Analog:** `server/tasks/agent_tasks.py:212-272` —— 七条恢复入口中"可工作"的标准范式：**先标记节点终态，再调引擎续跑**，失败走 `_handle_node_failure`：

```251:272:server/tasks/agent_tasks.py
        if result.status == "completed":
            # Mark node as completed with agent output
            output_data = {
                "agent_session_id": session_id,
                "final_answer": result.final_answer,
                "output": result.output,
                "usage": result.usage,
            }
            await node_exec.amark_completed(output_data)

            # Continue workflow execution
            engine = WorkflowEngine()
            await engine._continue_after_node(execution, node_exec)
            log.info("工作流已继续执行下一节点")
        else:
            # Agent errored or hit max_iterations
            error_msg = result.error or f"Agent session ended with status: {result.status}"
            await node_exec.amark_failed(error_msg)

            engine = WorkflowEngine()
            await engine._handle_node_failure(execution, node_exec)
            log.warning("工作流节点执行失败", agent_status=result.status)
```

注意延迟导入模式（函数体内 `from workflows.engine.scheduler import WorkflowEngine`，agent_tasks.py:232-237 / dispatcher.py:39-42 均如此——避免循环引用，回调模块改造时保持）。容器回调修复（callbacks.py `_schedule_workflow_resume`）与 coding_callback 手工迷你调度器删除后，都收敛到"标记/重跑节点 → 重入续跑入口"这一形态；节点重跑必须走 `engine._execute_node`（含重试/超时/on_error），禁止再手工构建 ExecutionContext（Don't Hand-Roll 表）。

**无 analog 项：执行级互斥抢锁。** 代码库内无 `filter(status=...).aupdate(...)` 抢锁先例，按 RESEARCH Pitfall 6 方案新写：`WorkflowExecution.objects.filter(pk=..., status=SUSPENDED).aupdate(status=RUNNING)` 返回 0 即放弃。

---

### 五个新测试文件（`server/tests/workflows/test_engine_*.py`）

**主 Analog:** `server/tests/workflows/test_error_handling.py` —— Phase 17 新增、范式最新，四个模式全部照抄。

**模式 A：可控行为测试节点（制造任意 next_handle / waiting 行为，规避真实 AI/飞书依赖）：**

```33:47:server/tests/workflows/test_error_handling.py
class AlwaysFailNode(BaseNode):
    """Node that always fails — for testing error handling."""

    node_type = "test_always_fail"
    display_name = "Always Fail"
    description = "Always raises an exception"
    category = NodeCategory.ACTION
    execution_mode = "server_local"
    supports_retry = True

    _fail_count = 0

    async def execute(self, context: ExecutionContext) -> NodeResult:
        AlwaysFailNode._fail_count += 1
        raise RuntimeError(f"Intentional failure #{AlwaysFailNode._fail_count}")
```

Phase 18 变体：`BranchNode`（返回 `NodeResult(status="completed", output={...}, next_handle="true"/"false")`）、`WaitEventNode`（返回 `NodeResult(status="waiting_event", output={...})`）、`EchoTriggerDataNode`（输出 `context.trigger_data` 供断言）。类属性作可控旋钮（`_fail_until` / `_sleep_seconds` 模式），测试前重置。

**模式 B：autouse 注册/注销夹具：**

```111:122:server/tests/workflows/test_error_handling.py
@pytest.fixture(autouse=True)
def _register_test_nodes():
    """Register test node types for the duration of each test."""
    NodeRegistry.register(AlwaysFailNode)
    NodeRegistry.register(FailNTimesNode)
    NodeRegistry.register(SlowNode)
    NodeRegistry.register(TemplateRenderNode)
    yield
    NodeRegistry._nodes.pop("test_always_fail", None)
    NodeRegistry._nodes.pop("test_fail_n_times", None)
    NodeRegistry._nodes.pop("test_slow_node", None)
    NodeRegistry._nodes.pop("test_template_render", None)
```

**模式 C：run_sync 同步执行（新测试一律优先此范式，避免 test_engine.py 的 sleep 轮询不确定性）：**

```378:383:server/tests/workflows/test_error_handling.py
    @pytest.mark.asyncio
    async def test_abort_fails_workflow(self, engine, abort_workflow):
        """on_error=abort (default) causes workflow failure."""
        AlwaysFailNode._fail_count = 0
        execution = await engine.start_execution(abort_workflow, run_sync=True)
        assert execution.status == ExecutionStatus.FAILED
```

类级装饰器组合固定为 `@pytest.mark.asyncio` + `@pytest.mark.django_db(transaction=True)`（:287-289）。注意 Pattern 1 落地后 run_sync 在挂起时立即返回——`test_engine_waiting.py` 正是断言此新语义（`execution.status == ExecutionStatus.SUSPENDED`）。

**模式 D：结构化 error_message 断言（test_engine_deadlock.py 直接套用）：**

```709:722:server/tests/workflows/test_error_handling.py
        # (c) 最后一行可被 json.loads 且含四键，reason 属于枚举
        last_line = render_ne.error_message.strip().splitlines()[-1]
        payload = json.loads(last_line)
        assert set(payload.keys()) == {"reference", "reason", "available", "template"}
        assert payload["reason"] in {
            "node_not_found",
            "field_not_found",
            "unknown_prefix",
            "missing_field_path",
        }
```

死锁版断言键改为 `{"reason": "deadlock", "pending": [{node, short_id, waiting_on: [...]}]}`（RESEARCH Code Examples 已给目标形状）。

**模式 E：NodeExecution 状态查询断言：**

```609:615:server/tests/workflows/test_error_handling.py
        from workflows.models import NodeExecution

        downstream_ne = await NodeExecution.objects.filter(
            workflow_execution=execution, node__name="Downstream",
        ).afirst()
        assert downstream_ne is not None
        assert downstream_ne.status == NodeExecutionStatus.SKIPPED
```

skipped 级联断言（test_engine_routing.py）直接复用此写法。

**routing 纯函数零 DB 单测**（test_engine_routing.py / test_engine_inputs.py 的 unit 部分）：仿 template_resolver 的可测性策略——不标 `django_db`，手工构造 DAG/statuses dict 调纯函数。DAG 手工构造可绕过 ORM：直接实例化 `DAG()` 并填 `dag.nodes`（DAGNode 仅要求 `.node` 有 `id/short_id/name`，可用轻量 stub），或经 `pytest.fixture(db)` 建真实 workflow 后 `DAG.from_workflow`（test_dag.py 范式，见下）。

---

### `server/tests/workflows/conftest.py`（修改：新增工作流工厂夹具）

**Analog:** `test_engine.py:38-112` 的局部 fixture（trigger + 节点 + 边三件套），提升为 conftest 共享工厂。条件分支工作流的边写法参考 `test_dag.py:107-120`（source_handle="true"/"false"）：

```104:120:server/tests/workflows/test_dag.py
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="true",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_c,
        source_handle="false",
        target_handle="default",
    )
```

简单工作流工厂骨架照抄：

```37:71:server/tests/workflows/test_engine.py
@pytest.fixture
def simple_workflow(db, engine_project):
    """Create a simple two-node workflow."""
    workflow = Workflow.objects.create(
        name="Simple Workflow",
        project=engine_project,
        trigger_type="manual",
    )

    trigger_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Start",
        position_x=0,
        position_y=0,
    )
    // ... condition_node + WorkflowEdge.objects.create(source_handle="default", target_handle="default") ...
    return workflow
```

需要的工厂：`branch_workflow`（trigger → BranchNode → true/false 两支 → 菱形汇合）、`waiting_workflow`（trigger → WaitEventNode [→ 下游]）、`deadlock_workflow`（人造无法满足的依赖）。既有 conftest（tests/workflows/conftest.py）当前只有 obs_* 可观测性夹具，新工厂并列追加即可；`engine` fixture（`WorkflowEngine()` 实例，test_error_handling.py:134-137）一并上提。

**test_engine_trigger_data.py 附加 analog** — 根 conftest 的 `make_context` 工厂（tests/conftest.py:854-880）已支持 `trigger_data` 入参，可用于 resolver 侧断言；经 scheduler 的注入断言则用 EchoTriggerDataNode + run_sync 集成路径。

**既有测试需同步改写**（Pattern 1 警告项）：`test_engine.py::test_approval_node_waits`（断言 `waiting_count >= 0` 恒真，:281）与 `test_cancel_running_execution` 依赖旧轮询语义。

---

### `server/workflows/engine/__init__.py`（修改：导出 routing）

**Analog:** 自身（全文 10 行）。追加 `from workflows.engine.routing import ...` 并扩 `__all__`，与 `DAG, DAGNode, WorkflowEngine` 并列。

## Shared Patterns

### 结构化 error_message 编码（ENG-04 死锁诊断写入侧）
**Source:** `server/workflows/engine/scheduler.py:1019-1032`（Phase 17 唯一先例）
**Apply to:** routing.diagnose_deadlock 的输出 → scheduler 写 `amark_failed`

```1019:1032:server/workflows/engine/scheduler.py
            except Exception as _exc:
                if isinstance(_exc, TemplateResolutionError):
                    # 模板解析失败（VAR-02）：中文一句话 + 结构化 JSON。
                    # 最后一行可被 JSON.parse（Phase 21 错误展示直接消费）
                    structured = json.dumps(
                        {
                            "reference": _exc.reference,
                            "reason": _exc.reason,
                            "available": _exc.available,
                            "template": _exc.template,
                        },
                        ensure_ascii=False,
                    )
                    last_error = f"{_exc}\n{structured}"
```

约定三要素：中文一句话 + `\n` + `json.dumps(..., ensure_ascii=False)`；最后一行可独立 `json.loads`；JSON 只含拓扑元数据（名称/short_id/状态/handle），不含节点输出值（V5 信息泄露防线）。

### 状态变更 + hook 事件广播
**Source:** `scheduler.py:652-662`（amark_suspended + execution_suspended）、`scheduler.py:842-851`（amark_completed/amark_failed + 对应事件）、WS 侧 `workflows/hooks/builtin.py:38-75`
**Apply to:** 所有新增/移动的状态迁移点

固定顺序：`await execution.amark_xxx(...)` → `hook_execution = await self._load_execution_for_hooks(execution)`（需要时）→ `await self.hooks.trigger("execution_xxx", execution=...)`。WS 广播无需新增代码——`WebSocketBroadcastHook` 对所有事件统一发 `{event, execution_id, status}`：

```55:60:server/workflows/hooks/builtin.py
            message = {
                "type": "workflow.event",
                "event": event,
                "execution_id": str(execution.id),
                "status": execution.status,
            }
```

### structlog 结构化日志
**Source:** `scheduler.py:654-658`、`dispatcher.py:117-129`
**Apply to:** routing 决策点（skip 级联、死锁判定、抢锁失败放弃续跑）

```python
logger.info("workflow_suspended", execution_id=str(execution.id), waiting_nodes=len(waiting_nodes))
```

事件名 snake_case 作首参，上下文全部走 kwargs；ID 一律 `str(...)`。

### 中文 docstring + 契约注释
**Source:** `template_resolver.py:1-23`、`dag.py:100-107`、`dag.py:152-158`
**Apply to:** routing.py 全部公开函数、scheduler 改造点

风格：docstring 说明"为什么/定界"（含 Phase ID 引用），行内注释解释非显然约束（如 back-edge 语义、characterization 锁定项）。

### 测试装饰器组合
**Source:** `test_error_handling.py:287-289`
**Apply to:** 全部五个新测试文件的集成测试类

```python
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestXxx:
```

纯函数单测类不加 django_db（零 DB，规避 pytest-socket/事务开销）。

## No Analog Found

| File/Concern | Role | Data Flow | Reason |
|------|------|-----------|--------|
| 执行级互斥抢锁（`filter(status=SUSPENDED).aupdate(status=RUNNING)`） | service 片段 | event-driven | 代码库无原子条件更新抢锁先例；按 RESEARCH Pitfall 6 给定方案新写，NE 级可加 `filter(status=PENDING).aupdate(status=QUEUED)` 认领 |

## Metadata

**Analog search scope:** `server/workflows/engine/`、`server/workflows/triggers/`、`server/workflows/hooks/`、`server/tasks/`、`server/tests/workflows/`、`server/tests/conftest.py`
**Files scanned:** 12（template_resolver.py、dag.py、scheduler.py 五段、dispatcher.py、engine/__init__.py、hooks/builtin.py、agent_tasks.py、test_engine.py、test_error_handling.py、test_dag.py、tests/workflows/conftest.py、tests/conftest.py 片段）
**Pattern extraction date:** 2026-06-13
**配套阅读:** 18-RESEARCH.md 已含 scheduler 现状四段关键摘录（:565-586 就绪判定、:822-851 waiting_event/完成出口、:1093-1107 _collect_inputs、:1411-1424 回调路由），本文不重复，planner 直接引用。
