---
title: 贡献指南
---

# 贡献指南

感谢你帮助改进 Friday AI。本页是 [CONTRIBUTING.md](https://github.com/friday-ai-codes/friday-ai/blob/main/CONTRIBUTING.md) 的展开版。

## 开发环境

1. 安装 Docker、Docker Compose v2、`uv`、Node.js、pnpm、Go 和 Git；
2. 生成本地配置：

   ```bash
   scripts/setup.sh
   ```

3. 安装依赖：

   ```bash
   make install
   ```

4. 启动应用：`docker compose up -d`，或本地运行 `make dev`（tmux 分屏起前后端）。

详细的工具链版本与调试方式见[源码与本地开发](/deploy/source)。

## 提交前检查

按你改动的区域跑对应检查：

::: code-group

```bash [Server]
cd server
uv run pytest \
  tests/test_credential_leak_protection.py \
  tests/test_interactions_ledger.py \
  tests/mcp_tools/test_feishu_work_item_context.py \
  tests/test_httpx_removal_guard.py \
  tests/test_conversation_facade_waiting_clarification.py \
  tests/test_intent_router.py \
  tests/test_langchain_runner_core.py \
  tests/test_langchain_runner_no_stategraph.py \
  tests/test_coding_progress.py \
  --cov=. --cov-report=term-missing
```

```bash [Web]
cd web
pnpm lint && pnpm type-check && pnpm test:unit:coverage
pnpm test:e2e -- --project=chromium
```

```bash [Runner]
cd runner
go vet ./... && go test ./...
```

```bash [Task]
cd task
uv run ruff check . && uv run pytest
```

:::

Server 的 ruff 和 mypy 在 CI 中暂时是 advisory（legacy 基线规整中），但改动大范围后端代码前在本地跑一遍仍然有价值。

涉及部署面（compose、setup 脚本）的改动，提 PR 前还要验证：

```bash
bash -n scripts/setup.sh
scripts/setup.sh --non-interactive --force --data-dir /tmp/friday-ai-data
docker compose config
```

## 提交信息规范

Friday AI 使用严格的 commit subject 格式，CI 会运行 `scripts/check_commit_messages.sh --all` 拒绝不合规的提交：

```text
feat: add hat wobble
^--^  ^------------^
|     |
|     +-> 现在时态的摘要
|
+-------> 类型：chore / docs / feat / fix / refactor / style / test
```

| 类型 | 用途 |
| --- | --- |
| `feat` | 面向用户的新功能（不含构建脚本） |
| `fix` | 面向用户的 bug 修复（不含构建脚本） |
| `docs` | 仅文档变更 |
| `style` | 格式调整，不改生产代码逻辑 |
| `refactor` | 生产代码重构（如重命名变量） |
| `test` | 新增或重构测试，不改生产代码 |
| `chore` | 维护性工作，不改生产代码 |

不要使用 scope、checkpoint 编号、混合类型或私有 workflow ID。

## Pull Request

- 保持改动聚焦，说明对用户可见的影响；
- 附上测试，或解释为什么测试不可行；
- 行为、配置或公开 API 变化时同步更新文档；
- 不要提交 `.env`、数据库文件、日志、生成的报告或隐私数据。

## 贡献文档

文档站基于 VitePress，源文件在 `docs/`：

```bash
pnpm install        # 仓库根目录
pnpm docs:dev       # 本地预览
pnpm docs:build     # 构建验证（CI 的 docs-ci 也会跑这一步）
```

REST API 文档由 OpenAPI schema 自动生成，更新方式：

```bash
cd server && uv run python manage.py spectacular --color --file ../docs/public/schema.json
pnpm docs:generate-api
```

文档写作约定：正文使用中文，专有名词、代码标识、命令和 URL 保留英文原文。

## 安全问题

不要在公开 issue 中报告安全漏洞，请遵循 [SECURITY.md](https://github.com/friday-ai-codes/friday-ai/blob/main/SECURITY.md) 的流程。
