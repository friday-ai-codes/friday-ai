---
task: 蓝图批注侧栏视觉整改 —— 分组头吸顶、圆角裁切修复、线程卡重设计
slug: thread-sidebar-restyle
date: 2026-08-06
status: complete
---

## 改动

### 1. 圆角被裁的根因修复（`[id].vue`）

侧栏列原是静态 `sticky top-22`（88px），而吸顶头部带段导航/警示横幅时实测 130px+ ⇒
侧栏顶部（容器上圆角 + 第一张卡）整个滑进头部底下。改为与 `measureScrollOffset`
同源的实测偏移（头高 + 12px），`useResizeObserver` 跟随头高变化，`maxHeight` 同步换算。

### 2. 侧栏容器结构（`[id].vue`）

`ScrollArea.card.p-3` 单层结构改为 card 内 flex-col：

- 常驻**面板头**：icon + 「批注」标题 + 总计数 Badge + 收起按钮
  （`blueprint-sidebar-panel-collapse`，复用 `viewerStore.toggleSidebar`）；
- `ScrollArea` 只管正文滚动；内容 padding 下沉到 `BlueprintThreadSidebar`
  （`px-3 pt-3 pb-3`），分组吸顶头才能全出血。

### 3. 分组头吸顶（`BlueprintThreadSidebar.vue`）

- `CollapsibleTrigger` 改 `sticky top-0 z-10 -mx-3 w-[calc(100%+1.5rem)] bg-card`
  + 底部 hairline：滚动时「AI 提问」等组名恒在顶部，卡片从其下滑过不透底；
  折叠交互保留（reka-ui Collapsible）。
- 新增 kind 色点（teal/amber/violet/sky，与 `annotationHue` 色相档对齐）。
- 删除嵌套 `overflow-y-auto`（嵌套滚动会让 sticky 吸错 scrollport）。

### 4. 线程卡重设计（`BlueprintThreadCard.vue`）

- 新增 `showKind` prop：侧栏分组语境传 `false`（组名即 kind，卡上徽标冗余）；
  `BlueprintCommentPopover` 无分组语境保持默认 `true`。
- 空 severity 的「未分级」徽标不再渲染（噪音）。
- 时间戳紧凑档：当日 `HH:mm` / 当年 `M月d日 HH:mm` / 跨年日期；完整时间放 `title`。
- 引用快照改左色条引文样式（去 font-mono、两行截断、全文在 title）。
- 消息正文 `text-xs leading-5` → `text-[13px] leading-6`；问答对答案改左色条 +
  同款行高（去「→」前缀）。
- active 态 `ring-2 ring-primary/60` → `border-primary/40 + ring-2 ring-primary/25 +
  bg-primary/2`，hover 微反馈；`ring-2` 保留（测试 10b 契约）。

### 5. 既有 e2e 修正（`blueprint-viewer-visual.spec.ts`）

UAT 115-4 两条在本次改动前已红（此前会话把顶栏「查看批注」按钮改为 `xl:hidden`，
测试仍在 1440px 点它）：宽屏入口更新为 `blueprint-header-sidebar-toggle`
（收起→0 份、展开→1 份），断点切换用例从窄屏才点「查看批注」。

## 验证

- vitest：`src/components/blueprint` + `src/pages/knowledge` 17 文件 328 用例全绿。
- Playwright：`blueprint-viewer-visual.spec.ts` 串行 11/11 全绿
  （并行下 UAT 115-2/115-3 偶发抖动，与本次改动无关）。
- Chromium 截图核验：常驻栏（1600px）顶部完整、分组头吸顶、抽屉（1100px）同样成立。

## 未提交

按会话约定未创建 git commit；改动留在工作区由用户验收。
