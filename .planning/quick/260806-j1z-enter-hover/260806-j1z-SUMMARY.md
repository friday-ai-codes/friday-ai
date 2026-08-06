---
quick_id: 260806-j1z
slug: enter-hover
status: complete
date: 2026-08-06
---

# Quick 260806-j1z 总结：划线评论对齐飞书文档交互

## 交付

| 层 | 改动 |
|----|------|
| 新组件 | `BlueprintCommentPopover.vue`：文档坐标绝对定位浮层（Teleport body，随文档滚动）；draft 模式（引用条 + 输入框 + Enter 发送/Shift+Enter 换行 + 取消/发送）与 thread 模式（内嵌 `BlueprintThreadCard`，动作沿用 kind 硬分流）互斥 |
| 页面接线 | `[id].vue`：「发起评论」→ 选区下方就地输入卡（含键盘路径，不再进侧栏草稿）；点击正文划线 → 划线旁就地线程卡（矩形取首枚 mark，降级角标回退块矩形，失锚回退侧栏）；`onCreateComment` 返回成败，失败保留输入 |
| 划线样式 | `annotationTokens`：`MARK_SHAPE_CLASS` 加 `transition-colors`；全部色相 open/answered 档补 `hover:bg` 字面量（hover 加深，飞书高亮手感） |
| i18n | `annotation.inlineComposer`（placeholder/send/cancel/title） |

## 关键决策

- **不给评论加「解决」按钮**：后端 `resolve/dismiss` 仅对 `ai_review_finding` 开放（其余 400），浮层内复用 ThreadCard 的渲染层分流，零新动作入口。
- **色相语义保留**：飞书全黄，但本产品划线携带 kind/severity 信息（blocker 红 / 评论紫 / 澄清 teal），只借鉴形态（底纹+底边线+hover 加深+就地卡片），不并色。
- 侧栏草稿卡组件与测试保留（页面不再传 `draft`），侧栏选中态与深链路径行为不回退。

## 验证

- vitest：commentPopover 5 + blueprint 全组 + blueprintViewer 页面测试 303 passed；`vue-tsc` 退出 0
- Playwright 真机 E2E：鼠标拖选（markdown 预览块）→ 选区浮层 → 就地输入卡 → 发送 → 划线精确落在选中文字上 → 点击划线 → 就地线程卡浮出。渲染坐标 ↔ 源坐标映射闭环验证。
- ⚠️ E2E 在该蓝图上真实创建了一条人工评论线程（「这里的入口展示逻辑需要和客户端确认一下」，锚在 fp 权益鉴权验收行），线程不可删，留作实数据。

## 备注

- 可观测性：纯前端交互改造，无新调用入口/LLM/召回，未新增埋点。
- 未提交（用户未要求）。
