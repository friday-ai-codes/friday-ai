# 前端设计规范 — Glassmorphism 玻璃拟态
## 核心特征
| 元素 | 类名 |
|------|------|
| 玻璃卡片 | `bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl` |
| 玻璃卡片（增强） | `glass-card rounded-2xl`（使用 sub2api 风格阴影） |
| 环境光晕 | 背景用 `blur-3xl` 渐变圆形 |
| 图标容器 | `bg-gradient-to-br from-primary/20 to-primary/10 rounded-lg ` |
| 渐变文字 | `bg-gradient-to-r bg-clip-text text-transparent` |
| 悬浮效果 | `group-hover:shadow-lg group-hover:border-primary/30 transition-all` |
| Glow 光效 | `shadow-glow`（青色辉光效果） |
## 功能色系
- 主要：`from-teal-500 to-cyan-400`（青色系）
- 任务：`from-violet-500 to-purple-400`
- 警示：`from-amber-500 to-orange-400`
- 成功：`from-emerald-500 to-teal-400`
## 动画
- 进入动画：`animate-fade-in`、`animate-slide-up`、`animate-slide-down`
- 侧边滑入：`animate-slide-in-right`
- 弹出缩放：`animate-scale-in`
- 加载效果：`animate-shimmer`
- 光效循环：`animate-glow`
## 阴影
- 玻璃阴影：`shadow-glass` — 柔和的半透明投影
- 辉光阴影：`shadow-glow` — 青色辉光效果
- 卡片阴影：`shadow-card` — 基础卡片投影
- 悬浮阴影：`shadow-card-hover` — 悬浮时增强投影
## 禁止
- 扁平无装饰卡片、小圆角（`rounded-md` 或更小）
- 单调 hover 效果（仅变色，无阴影/光效）
- 使用旧蓝色系 (#3F72AF) 硬编码颜色值
