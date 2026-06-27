# `ai_plan_generation` 节点废弃说明（迁移到 `ai_plan_research`）

> 状态：**DEPRECATED（已废弃，保留注册）**
> 取代者：`ai_plan_research`
> 影响范围：新建工作流；既有已实例化工作流**不受影响**

## 废弃原因

旧的 `ai_plan_generation` 是基于单 agent 的 LangChain 方案生成节点。随着技术方案生成统一收口到
编排入口（`plan_orchestration` / `ai_plan_research`），节点库需要把方案生成路径收敛到唯一入口，
避免新建工作流时在多个语义重叠的节点之间二选一。因此：

- `ai_plan_generation` 不再从前端节点库（`NodePalette`）暴露，新建工作流无法再拖出该节点。
- 代码中以 `deprecated: ClassVar[bool] = True` 标记，并在实例化时打印一次性 `logger.warning`
  （`event="deprecated_node_instantiated"`，`category="sampling"`，`component="workflow_node"`，
  `migration="ai_plan_research"`）。

## 既有工作流不受影响

`ai_plan_generation` 仍通过 `@register_node` 保留注册，节点类代码、端口（`default` /
`need_clarification` / `error`）与 `map_output` 逻辑**逐字保留**：

- 数据库中 `node_type="ai_plan_generation"` 的既有节点实例运行期仍能经 `NodeRegistry` 查找到节点类，
  正常 `execute()`。
- 节点定义快照 `node-types.fixture.json` 仍包含 `ai_plan_generation`（后端仍注册），未从 fixture 删除。

换言之：**不删代码、不注销注册、不从 fixture 删除**——这是历史里程碑「向后兼容不回退」约束的硬要求。

## 新建工作流改用 `ai_plan_research`

新建工作流时，请在 AI 分组中选择 **AI 方案研究（`ai_plan_research`）**：

- config 使用 `requirement_text`（需求文本输入），参照 `technical_plan_generation` /
  `code_generation` 等模板节点的 config 形态。
- `ai_plan_research` 暴露在 `NodePalette` 的 AI 分组，且已在 `node-types.fixture.json` 中注册，
  满足前后端节点漂移守护（palette ⊆ fixture）。

## 不会自动迁移既有实例

本次废弃**不会**自动改写或迁移数据库中既有的 `ai_plan_generation` 节点实例。如需将既有工作流切换到
统一编排入口，请手动在工作流编辑器中替换节点并重新配置 `requirement_text` 等输入。
