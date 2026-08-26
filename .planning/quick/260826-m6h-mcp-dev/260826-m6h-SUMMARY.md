---
status: complete
quick_id: 260826-m6h
completed_at: "2026-08-26T16:31:00+08:00"
---

# MCP 与本地 dev 可用性收口

## 完成内容

- MCP 客户端从 37 个工具同步到服务端当前公开的 49 个工具，补齐代码图谱、影响分析、Process 与蓝图 stage 单跑共 12 个工具。
- `@friday-ai-codes/mcp` 升级到 `0.6.0`，同步 `SERVER_VERSION`，重建本地 `dist/cli.js`。
- 修正确认门回归测试：`human_confirmed` 正式字段保持冻结，自动候选写入 `appendices/change_proposals`，不再断言旧的 `draft_content.boundaries`。
- Cursor 的 Friday MCP 配置已改为当前仓库 `mcp/dist/cli.js`，不再指向旧 GSD worktree。
- 重建 tmux `friday-ai` dev 会话；后端和前端实际工作目录均为当前仓库，端口分别为 `10241`、`10240`。

## 验证

- 工具契约双向 diff：`server=49`、`client=49`、missing/extra 均为空。
- MCP：3 个测试文件、28 个测试通过；TypeScript typecheck 通过；build 通过。
- MCP stdio 端到端：返回 49 个工具、版本 `0.6.0`；`graph_query` 请求成功到达本地后端并得到预期 400 参数校验。
- 后端：确认门与章程回灌共 62 个测试通过。
- 前端：`pnpm type-check` 通过。
- dev：`http://localhost:10240/` 返回 200；`http://localhost:10241/api/` 返回预期 401；12 个新增工具路由均返回预期 401。

## 说明

- 未创建 git commit。
- Cursor 对 MCP 工具目录有会话级缓存；配置和本地客户端已更新，重新加载 Cursor 窗口或开启新 Agent 会话后会显示新增 12 个工具。
