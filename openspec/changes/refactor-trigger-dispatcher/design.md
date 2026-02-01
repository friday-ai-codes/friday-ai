## Context
当前触发器架构存在多入口分散、数据格式不一致的问题。需要设计统一的调度器来解决。
### 现状问题
```
飞书 Webhook → FeishuWebhookView → workflow_bridge._start_workflow
 ├─ 预处理: 提取 event_type, work_item_id
 └─ 构建 input_data: { event_type, work_item_id, payload }
手动执行 → WorkflowViewSet.execute → WorkflowEngine.start_execution
 └─ 直接传入用户输入
通用 Webhook → WebhookTriggerView → WorkflowEngine.start_execution
```
触发器节点需要兼容多种输入格式，增加了复杂性。
### 约束
- 向后兼容：现有飞书集成必须继续工作
- 审批功能：`workflow_bridge` 中的审批处理逻辑需要保留
- 可扩展性：方便添加新触发源（GitHub、Cron 等）
## Goals / Non-Goals
### Goals
- 统一所有触发入口通过 `TriggerDispatcher`
- 原始数据透传给触发器节点，由节点自己解析
- 触发器节点自描述：声明支持的事件类型和输入格式
- Handler 可插拔注册机制
### Non-Goals
- 不实现定时触发（Cron）- 留待后续
- 不实现 GitHub/GitLab 集成 - 留待后续
- 不改变现有 API 接口
## Decisions
### Decision 1: 统一 TriggerContext 数据结构
所有触发方式构建相同的 `TriggerContext`，包含 `raw_payload` 原始数据。
```python
@dataclass
class TriggerContext:
 trigger_type: str # "feishu" | "webhook" | "manual"
 raw_payload: dict # 原始数据，不预处理
 event_type: str | None # 事件类型（飞书事件）
 project: Project | None # 关联项目
 workflow: Workflow | None # 目标工作流（手动触发时）
 triggered_by: User | None # 触发者
 idempotency_key: str | None # 幂等键
```
**Rationale**: 统一数据结构简化下游处理，`raw_payload` 透传避免预处理导致的格式差异。
### Decision 2: Handler 注册机制
使用装饰器自动注册 Handler：
```python
@register_handler
class FeishuEventHandler(TriggerHandler):
 trigger_type = "feishu"
```
**Rationale**: 类似现有的 `@register_node` 模式，保持一致性。
### Decision 3: 触发器节点继承 BaseTriggerNode
触发器节点实现 `parse_payload` 方法解析原始数据：
```python
class FeishuEventTriggerNode(BaseTriggerNode):
 async def parse_payload(self, context: ExecutionContext) -> dict:
 raw = context.input_data.get("raw_payload", {})
 return {
 "work_item_id": raw.get("id"),
 "project_key": raw.get("project_key"),
 ...
 }
```
**Rationale**: 节点自己最清楚需要什么数据，由节点负责解析更合理。
**Alternatives considered**:
- Handler 预处理数据：会回到现在的问题，不同触发方式格式不一致
- 中间件层转换：增加复杂性，难以调试
## Architecture
```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│FeishuWebhook │ │GenericWebhook│ │ 手动触发 │
│ View │ │ View │ │ View │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
 │ │ │
 ▼ ▼ ▼
 └─────────────────┴─────────────────┘
 │
 ▼
 ┌─────────────────────┐
 │ TriggerContext │
 │ (raw_payload 透传) │
 └──────────┬──────────┘
 │
 ▼
 ┌─────────────────────┐
 │ TriggerDispatcher │
 │ ├─ validate │
 │ ├─ find_workflows│
 │ └─ start_execution │
 └──────────┬──────────┘
 │
 ┌────────────────┼────────────────┐
 ▼ ▼ ▼
 ┌─────────┐ ┌─────────┐ ┌─────────┐
 │ Feishu │ │ Webhook │ │ Manual │
 │ Handler │ │ Handler │ │ Handler │
 └─────────┘ └─────────┘ └─────────┘
 │
 ▼
 ┌─────────────────────┐
 │ WorkflowEngine │
 └──────────┬──────────┘
 │
 ▼
 ┌─────────────────────┐
 │ BaseTriggerNode │
 │ .parse_payload │
 └─────────────────────┘
```
## File Structure
```
server/workflows/triggers/
├── __init__.py
├── context.py # TriggerContext 数据类
├── dispatcher.py # TriggerDispatcher 调度器
├── registry.py # TriggerHandlerRegistry 注册表
└── handlers/
 ├── __init__.py
 ├── base.py # TriggerHandler 基类
 ├── feishu.py # FeishuEventHandler
 ├── webhook.py # WebhookHandler
 └── manual.py # ManualHandler
server/workflows/nodes/triggers/
├── base.py # BaseTriggerNode 基类 (新增)
├── feishu_event.py # 重构：继承 BaseTriggerNode
├── webhook.py # 重构：继承 BaseTriggerNode
└── manual.py # 重构：继承 BaseTriggerNode
```
## Risks / Trade-offs
| Risk | Mitigation |
|------|------------|
| 重构过程中断现有飞书集成 | 分阶段实施，先添加新代码，再切换调用 |
| Handler 查找性能 | 使用字典缓存，O(1) 查找 |
| 幂等性处理内存增长 | 设置上限，定期清理旧条目 |
## Migration Plan. **Phase**: 添加新的 triggers 模块，不影响现有代码
2. **Phase**: 改造 View 层使用 TriggerDispatcher（可选择性回退）
3. **Phase**: 验证所有触发方式工作正常
4. **Phase**: 清理 workflow_bridge 废弃代码
回滚策略：View 层保留原有代码路径，通过 feature flag 切换。
## Open Questions
- 是否需要支持触发器优先级？（多个触发器匹配时的执行顺序）
- 是否需要支持触发器链？（一个触发器触发另一个工作流）
