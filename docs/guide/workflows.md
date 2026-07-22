---
title: 工作流指南
---

# 工作流指南

Friday 工作流引擎基于 DAG（有向无环图）实现可视化自动化编排。通过将不同功能的节点以连线方式串联，你可以构建从需求触发到代码交付的完整自动化流程。

核心概念一张图：

<FlowPipeline :steps="['触发器接收事件', '节点链依次处理', '输出执行结果']" />

::: tip 前置阅读
如果你还没有部署 Friday，请先阅读[快速开始指南](/guide/quick-start)完成安装和基础配置。引擎的内部实现见[工作流引擎](/internals/workflow-engine)。
:::

## 创建工作流

1. 进入目标项目页面
2. 点击左侧导航栏的「工作流」标签
3. 点击「创建工作流」按钮
4. 填写工作流名称和描述
5. 进入可视化编辑器

在可视化编辑器中，你可以通过拖拽方式添加节点，并用连线定义节点之间的执行顺序。每个工作流必须以一个触发器节点作为起点。

## 配置触发器

触发器是工作流的入口，决定了工作流何时被启动。Friday 提供三种触发器类型：

### 飞书事件触发（feishu_event_trigger）

监听飞书工作项的状态变更等事件，自动启动工作流。

**适用场景：** 需求状态流转时自动触发 AI 方案生成、编码等操作。

**配置项：**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `event_type` | 是 | 监听的飞书事件类型（单选） |
| `project_ids` | 否 | 要监听的 Friday 项目 ID 列表，留空监听所有项目 |
| `filter_project_key` | 否 | 飞书项目 Key（高级用法：直接指定飞书项目标识） |
| `filter_work_item_type` | 否 | 仅处理指定类型的工作项（story/task/bug/epic/feature） |
| `filter_status` | 否 | 状态过滤，仅在指定状态变更时触发 |
| `filter_status_custom` | 否 | 自定义状态 key，多个用逗号分隔 |
| `exclude_project_ids` | 否 | 要排除的项目 ID 列表 |
| `exclude_work_item_pattern` | 否 | 排除工作项（包含匹配）：工作项名称包含此文本时被排除 |
| `exclude_work_item_regex` | 否 | 排除工作项（正则匹配）：使用正则表达式匹配要排除的工作项 |

**配置示例：**

```json
{
  "event_type": "work_item_status_changed",
  "filter_status": ["开发中"],
  "filter_work_item_type": "story",
  "exclude_work_item_pattern": "测试",
  "exclude_work_item_regex": "^\\[SKIP\\]"
}
```

### 手动触发（manual_trigger）

通过 Web UI 按钮或 API 调用手动启动工作流。

**适用场景：** 调试、测试，或需要人工决定何时执行的场景。

**配置项：**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `input_schema` | 否 | 定义触发时用户需要输入的参数 |

**配置示例：**

```json
{
  "input_schema": {
    "type": "object",
    "properties": {
      "work_item_id": { "type": "string", "description": "工作项 ID" },
      "branch_name": { "type": "string", "description": "目标分支" }
    },
    "required": ["work_item_id"]
  }
}
```

### Webhook 触发（webhook_trigger）

接收外部系统发送的 HTTP POST 请求来启动工作流。

**适用场景：** 与 CI/CD、第三方系统集成。

**配置项：**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `path` | 否 | 自定义的 Webhook 路径后缀 |
| `method` | 否 | HTTP 方法 |
| `secret` | 否 | 用于验证请求的签名密钥 |
| `response_mode` | 否 | `immediate`（立即响应）或 `wait`（等待工作流完成后响应） |

**配置示例：**

```json
{
  "path": "deploy-trigger",
  "secret": "your-webhook-secret",
  "response_mode": "immediate"
}
```

## 配置节点

节点是工作流的核心执行单元。每个节点接收上游输出作为输入，处理后将结果传递给下游节点。

### AI 节点组

AI 节点利用大语言模型完成智能化任务，是 Friday 的核心能力。

