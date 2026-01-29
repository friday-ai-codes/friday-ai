# Design: Global Variables System
## Context
Friday 工作流系统需要一种机制，让用户能够从工作项数据中提取关键信息，并在后续节点中以统一、直观的方式引用。当前的节点输出引用虽然功能完整，但缺乏：
1. 显式的变量定义和命名
2. 变量元数据（描述、是否必填等）
3. 跨节点的统一引用语法
## Goals / Non-Goals
### Goals
- 提供直观的全局变量定义和引用机制
- 支持从结构化数据（JSON/YAML）中提取变量
- 支持使用 AI 从非结构化文本中智能提取变量
- 在所有节点配置中统一支持 `{{ global.xxx }}` 语法
- 变量具有元数据（key, name, desc, required）
### Non-Goals
- 不实现变量的跨工作流共享（仅限单次执行）
- 不实现复杂的变量类型系统（所有变量视为字符串或 JSON）
## Decisions
### 1. 变量存储位置
**Decision**: 将全局变量存储在 `WorkflowExecution.context['global_variables']` 中
**Rationale**:
- 复用现有的 context 机制，无需新增数据库字段
- 变量随 `WorkflowExecution` 记录持久化到数据库，支持：
 - **执行复盘**：查看历史执行时完整还原当时的变量状态
 - **重新触发**：基于已保存的变量值重新执行工作流
 - **调试审计**：追溯变量的来源节点和提取时间
