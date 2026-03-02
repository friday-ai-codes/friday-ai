# 前端设计规范 — Glassmorphism 玻璃拟态
## 核心特征
| 元素 | 类名 |
|------|------|
| 玻璃卡片 | `bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl` |
| 环境光晕 | 背景用 `blur-3xl` 渐变圆形 |
| 图标容器 | `bg-gradient-to-br from-primary/20 to-primary/10 rounded-lg ` |
| 渐变文字 | `bg-gradient-to-r bg-clip-text text-transparent` |
| 悬浮效果 | `group-hover:shadow-lg group-hover:border-primary/30 transition-all` |
## 功能色系
- 主要：`from-blue-500 to-cyan-400`
- 任务：`from-violet-500 to-purple-400`
- 警示：`from-amber-500 to-orange-400`
- 成功：`from-emerald-500 to-teal-400`
## 禁止
- 扁平无装饰卡片、小圆角（`rounded-md` 或更小）
- 单调 hover 效果（仅变色，无阴影/光效）