#### AI 方案生成（ai_plan_generation）

自动分析需求并生成结构化技术方案，支持跨仓库分析。

| 配置项 | 说明 |
| --- | --- |
| `model` | LLM 模型，推荐 `claude-sonnet-4-20250514` |
| `feishu_field_key` | 技术方案回填到飞书的目标字段 Key |
| `auto_transition_status` | 方案生成后自动将工作项流转到指定状态 |

::: tip 推荐配置
开启 `auto_transition_status` 并设为「待审核」，方案生成后自动流转状态，减少人工操作。
:::

#### 方案审批（ai_plan_approval）

审批技术方案，支持通过飞书群发送审批通知。

| 配置项 | 说明 |
| --- | --- |
| `chat_id` | 飞书群 ID，用于发送审批通知 |

#### AI 编码指派器（ai_coding_dispatcher）

根据技术方案自动创建编码任务，将方案拆分为可执行的编码单元。

| 配置项 | 说明 |
| --- | --- |
| `merge_same_branch` | 是否将目标相同仓库/分支的任务合并为单个编码任务（推荐开启） |

#### AI 编码执行（ai_coding）

由 Runner 在 Docker 容器中隔离执行 AI 编码任务，自动创建 MR/PR。

| 配置项 | 说明 |
| --- | --- |
| `container_image` | SubAgent 容器镜像 |
| `timeout_seconds` | 单个仓库编码超时（秒） |
| `chat_id` | 飞书群 ID，用于发送结果通知和分支确认 |
| `write_back` | 编码完成（MR 结果已知）后将执行结果回写到绑定的飞书工作项（评论），新建节点默认开启 |

::: warning 存量工作流升级说明（write_back）
`write_back` 为 v0.17.0 新增配置。**存量工作流（配置中没有该键）升级后行为不变**：仅当工作流上下文能反查到绑定的飞书工作项（技术方案 → 工作项链路，或触发数据携带工作项三元组）时才回写；反查不到时静默跳过，与升级前完全一致，不产生任何新评论或告警噪音。

- 显式设为 `false` 可完全关闭回写；显式设为 `true` 但未绑定工作项时会记录 `writeback_skipped` 事件（不报错）。
- 回写失败只记录 `writeback_failed` 结构化事件，不重试、不阻断工作流。
- 与下游 `notify_feishu_im` 节点的语义分工：工作项评论是**业务留痕**（沉淀在需求单上），IM 卡片是**即时通知**（推送给群/个人），两者互不替代。
:::

::: tip 执行模式
`ai_coding` 和 `ai_code_review` 为 `runner_dispatched` 模式，需要 Runner 在线才能执行。其他 AI 节点在 Server 端本地执行。
:::

#### AI 代码审查（ai_code_review）

对 AI 编码结果进行多维度审查，支持多轮迭代审查。

| 配置项 | 说明 |
| --- | --- |
| `model` | 审查使用的 LLM 模型 |
| `chat_id` | 飞书群 ID，用于发送审查结果 |
| `max_iterations` | Agent 审查迭代上限 |
| `timeout_hours` | 最大等待时间（小时） |

#### AI Prompt（ai_prompt）

通用 AI 调用节点，可自定义 system prompt 和 user prompt，灵活处理各种文本任务。

| 配置项 | 说明 |
| --- | --- |
| `system_prompt` | 系统提示词，定义 AI 角色和行为 |
| `user_prompt` | 用户提示词，支持模板变量引用上游数据 |
| `model` | LLM 模型 |

#### 召回上下文（context_retrieval）

从向量数据库检索与当前任务相关的上下文信息，为后续 AI 节点提供参考资料。

#### AI 变量提取（ai_variable_extractor）

利用 AI 从非结构化文本中提取结构化变量，例如从需求描述中提取关键参数。

### 控制流节点组

控制流节点用于编排执行顺序和分支逻辑。

#### 条件分支（condition）

根据表达式结果选择不同的执行路径。

