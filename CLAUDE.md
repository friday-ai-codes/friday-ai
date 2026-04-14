# Claude Code 项目指令
## 语言要求
**必须使用中文。** 所有回复、对话、解释、commit message、文档、注释、计划、报告，以及所有 `gsd / codex` 工作流过程回复一律使用中文。技术术语和代码标识符保持原文。这是最高优先级的硬性要求，无例外。
## 项目结构
全栈 Monorepo：`web/`（Vue 3 + TypeScript + shadcn-vue + Tailwind CSS）、`server/`（Django 6.0 + DRF + Python 3.14+）
---
## 前端规范
- 语法：`<script setup lang="ts">` + Composition API
- 样式：Tailwind CSS，禁止内联样式
- 状态：优先局部状态，必要时再提升
- 添加 shadcn 组件：`cd web && npx shadcn-vue@latest add <name>`
- 设计风格：Glassmorphism 玻璃拟态（详见 `web/DESIGN.md`）
- 禁止：React 模式/术语、Options API
---
## 后端规范
- 框架：Django 6.0 + DRF
- 类型：所有函数必须有类型注解，代码必须通过 `uv run mypy .`
- 日志：用 `structlog`，禁止标准 `logging`
- 认证：JWT (`rest_framework_simplejwt`)
- API：前缀 `/api/`，URL 必须以 `/` 结尾
- 测试：pytest，测试放 `server/tests/`，运行 `cd server && pytest`
- 数据库：默认 SQLite (`data/friday.db`)，模型变更后询问用户是否执行迁移
- 创建 App：`cd server && python manage.py startapp <name>`
---
## 通用
- 提交信息清晰、原子化，适用时引用 issue
- 代码自文档化，注释解释"为什么"而非"是什么"
---
## GSD 命令命名约定
**向用户展示 GSD 命令时一律使用 `/gsd:<name>` 冒号命名空间格式**（例如 `/gsd:plan-phase`、`/gsd:update`），**禁止使用 `/gsd-<name>` 连字符格式**。
**原因：** 本项目使用 Claude Code runtime，GSD 命令安装于 `./.claude/commands/gsd/*.md`，Claude Code 将其暴露为 `/gsd:<name>`。GSD 官方文档、workflow、agent prompt 中仍大量使用遗留的 `/gsd-<name>` 写法（为兼容 Codex/OpenCode 等不支持冒号命名空间的 runtime），用户在 Claude Code 中无法直接调用。遇到 `/gsd-xxx` 应在输出前改写为 `/gsd:xxx`。
