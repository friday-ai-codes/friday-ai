# Phase 145: Cursor / Claude Code 自动采集 - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

把 `report_session_knowledge` 接入 Claude Code 与 Cursor 的真实会话生命周期，完成问答配对、可见答案精华提取、fail-soft HTTP/MCP writeback、skills/安装器分发和文档验收。任何 clean git tree 会话也要写回；本阶段不引入新运行时依赖、不采集隐藏 CoT，也不扩展 Capture 管理 UI。

</domain>

<decisions>
## Implementation Decisions

### Claude Code 事件配对
- Claude Code 在 `UserPromptSubmit` 读取官方 stdin JSON 中的用户 prompt 与 session id，继续执行既有项目上下文召回，并把待配对问题以 `0600` 临时状态按 session 隔离保存；hook stdout 只输出需注入的上下文，不回显敏感状态。
- Claude Code 在 `Stop` 读取官方 `last_assistant_message` 作为答案来源，与同 session 最近未消费问题配对后调用 `report_session_knowledge`；不得抓 transcript、终端日志、内部 event stream 或隐藏 reasoning。
- Stop 不再以 `git diff --stat`/最近 commit 是否非空作为会话 Capture 前置条件；clean tree、纯解释、代码阅读与调试结论同样写回。既有 `report_project_knowledge` 变更总结路径保持原门闩与语义。
- 无问题、空/缺失 `last_assistant_message`、重复 Stop 或递归 hook 时安全跳过；成功提交后消费配对状态，失败保留有界可重试状态但永不阻塞宿主退出。

### Cursor 事件配对
- Cursor 只接 `beforeSubmitPrompt` 与 `afterAgentResponse`：前者保存用户 prompt/session 对应关系，后者提取最终可见 assistant response 并回写；禁止使用 `stop` 事件替代 `afterAgentResponse`。
- 生成 `.cursor/hooks.json` 采用官方 `version: 1` 结构；installer 必须结构化读取并合并目标文件，保留未知顶级键、其他事件和用户已有 hook，只追加 Friday hook 且按稳定 command 标识去重。
- Cursor 事件字段通过兼容提取器读取，缺失 session id 时生成仅用于本次本地配对的稳定 fallback；无法可靠配对时跳过，不把前一会话答案错配给后一问题。
- Cursor 采集与 Claude Code 共用同一个 writeback helper/请求体构造，统一传递可得的 repository/git URL、branch、project、session、model/provider/token 与 `client=cursor|claude_code` 元数据。

### 答案精华、安全与 fail-soft
- 上报答案只取用户可见的最终响应，做保守长度上限与空白规范化；不要求客户端再调用 LLM 总结，也不得从 thinking、tool trace、agent transcript 或 CoT 标签补内容。
- 客户端不负责价值 high/medium/low；原始可见答案进入 Capture 后由 Phase 143 Friday LLM 异步提炼。客户端禁止因自判“低价值”而丢弃。
- hook shell/helper 使用现有 `bash`、`git`、`curl` 与系统 `python3` 标准库能力；不新增 jq、Node package、Python package 或其他安装依赖，不把 PAT、问答正文或上游错误 body 写到 stdout/stderr/cache。
- 所有网络调用设置短连接/总超时并 fail-soft，HTTP 非 2xx、JSON 解析、文件锁、无 git 仓库或 MCP 不可用均返回成功宿主状态；本地敏感状态权限收紧、原子写入且有 TTL 清理。

### 分发、兼容与验收
- `skills/hooks/hooks.json` 保留 Claude Code `SessionStart`、`UserPromptSubmit`、`Stop` 结构，在现有脚本上增量接线；`ide_hook_assets.py` 生成/检查的读写路径与实体 hooks 保持一致。
- `skills/lib/installer.mjs` 安装 Cursor 时 merge `.cursor/hooks.json` v1 而非覆盖；重复安装幂等，已有同类 Friday 条目升级为当前 command，非法 JSON 先保留原文件并给出可操作警告而非静默清空。
- 更新 friday/friday-dev 相关技能快照，明确每轮问答走 `report_session_knowledge`、项目交付总结仍走 `report_project_knowledge`；两工具职责不得在文案中合并。
- E2E fixture 覆盖 Claude 与 Cursor 各一次有改动和 clean-tree 会话、可见答案配对、失败网络、重复安装、已有自定义 Cursor hooks 合并及无 CoT/凭证泄漏；npm/server snapshot 继续作为工具可达前置门禁。

