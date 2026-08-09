---
name: friday-impact
description: "当用户要做 impact-analysis / 影响面分析时使用：改这段代码影响哪些调用方与执行流、MR/PR 风险面、detect_changes 看工作区改动波及范围、list_processes 看受影响执行流。覆盖 context/staleness 判读 → detect_changes/impact/list_processes → 解读 affected_processes。反向边界：只要仓库路由落点用 friday-routing；只要完整编码到 MR 用 friday-code；符号改名清单用 friday-refactoring。"
---

# Friday Impact

影响面分析工作流：在已索引仓库上判断「改这里会波及什么」，全程使用 `friday` MCP（或容器白名单同名工具）。本技能只规定**触发条件与工具顺序**，不复制工具实现细节。

## 前置门槛

看不到 `friday` MCP 工具，或调用返回 401/403，引导用户运行 `npx -y @friday-ai-codes/mcp setup`（见 `friday` 技能「环境未就绪」一节）。保留首个成功响应的 `run_id`。

## 触发条件

任一命中即用本技能：

| 用户意图 | 说明 |
| --- | --- |
| impact-analysis / 影响面 / 「改这个影响谁」 | 符号或文件级波及分析 |
| 「这次改动会踩到哪些执行流 / API」 | 需要 `affected_processes` 叙事 |
| MR/PR 风险面、回归范围 | 为评审准备影响面摘要 |
| 工作区未提交改动的波及 | `detect_changes` 批量路径 |

反向边界：

- 只要「功能点落到哪个仓库」→ `friday-routing`
- 要编码计划 / 执行 / 建 MR → `friday-code`（可在阶段二穿插本技能）
- 只要符号改名编辑清单 → `friday-refactoring`

## 工具顺序 checklist

按顺序执行；上一步失败或明显 stale 时先处理再继续。可选细节见 [references/tool-order.md](references/tool-order.md)。

1. **上下文与水位**  
   - 确认 `repository_id`（没有则先 `route_repositories` / `get_repository`）。  
   - 读信封里的 `staleness` / 索引水位；明显过期时先提示用户刷新索引，再解读结果。

2. **变更或符号影响**  
   - 有工作区/分支 diff：`detect_changes`（批量影响汇总）。  
   - 已知符号 / 文件：`impact`（单点或小集合影响）。  
   - 需要执行流清单对照：`list_processes`（可选 `symbol_id` / `community_class` 收窄）；细节用 `get_process`。

3. **解读 `affected_processes`**  
   - 从 `detect_changes` / `impact` 成功信封读取 `affected_processes`（名称、`process_key`、受影响步数 / 总步数、`community_class`）。  
   - 空数组是合法结果：声明「暂无匹配执行流 / Process 未构建」，**不要编造**流程名。  
   - `cross_community` 流程优先标出（架构跨越面更大）。

4. **输出**  
   - 按文件/符号归纳调用方与风险；附 `run_id`、`as_of`/水位。  
   - 若下游要写进 MR「影响面」段，把同一叙事交给建 MR 链路（formatter 消费同一信封字段）。

## 护栏

- 证据只引用工具返回的符号、路径、process_key；不得臆造调用链。  
- 工具 `ok=false`：报告 `error_code` / `error`，可降级为「无可靠影响面」继续其他交付，不假装零影响。  
- 不在本技能内改写仓库或 apply rename。
