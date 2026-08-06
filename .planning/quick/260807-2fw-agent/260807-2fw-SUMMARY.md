---
quick_id: 260807-2fw
slug: agent
description: 蓝图按仓调研明细：结论与 agent 过程可查
date: 2026-08-07
status: complete
---

# Quick Task 260807-2fw — 摘要

**One-liner:** 蓝图查看器新增「调研明细」抽屉 —— 按仓看**结论**（findings / 适配度 / 职责）
与 **agent 全过程**（叙述、工具调用、工具结果、读了哪些文件）；容器侧同步补上工具结果输出
并停止打印加密思考签名，全量过程改由 append-only 表承载。

补的是 v0.21.0 **LIVE-01 / LIVE-03** 的缺口：事件流只有阶段级标量（`findings_count` /
`verdict`），「agent 在做什么」这一层此前**没有任何读面**。

## 改了什么

| 层 | 文件 | 改动 |
|----|------|------|
| 容器 | `task/core/executor.py` | 新增 `UserMessage` → `ToolResultBlock` 分支打印 `[task:tool_result]`；ThinkingBlock **只取明文** `thinking`（⛔ 不再回落 `signature`）；工具入参上界 300 → 2000 |
| 落库 | `server/subagent/models.py` + `migrations/0016` | 新建 append-only `SubAgentRuntimeLog` |
| 落库 | `server/runners/consumers.py` | `_TASK_LOG_PREFIXES` 加 `tool_result`；`_append_runtime_log` 双写；失败分支改走同一通道 |
| 脱敏 | `server/common/logging.py` | `sk-` 两支加 `\b` 词边界（修误伤） |
| 读面 | `server/delivery/api/blueprint_doc_views.py` + `urls.py` | 新端点 `GET .../blueprint/research-detail/` |
| 前端 | `BlueprintResearchDrawer.vue` / `BlueprintStageStepper.vue` / `[id].vue` / `api` / `types` / `zh-CN.json` | 抽屉 + stepper 入口 + 文案 |

## 四个关键判断

**⛔ 不抬高 `_MAX_RUNTIME_LOGS`，改为双写。** `last_output["logs"]` 是 JSONField，
`_append_runtime_log` 每来一行整包读-改-写；抬到几百条再叠上工具结果，单会话写入量按
条数平方涨到几十 MB。改成：尾窗维持 80 条（**既有四个消费方零改动** —— chat runtime /
finalize / 仓库摘要 / MCP trace），全量走 `SubAgentRuntimeLog` 一行一 INSERT、可按
`(session, id)` 索引分页。⚠️ 顺序以自增 `id` 为准而非 `ts`：同毫秒多行会让工具调用与结果错位。

**⛔ 不走 `task.subagent_session` 外键。** 那个字段被 `mark_running` 每次派发覆写，阶段 2
（分仓）会把阶段 1（调研）的会话指针冲掉 ⇒ 顺着外键读只能拿到后半程。会话 id 里嵌了
`task.id.hex[:12]`，按前缀反查才能把一个仓的**每一次**运行收全（实测有个仓 4 次运行）。

**LIVE-05 的边界。** 返回工具调用、工具结果、agent 自然语言叙述（可归因的过程证据），
**不返回模型私有推理原文** —— 加密 signature 容器侧已停印、读面对存量数据一并过滤，
明文 thinking 本就取不到。所有正文出口过 `redact_secrets_in_text`。

**新增的暴露面必须脱敏。** 记录工具结果 = 仓库文件内容进浏览器，这是全仓第一次。口径与
chat 侧 `plan_research_sessions` 同源，⛔ 两处不得分叉。

## 真实数据里暴露并修掉的三个问题

1. **`findings` 全渲染成空白** —— 阶段一 `PartialPlan` 存的是 `{title, detail, citations}`，
   而分仓阶段投影到正文的是 `{id, kind, topic, text}`。**两种形态都在线上**，前端只认一种
   就会把另一种整条渲染成空。已改为两种都认。
2. **文件路径被脱敏正则吃掉** —— 容器工作目录 `/tmp/friday-ta|sk-|bp-research-…` 里的
   `task-` 正好凑成 `sk-` + 20 个合法字符，整条路径变成 `/tmp/friday-ta***REDACTED***/…`。
   这是共享脱敏函数的**既有误报**（chat 侧同样中招）。加 `\b` 后只**收窄**到「词首的 sk-」，
   凭证的真实出现位置（行首/空格/引号/`=`/`:` 之后）一律仍在边界上 ⇒ 强度不降，
   24 条凭证泄漏用例全绿。
3. **加密签名占了两成日志额度** —— 存量会话里 `[思考] EoMFCnEIEBAB…` 这类行占 74 步中的 15 步。
   读面按「`[思考]` + 40+ 位 base64」滤掉；⛔ 不按「以 `[思考]` 开头」判，那会把明文思考连坐。

## 验证

**真实蓝图 `5b650e1a-…`（4 个仓、10 次容器运行）**：

- 结论：每仓 5–7 条 findings，标题与正文都渲染得出
- 过程：阶段一 74 步 → 滤噪音后 **59 步有效**，含 27 次工具调用、20 段叙述
- 残留加密签名 **0** 行、被误脱敏的路径 **0** 行
- 阶段一 + 阶段二两段运行都在（含某仓 3 次分仓重试）

**用例**：后端 `test_blueprint_doc_views.py` 共 **62 passed**（新增 8 条：跨阶段外键覆写、
全量表优先/尾窗回落并标记、脱敏、log_limit 夹紧且取**最早** N 条、加密签名过滤、路径不被误伤）；
`test_credential_leak_protection.py` 24 passed；`test_coding_progress.py` + 日志脱敏守卫合计 98 passed。
容器侧新增 8 条纯函数用例，`task` SDK 既有用例 15 passed。
前端 `src/components/blueprint` + `src/pages/knowledge` **339 passed**，`eslint` / `vue-tsc` 干净。

## 遗留

- **工具结果只对以后跑的蓝图生效**：存量会话没有 `tool_result` 行（容器当时没打），
  抽屉里对存量数据显示「只保留了最近 80 步」的截断提示。
- `_MAX_RUNTIME_LOGS = 80` 的尾窗仍是存量数据的唯一来源 ⇒ 存量蓝图看不到全程，这是数据
  本身的缺失，⛔ 不是展示层能补的。
- `SubAgentRuntimeLog` 沿用 `ActionLog` 的口径随会话 CASCADE、⛔ 无独立清理任务；
  若日后体量成问题，可照 `system/log_retention.py` 的范式补。
- 抽屉入口只挂在 `repo_research` / `repo_plan` 两个节点（其余阶段不起容器）。
