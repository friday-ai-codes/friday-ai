# Claude Code 项目指令
## 语言要求
**必须使用中文回复用户。** 这是项目的硬性要求，所有对话、解释、文档注释都使用中文。
## 项目结构
全栈 Monorepo：
- **前端**: `web/` — Vue 3 + TypeScript + shadcn-vue + Tailwind CSS
- **后端**: `server/` — Django 6.0 + DRF + Python 3.14+
---
## 前端规范
### 技术约定
- 语法：`<script setup lang="ts">` + Composition API
- 样式：Tailwind CSS，禁止内联样式
- 状态：优先局部状态，必要时再提升
- 添加 shadcn 组件：`cd web && npx shadcn-vue@latest add <name>`
### 设计风格：Glassmorphism
采用玻璃拟态风格，核心特征：
| 元素 | 类名 |
|------|------|
| 玻璃卡片 | `bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl` |
| 环境光晕 | 背景用 `blur-3xl` 渐变圆形 |
| 图标容器 | `bg-gradient-to-br from-primary/20 to-primary/10 rounded-lg ` |
| 渐变文字 | `bg-gradient-to-r bg-clip-text text-transparent` |
| 悬浮效果 | `group-hover:shadow-lg group-hover:border-primary/30 transition-all` |
功能色系：
- 主要：`from-blue-500 to-cyan-400`
- 任务：`from-violet-500 to-purple-400`
- 警示：`from-amber-500 to-orange-400`
- 成功：`from-emerald-500 to-teal-400`
### 禁止
- React 模式/术语、Options API
- 扁平无装饰卡片、小圆角（`rounded-md` 或更小）
- 单调 hover 效果（仅变色，无阴影/光效）
---
## 后端规范
### 技术约定
- 框架：Django 6.0 + DRF
- 类型：所有函数必须有类型注解，代码必须通过 `uv run mypy .`
- 日志：用 `structlog`，禁止标准 `logging`
- 认证：JWT (`rest_framework_simplejwt`)
- 创建 App：`cd server && python manage.py startapp <name>`
### API 设计
- 前缀 `/api/`，URL 必须以 `/` 结尾
- 文档：`/api/docs` (Swagger)、`/api/redoc`
### 测试
- 框架：pytest，测试放 `server/tests/`
- 运行：`cd server && pytest`
### 数据库
- 默认 SQLite (`data/friday.db`)
- 模型变更后询问用户是否执行迁移
---
## 通用
- 提交信息清晰、原子化，适用时引用 issue
- 代码自文档化，注释解释"为什么"而非"是什么"
