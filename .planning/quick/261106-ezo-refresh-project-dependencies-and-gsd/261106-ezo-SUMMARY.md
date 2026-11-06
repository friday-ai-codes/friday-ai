---
status: complete
---

# 依赖维护与项目进度核对

## 更新范围

- 项目内的 GSD 稳定版统一为 1.20.1。Codex、Claude Code 的原版本为 1.7.0，Cursor 为 1.3.1。安装采用项目相对路径，保留已有 Cursor 可观测性规则，去重 Codex 启动钩子。三份安装清单共 2,544 个文件，已逐一校验 SHA-256。用六列表格样本复验了旧版 Cursor 的计划计数定制。
- 按飞书官方技能目录刷新项目锁文件。原有 27 个技能中有 23 个内容摘要变化，另加入妙记、视频会议等兼容入口共同依赖的 lark-meeting。核对 28 个技能的 526 份源文件，仅将锁文件纳入项目。
- 后端与任务执行器统一 Claude Agent SDK 0.1.81，保留 MCP 1.x 兼容约束。Django 从 6.0.1 更新至 6.0.10，LangGraph 从 1.1.6 更新至 1.1.10。原 Python 镜像在解析时返回 HTTP 429，两份 uv 锁文件经 PyPI 官方源重建、冻结安装并导出。
- 文档与前端统一使用 pnpm 10.34.9。Vite 升至 8.3.6，Vitest 和覆盖率插件统一为 4.1.12。保留项目对 Vue 来源的信任策略。Shiki Markdown 插件锁在兼容 markdown-it 14 的 4.4.0，vue-tsc 保留通过模板类型检查的 3.3.4。
- Runner 保持 Go 1.25.0 兼容。Docker SDK 从 28.0.1 升至 28.5.2，Kubernetes 三个客户端包从 0.34.5 升至 0.34.13。最新版 gopsutil 补丁要求 Go 1.26，本次保留原锁定版本。
- 任务镜像固定使用 Claude Code stable 2.1.311。npm 仅放行该包的安装脚本，构建时执行版本检查。

## 已运行的验证

| 范围 | 结果 |
|---|---|
| GSD | 三套项目 CLI 均能读取 v0.26.0、Phase 146 及 6 个计划 |
| 后端 | Django 系统检查通过，迁移无漂移。SQLite 默认套件 11,156 通过、61 跳过、29 按标记排除、1 预期失败。独立 PostgreSQL 17 队列套件 15 通过 |
| 前端与文档 | 锁文件冻结安装、Vue 类型检查与生产构建、文档生产构建通过。前端 2,361 通过、1 跳过。Vue Macros 和 vee-validate 仍有 peer 版本提示 |
| Runner | 构建、go vet、竞态测试通过；另用 Go 1.25.0 运行完整 Go 单测通过 |
| 任务执行器 | 308 通过、3 跳过。无需供应商密钥的 SDK MCP 初始化通过 |
| 任务镜像 | 本机 linux/arm64 完整构建通过。构建器临时改用中科大 Alpine 软件源，仓库 Dockerfile 使用默认源。默认源的重复构建因系统包下载过慢主动停止。以非 root 用户验证了镜像原生入口、friday-task --help、Claude CLI 2.1.311 和 SDK MCP 初始化 |
| 独立子模块 | MCP 类型检查、31 项测试、构建通过。Friday skills 6 项测试通过。MCP 固定提交与子仓 main 的文件树相同，skills 固定提交等于其远端 main |

## 交付位置（核对日期 2026-11-06）

远端 main 最近一次合并为 10 月 9 日的 PR #4。蓝图就绪门、确认和交接取件等改动已合并，五项 CI 均通过。GitHub 最近发布的是 v0.21.0，v0.25.0 已在 GSD 归档。当前里程碑为 v0.26.0，Phase 146 已有 6 个计划，执行总结为 0，也缺少阶段验收报告。147–152 尚未进入正式执行。[PR #4](https://github.com/friday-ai-codes/friday-ai/pull/4) · [发布记录](https://github.com/friday-ai-codes/friday-ai/releases)

在无业务凭证的本地 stdio 进程中实际调用 tools/list。当前源码提供 55 个工具，同版本号的 npm 0.6.0 包提供 42 个，缺少蓝图审批、已确认交接取件和 graph_query 等 13 个工具。下一步从 146 的公共契约与发布包对账开始，并对已有实现补充验证。10 月交付记录里的重跑使用了 Mock 蓝图；真实 Friday、Runner、Qdrant 和飞书的端到端验收仍待补齐。