| 配置项 | 说明 |
| --- | --- |
| `expression` | 条件表达式，返回 true 或 false |
| `true_branch` | 条件为 true 时的下游节点 |
| `false_branch` | 条件为 false 时的下游节点 |

#### 延迟（delay）

暂停工作流执行指定的时间。

| 配置项 | 说明 |
| --- | --- |
| `duration_seconds` | 延迟时间（秒） |

#### 并行分支 / 汇合（parallel / join）

将工作流分为多个并行执行的分支，并在所有分支完成后汇合继续执行。

| 配置项 | 说明 |
| --- | --- |
| `branches` | 并行分支配置 |

#### ForEach 循环（foreach）

对列表中的每个元素执行操作，支持串行和并发两种模式，适合批量处理多个仓库、多个工作项的场景。

| 配置项 | 说明 |
| --- | --- |
| `list_source` | 列表数据来源，支持模板变量（如 <span v-pre>`{{input.items}}`</span>） |
| `execution_mode` | `sequential`（串行）或 `parallel`（并发） |
| `max_concurrency` | 并发模式下的最大并发数（1-50，默认 5） |
| `on_iteration_error` | `abort`（任一失败终止）或 `continue`（记录错误继续） |

#### 变量聚合（aggregate）

把多个上游节点的输出汇总成一个对象，常放在并行分支之后整理数据。

#### 等待飞书字段（wait_feishu_field）

暂停工作流，等待飞书工作项指定字段变更为期望值后继续执行。

| 配置项 | 说明 |
| --- | --- |
| `field_key` | 等待的飞书字段 Key |
| `expected_value` | 期望的字段值 |
| `timeout_seconds` | 超时时间（秒），超时后工作流失败 |

::: tip 典型用法
用于「AI 方案生成」后等待人工审核通过，再继续后续编码流程。推荐设置 `timeout_seconds` 为 604800（7 天）。
:::

#### 人工审批（human_approval）

暂停工作流等待指定审批人操作，审批通过后继续执行。

| 配置项 | 说明 |
| --- | --- |
| `approvers` | 审批人列表 |
| `timeout` | 审批超时时间 |

### 操作节点组

操作节点执行具体的代码管理和数据处理操作。

#### 创建分支（create_branch）

在关联的代码仓库中创建新分支。

| 配置项 | 说明 |
| --- | --- |
| `branch_name_template` | 分支名称模板，支持变量引用 |

#### 创建 PR（create_pr）

在代码仓库中创建 Pull Request / Merge Request。

| 配置项 | 说明 |
| --- | --- |
| `title_template` | PR 标题模板 |
| `description_template` | PR 描述模板 |
| `target_branch` | 目标分支 |

#### 合并 PR（merge_pr）

合并已创建的 Pull Request。

| 配置项 | 说明 |
| --- | --- |
| `merge_method` | 合并方式：`merge`、`squash` 或 `rebase` |

#### 获取空间信息（fetch_space_info）

获取项目空间的配置信息，包括关联仓库、飞书配置等数据。

| 配置项 | 说明 |
| --- | --- |
| `space_identifier` | 空间标识 |
| `identifier_type` | 标识类型 |
| `include_repositories` | 是否返回空间关联的仓库列表 |

#### 代码执行（code）

在沙箱中执行一段 Python 代码处理上游数据，适合表达式不够用的数据加工场景。代码在执行前会经过 AST 校验，禁止 import、文件与网络访问等危险语法。

| 配置项 | 说明 |
| --- | --- |
| `code` | 要执行的 Python 代码 |
| `timeout_seconds` | 执行超时（秒） |

#### 变量提取（variable_extractor）

基于正则表达式或 JSONPath 从上游数据中提取变量。

### 集成节点组

集成节点用于与外部系统交互。

#### 获取工作项详情（fetch_work_item）

从飞书项目空间拉取工作项的详细信息。

#### HTTP 请求（http_request）

发送自定义 HTTP 请求，与任意外部 API 集成。