- 与现有的 `{{ global.xxx }}` 模板语法无缝衔接
**Structure**:
```python
{
 "global_variables": {
 "requirementsDescription": {
 "key": "requirementsDescription",
 "name": "需求描述",
 "desc": "从工作项中提取的需求描述文本",
 "value": "实际的需求描述内容...",
 "required": True,
 "source_node": "node_uuid_123"
 }
 }
}
```
### 2. 变量提取路径语法
**Decision**: 使用 JSONPath 语法
**Syntax examples**:
```python
$.data.title # 简单路径
$.fields[0].value # 数组索引
$.fields[-1].value # 最后一个元素
$.fields[?(@.key=='description')].value # 条件过滤
$.items[*].name # 所有元素的某字段
```
**Alternatives considered**:
- 点号语法 (`data.fields.description`): 简单但无法处理条件过滤
- JMESPath: 功能类似但社区采用度不如 JSONPath
**Rationale**:
- JSONPath 是业界标准，文档丰富
- 支持条件过滤 `[?(@.key=='xxx')]`，可精确提取数组中特定对象的字段
- Python 有成熟库 `jsonpath-ng` 支持
**Implementation**:
```python
from jsonpath_ng import parse
expr = parse("$.fields[?(@.key=='description')].value")
matches = expr.find(data)
value = matches[0].value if matches else None
```
### 3. AI 提取的 Prompt 设计
**Decision**: 使用结构化输出格式，要求 AI 返回 JSON
**Prompt Template**:
```
请从以下文本中提取指定的变量信息，以 JSON 格式返回。
需要提取的变量：
{{#each variables}}
- {{key}}: {{desc}}
{{/each}}
文本内容：
{{input_text}}
请返回 JSON 格式：
{
 "variables": {
 "variableKey": "提取的值",
 ...
 }
}
```
### 4. 必填变量校验时机
**Decision**: 在变量提取节点执行完成后立即校验
**Rationale**:
- 尽早失败，避免后续节点因缺少变量而产生不明确的错误
- 用户可在节点配置中明确标记哪些变量是必填的
### 5. 前端变量自动补全
**Decision**: 在支持模板语法的输入框中，输入 `{{` 时弹出变量选择器
**Implementation**:
- 通过 API 获取当前执行上下文中已定义的全局变量列表
- 在编辑模式下，显示工作流中所有变量提取节点定义的变量
- 显示变量的 `name` 和 `desc` 帮助用户选择
### 6. 前端可视化路径选择器
**Decision**: 采用可视化树形选择器，根据触发事件类型显示对应的数据结构预览
**Layout**:
```
┌─────────────────────────────────────────────────────────────────────┐
│ 变量提取配置 │
├─────────────────────────────────────────────────────────────────────┤
│ 数据结构预览 │ 提取规则 │
│ ┌───────────────────────────┐ │ ┌───────────────────────────┐ │
│ │ ▼ payload │ │ │ 变量名: 需求描述 │ │
│ │ ├─ project_key │ │ │ Key: requirementDesc │ │
│ │ ├─ id │ │ │ 路径: $.payload.fields │ │
│ │ ├─ name ────────────● │──→│ │ [?(@.key=='desc')] │ │
│ │ ├─ work_item_type_key │ │ │ .value │ │
│ │ ▼ fields [数组] │ │ │ 必填: ☑ │ │
│ │ ├─ [key=field_bcff9b] │ │ └───────────────────────────┘ │
│ │ │ ├─ key │ │ │
│ │ │ └─ value ─────● │ │ [+ 添加提取规则] │
│ │ └─ [key=description] │ │ │
│ │ ├─ key │ │ ───────────────────────────── │
│ │ └─ value │ │ 预览结果: │
│ └───────────────────────────┘ │ ┌───────────────────────────┐ │
│ │ │ "用户可以通过邮箱登录..." │ │
│ 事件类型: WorkitemCreateEvent ▼ │ └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```
**事件类型与数据结构映射**:
根据工作流触发节点的事件类型，左侧显示对应的 Schema 预览：
| 事件类型 | 特有字段 | 说明 |
|---------|---------|------|
| `WorkitemCreateEvent` | `id`, `name`, `work_item_type_key`, `fields` | 工作项创建 |
| `WorkitemStatusEvent` | `cur_work_item_status.state_key`, `pre_work_item_status.state_key` | 状态变更 |
| `WorkFlowNodeStatusEvent` | `status_change_type` | 节点流转 |
| `WorkitemCommentEvent` | `comment` | 评论内容 |
| `WorkitemUpdateEvent` | `changed_fields` | 字段变更 |
**常用字段快捷选项**:
基于 `KeyFields` 预定义，提供快捷选择：
| 快捷项 | JSONPath | 说明 |
|-------|----------|------|
| 需求文档 | `$.payload.fields[?(@.key=='field_bcff9b')].value` | PRD 链接 |
| 技术方案 | `$.payload.fields[?(@.key=='field_3f6667')].value` | 技术文档链接 |
| 描述 | `$.payload.fields[?(@.key=='description')].value` | 工作项描述 |
| 工作项名称 | `$.payload.name` | 标题 |
| 工作项ID | `$.payload.id` | ID |
**交互流程**:
1. **自动识别上游**: 变量提取节点连接到上游节点后，自动识别数据来源
2. **加载 Schema**: 根据上游节点类型（触发器/其他节点）加载对应的数据结构
3. **点击选择**: 用户点击树形视图中的字段 → 自动生成 JSONPath
4. **数组处理**: 点击数组字段时弹出过滤条件配置面板
5. **实时预览**: 如有历史执行数据，显示实际提取结果预览
6. **手动编辑**: 高级用户可直接编辑 JSONPath 表达式
## Risks / Trade-offs
| Risk | Mitigation |
|------|------------|
| AI 提取结果不稳定 | 提供重试机制；用户可手动修正；记录原始输出便于调试 |
| 路径语法不够强大 | 先实现简单语法，根据用户反馈迭代扩展 |
| 变量命名冲突 | 节点按拓扑顺序执行，后定义的同名变量覆盖先定义的，记录 warning |
## Migration Plan
此功能为新增功能，无需迁移现有数据。
1. 后端先实现基础设施和节点
2. 前端实现配置面板
3. 灰度发布，收集用户反馈
4. 根据反馈迭代自动补全体验
## Open Questions
1. 是否需要支持变量的「作用域」概念（如仅在特定分支可见）？
2. AI 提取失败时的降级策略：是否允许用户手动填写？
3. 是否需要提供「变量预览」功能，在执行前验证提取逻辑？
