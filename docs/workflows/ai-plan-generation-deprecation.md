# `ai_plan_generation` 节点退役说明（已迁移到 `ai_plan_research`）

> 状态：**已删除（节点类不再存在、不再注册）**
> 取代者：`ai_plan_research`
> 既有工作流：由数据迁移 `workflows/0034_migrate_ai_plan_generation_to_plan_research` 自动迁移

## 退役原因

旧的 `ai_plan_generation` 是基于单 agent 的 LangChain 方案生成节点。技术方案生成统一收口到编排入口
（`process_runtime` / `ai_plan_research`）后，节点库需要把方案生成路径收敛到唯一入口，避免新建工作流时
在多个语义重叠的节点之间二选一。

Chassis v2 对该节点选择了**物理删除**而非标记 deprecated：节点类 `workflows/nodes/ai/plan_generation.py`
已删除，`NodeRegistry.get("ai_plan_generation")` 返回 `None`。现行契约由
`server/tests/workflows/test_node_schema.py` 守护。

## 既有工作流如何处理

**编辑态（`WorkflowNode`）由迁移 0034 自动改写**，无需人工干预。

在补上 0034 之前存在一个缺口：删除节点类的同时没有配套数据迁移，而迁移 0007 / 0011 恰恰把
`ai_agent` / `ai_technical_plan` **迁入**了 `ai_plan_generation`。升级后的存量部署里这些行会成为孤儿，
执行时命中 `workflows/engine/scheduler.py` 的 `raise ValueError(f"未知的节点类型: ...")` 硬失败
（不是降级）。0034 补齐了这条缺口。

### config 转换规则

两个节点的 config schema 只部分重叠，0034 的映射策略是：

| 旧字段 | 处理 |
|--------|------|
| `model` / `chat_id` / `use_custom_api` / `api_base_url` / `api_key` / `api_format` / `provider_type` / `include_repos` | 逐字保留（两边 schema 都有） |
| `user_prompt` | 映射到 `requirement_text`（旧节点用它承载需求文本）；已有 `requirement_text` 时不覆盖 |
| `system_prompt` / `exclude_repos` / `max_iterations` / `enabled_tools` 等 | 归档到 `_legacy_ai_plan_generation` 键 |

被归档的字段没有销毁——`config` 是 JSONField，`BaseNode.validate_config` 用 jsonschema 校验且未设
`additionalProperties: false`，额外键不影响校验，运维可据此人工恢复。

迁移不可逆（反向为 noop），与 0011 同例。

### 历史执行记录保持原样

迁移**只改 `WorkflowNode`，不动 `NodeExecution`**。历史执行记录里 `node_type` 仍是
`ai_plan_generation`，因此前端以下四处的 AI 节点类型列表**必须继续包含该值**，否则旧执行记录渲染异常：

- `web/src/pages/executions/[id].vue`
- `web/src/components/execution/NodeDataTab.vue`
- `web/src/components/execution/NodeDetailSheet.vue`
- `web/src/components/execution/dag/composables/useExecutionDag.ts`

这四处已加注释说明。清理死代码时不要按"grep 到 ai_plan_generation 就删"处理。

## 新建工作流改用 `ai_plan_research`

在 AI 分组中选择 **AI 方案编排调研（`ai_plan_research`）**，config 使用 `requirement_text` 承载需求文本。