| 配置项 | 说明 |
| --- | --- |
| `method` | HTTP 方法（GET/POST/PUT/DELETE） |
| `url` | 请求 URL，支持模板变量 |
| `headers` | 请求头 |
| `body` | 请求体 |

#### 飞书通知（notify_feishu）

向飞书群发送消息通知。

| 配置项 | 说明 |
| --- | --- |
| `chat_id` | 飞书群 ID |
| `message_template` | 消息模板，支持变量引用 |

#### 获取群聊 / 加入群聊（fetch_group_chat / join_group_chat）

`fetch_group_chat` 查找与工作项关联的飞书群聊并返回群信息；`join_group_chat` 把 Friday 机器人邀请进指定群聊。两者常配合使用：先找到需求对应的群，再确保机器人在群里，后续的提问卡片和结果通知才发得出去。

| 配置项 | 说明 |
| --- | --- |
| `chat_id` | 飞书群 ID，留空时可通过工作项信息查找 |
| `project_key` / `work_item_id` | 通过工作项定位群聊（`fetch_group_chat`） |

#### 群聊提问（group_chat_question）

在飞书群里发送提问卡片，暂停工作流等待群成员回答后继续。适合执行中缺信息（缺字段、缺截图、需要确认分支）的场景。

| 配置项 | 说明 |
| --- | --- |
| `chat_id` | 飞书群 ID |
| `question` | 问题内容，支持模板变量 |
| `options` | 可选项列表（生成按钮卡片） |
| `mention_user_id` | @ 指定成员 |
| `max_rounds` | 最大追问轮数 |

#### MCP 部署（mcp_deploy）

将服务部署到 MCP（Model Context Protocol）服务。

## 推荐工作流模板

### 需求到 PR 自动化工作流

这是 Friday 最典型的使用场景：从飞书需求状态变更自动触发，经过 AI 方案生成、人工审核、AI 编码，最终自动创建 PR。

<FlowPipeline :steps="['飞书事件触发', 'AI 方案生成', '等待飞书字段（审核通过）', 'AI 编码指派器']" />

**推荐节点配置：**

<Steps>

1. 飞书事件触发

   - 事件类型：工作项状态变更
   - 状态过滤：进入「开发中」状态时触发

2. AI 方案生成

   - 模型：`claude-sonnet-4-20250514`（推荐）
   - 飞书字段 Key：技术方案回填的目标字段
   - 自动流转状态：开启，目标状态「待审核」

3. 等待飞书字段

   - 等待条件：审核状态字段变为「通过」
   - 超时时间：7 天（604800 秒）

4. AI 编码指派器

   - 合并同分支任务：开启（推荐）

</Steps>

::: tip 扩展工作流
你可以在 AI 编码指派器之后继续添加 `ai_coding` → `ai_code_review` → `create_pr` 节点，实现从需求到代码审查的完整自动化。
:::

## 运行与调试

### 手动运行

1. 进入工作流详情页
2. 点击「手动运行」按钮
3. 如果工作流使用 `manual_trigger`，填入测试数据
4. 点击「执行」开始运行

### 飞书事件触发运行

1. 确保飞书 Webhook 已正确配置（参考[飞书集成](/integrations/feishu)）
2. 在飞书项目空间中操作工作项（如变更状态）
3. Friday 自动接收事件并启动匹配的工作流

### 执行监控

工作流运行后，你可以通过执行详情页实时监控进度：

- **DAG 视图：** 以图形方式展示各节点执行状态
  - 灰色 — 待执行
  - 蓝色 — 执行中
  - 绿色 — 成功
  - 红色 — 失败
- **AI 透视：** 查看 AI 节点的输入 prompt 和输出内容，了解 AI 的决策过程
- **执行日志：** 查看每个节点的详细日志、输入输出数据和执行耗时

### 故障排查

**节点执行失败：**

- 点击失败节点查看错误信息
- 修复问题后，可从失败节点重新运行

**工作流卡住：**

- 检查等待节点（如 `wait_feishu_field`、`human_approval`）的条件是否满足
- 确认超时时间设置是否合理

**Runner 相关节点失败：**