### the agent's Discretion
- 共用 helper 采用 shell + Python 文件、单个 Python 标准库脚本或现有 asset generator 模板由实现者决定，只要零新增依赖且两个宿主行为一致。
- 临时配对目录、TTL、答案长度上限与锁实现由实现者按跨平台可靠性决定；不得把原始问答落入仓库或长期保留。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `skills/hooks/user-prompt-submit` 已实现 Claude `UserPromptSubmit` stdin 解析、git/branch 获取、`lookup_project_by_branch` HTTP 调用、缓存、超时和 fail-soft context 注入。
- `skills/hooks/stop` 已实现 Stop stdin 解析、git diff/commit 汇总、`report_project_knowledge` 调用与 fail-soft；应拆开“每轮 Capture”和“有交付变更的项目记忆”两条独立路径。
- `skills/hooks/hooks.json` 已注册 Claude Code `SessionStart`、`UserPromptSubmit`、`Stop`，可以增量调整而不改变官方事件名。
- `server/initiatives/services/ide_hook_assets.py` 已集中生成 Cursor/Claude/Codex hook asset、读路径和 writeback path，是服务端安装提示/快照的权威出口。

### Established Patterns
- `skills/lib/installer.mjs` 已负责 skills 复制、agent 指令 bootstrap 与目标文件幂等写入；Cursor hooks v1 merge 应复用其读 JSON、路径创建、原子/保守更新风格。
- `server/tests/initiatives/test_ide_hook_assets.py` 与 installer 测试已锁定各宿主输出资产；`server/tests/mcp_tools/test_skills_snapshot_guard.py` 保证 skill 文案引用的 MCP 工具和字段已进服务端 snapshot。
- 现有 hook 使用短超时、`FRIDAY_MCP_BASE_URL`/token 环境和 Python 标准库处理 JSON，满足“不增加 runtime dependency”的基础路径。

### Integration Points
- 在 Claude `user-prompt-submit` 保存问题，在 `stop` 从 `last_assistant_message` 配对并调用 Phase 142 `/report_session_knowledge/`；既有 project context recall 与 project knowledge writeback 分支分别保留。
- 新增 Cursor before/after hook command 资产与 `.cursor/hooks.json` v1 模板，在 `installer.mjs` 进行非破坏 merge，并由 `ide_hook_assets.py` 暴露一致安装路径。
- 共用 writeback helper 构造 Phase 142 已锁定请求体；仓库/项目不可解析时仍提交，仅 MCP 接受失败才保留重试状态。
- skills 文档与 snapshots 同步新增工具引用，E2E 从 hook stdin fixture 一直断言到 `SessionCapture` 行，不以 git diff 为成功条件。

</code_context>

<specifics>
## Specific Ideas

- Claude 的答案权威字段是 `Stop.last_assistant_message`；Cursor 的答案权威事件是 `afterAgentResponse`，二者都只代表用户已看到的最终回答。
- clean git tree 是核心验收场景，不是边缘情况；会话知识的价值与是否改文件无关。
- Cursor 安装必须像合并用户配置，不像生成构建产物：保留、自增、去重、可重复执行，绝不整文件覆盖。

</specifics>

<deferred>
## Deferred Ideas

- VS Code、JetBrains、Codex 等更多宿主自动采集留后续版本；现有 Codex 资产不因本 Phase 回退。
- 离线持久队列、跨设备 session 同步与失败 Capture 管理 UI 留后续版本。
- 客户端本地 LLM 摘要、CoT/工具轨迹采集和 transcript 上传明确不做。
- Capture 人工价值纠偏、升级为 `ProjectMemory` 草稿和管理后台不属于本 Phase。

</deferred>
