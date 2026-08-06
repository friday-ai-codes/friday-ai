---
task: 蓝图批注侧栏视觉整改 —— 分组头吸顶、圆角裁切修复、线程卡重设计
slug: thread-sidebar-restyle
created: 2026-08-06
type: quick
status: complete
---

## 背景（用户原话要点）

1. 侧栏「菜单」样式太丑，卡片圆角像被裁掉一样没展示全；
2. 「AI 提问」分组头要 sticky 吸顶，且分组可折叠隐藏；
3. 线程卡要有设计感、好的阅读体验，行高要便于阅读。

## 现状定位

- 侧栏容器：`web/src/pages/knowledge/blueprints/[id].vue` 的
  `<ScrollArea class="card w-full p-3">`——padding 在 ScrollArea root 上，
  viewport 裁切 + sticky 起不来，滚动时卡片顶到 viewport 边缘被 `.card` 圆角裁切。
- 分组：`BlueprintThreadSidebar.vue` 的 `Collapsible` 组，trigger 无吸顶。
- 卡片：`BlueprintThreadCard.vue`，头部三枚徽标（kind 在分组下冗余、
  「未分级」是噪音）、时间戳全量 locale 串过长、正文 text-xs leading-5 偏挤。

## 任务

1. `[id].vue`：侧栏容器改为 card 内 flex-col——sticky 面板头（标题 + 计数 + 收起按钮）
   + ScrollArea 正文（padding 移入内容层，圆角不再裁卡片）。抽屉侧同步。
2. `BlueprintThreadSidebar.vue`：分组头 sticky top-0 + 不透明底 + full-bleed，
   徽标/箭头样式精修；组间距与卡片间距梳理。
3. `BlueprintThreadCard.vue`：
   - kind 徽标在分组语境下由 `showKind=false` 隐藏（CommentPopover 保持显示）；
   - 空 severity（未分级）徽标不渲染；
   - 时间戳改紧凑格式（当日 HH:mm / 当年 M月d日 HH:mm）；
   - 正文行高升到 leading-6、字号 13px，引用快照与问答对精修；
   - active 态由 ring-2 改为 border-primary + 弱底纹（不再溢出被裁）。
4. Playwright 截图前后对比核验；vitest 相关用例跑绿。

## 验收

- 滚动侧栏时「AI 提问」等分组头吸顶且下方卡片从其下滑过（不透底）；
- 卡片圆角任何滚动位置不被容器裁切；
- 组件测试 threadSidebar / commentPopover / blueprintViewer 全绿。