- `ai_coding` 和 `ai_code_review` 需要 Runner 在线
- 检查 Runner 状态（参考[管理指南 - Runner 管理](/guide/admin#runner-管理)）

## 附录：节点类型速查表

以下表格列出 Friday 全部 32 种节点类型。<Badge type="info" text="server" /> 表示在 Server 端执行，<Badge type="warning" text="runner" /> 表示需要 Runner 在线执行。

| node_type | 显示名称 | 分类 | 执行模式 | 阻塞 |
| --- | --- | --- | --- | --- |
| `feishu_event_trigger` | 飞书事件触发 | 触发器节点 | <Badge type="info" text="server" /> | |
| `manual_trigger` | 手动触发 | 触发器节点 | <Badge type="info" text="server" /> | |
| `webhook_trigger` | Webhook 触发 | 触发器节点 | <Badge type="info" text="server" /> | |
| `ai_code_review` | AI 代码审查 | AI 节点 | <Badge type="warning" text="runner" /> | 是 |
| `ai_coding` | AI 编码执行 | AI 节点 | <Badge type="warning" text="runner" /> | 是 |
| `ai_coding_dispatcher` | AI 编码指派器 | AI 节点 | <Badge type="info" text="server" /> | |
| `ai_plan_approval` | 方案审批 | AI 节点 | <Badge type="info" text="server" /> | 是 |
| `ai_plan_generation` | AI 方案生成 | AI 节点 | <Badge type="info" text="server" /> | 是 |
| `ai_prompt` | AI Prompt | AI 节点 | <Badge type="info" text="server" /> | |
| `ai_variable_extractor` | AI 变量提取 | AI 节点 | <Badge type="info" text="server" /> | |
| `context_retrieval` | 召回上下文 | AI 节点 | <Badge type="info" text="server" /> | |
| `aggregate` | 变量聚合 | 控制流节点 | <Badge type="info" text="server" /> | |
| `condition` | 条件分支 | 控制流节点 | <Badge type="info" text="server" /> | |
| `delay` | 延迟 | 控制流节点 | <Badge type="info" text="server" /> | |
| `foreach` | ForEach 循环 | 控制流节点 | <Badge type="info" text="server" /> | |
| `human_approval` | 人工审批 | 控制流节点 | <Badge type="info" text="server" /> | 是 |
| `join` | 并行汇合 | 控制流节点 | <Badge type="info" text="server" /> | |
| `parallel` | 并行分支 | 控制流节点 | <Badge type="info" text="server" /> | |
| `wait_feishu_field` | 等待飞书字段 | 控制流节点 | <Badge type="info" text="server" /> | 是 |
| `code` | 代码执行 | 操作节点 | <Badge type="info" text="server" /> | |
| `create_branch` | 创建分支 | 操作节点 | <Badge type="info" text="server" /> | |
| `create_pr` | 创建 PR | 操作节点 | <Badge type="info" text="server" /> | |
| `fetch_space_info` | 获取空间信息 | 操作节点 | <Badge type="info" text="server" /> | |
| `merge_pr` | 合并 PR | 操作节点 | <Badge type="info" text="server" /> | |
| `variable_extractor` | 变量提取 | 操作节点 | <Badge type="info" text="server" /> | |
| `fetch_group_chat` | 获取群聊 | 集成节点 | <Badge type="info" text="server" /> | |
| `fetch_work_item` | 获取工作项详情 | 集成节点 | <Badge type="info" text="server" /> | |
| `group_chat_question` | 群聊提问 | 集成节点 | <Badge type="info" text="server" /> | 是 |
| `http_request` | HTTP 请求 | 集成节点 | <Badge type="info" text="server" /> | |
| `join_group_chat` | 加入群聊 | 集成节点 | <Badge type="info" text="server" /> | |
| `mcp_deploy` | MCP 部署 | 集成节点 | <Badge type="info" text="server" /> | |
| `notify_feishu` | 飞书通知 | 集成节点 | <Badge type="info" text="server" /> | |
