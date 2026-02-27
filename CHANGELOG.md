# Changelog
All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [5.3.0] - 2026-02-28
### Major Changes
- **Vue Flow 迁移完成** — 工作流编辑器从 AntV X6 全面迁移到 Vue Flow，全功能保留 + 节点外观重新设计
### Features
- 27 种自定义节点 — BaseWorkflowNode slot 壳组件 + TriggerNode/ActionNode/ControlNode/DynamicPortNode 4 个类别组件
- GradientEdge 自定义边 — SVG linearGradient 渐变边，替代 X6 默认边
- 连线验证 — useConnectionValidator composable 实现防自连接/防重复/防环(BFS)验证
- 拖放交互 — useDragAndDrop composable（HTML5 Drag + screenToFlowCoordinate），从节点面板拖拽到画布
- MiniMap/Controls 插件 — Glassmorphism 玻璃拟态风格的小地图和控制面板
- NodeToolbar 浮动工具栏 — 单选浮动工具栏(复制/删除) + 多选统一工具栏(批量操作)
- 键盘快捷键 — useKeyboardShortcuts composable（Delete/Ctrl+C/V/A + isInputFocused guard）
- 动态端口 — parallel/join 节点支持动态添加/移除端口
### Removed
- 移除 AntV X6 代码 — 删除 26 个 X6 文件（节点、边、插件、工具函数）
- 移除 X6 npm 依赖 — 卸载 `@antv/x6` 和 `@antv/x6-vue-shape` 及其依赖链
- 移除 X6 测试页面 — 删除 `x6-test.vue`
### Bundle Size
- 构建产物减小约 500KB（移除 X6 及其依赖链后）
### Technical
- 数据转换层 — 后端 API 格式不变，前端转换层适配 Vue Flow nodes/edges 格式
- 端口配置独立模块 — portConfig.ts（PortMetadata 仅 id + group），不依赖任何图形库
- 状态管理 — useVueFlow + useExecutionsStore + useNodeStyle composables
- 类型安全 — 完整 TypeScript 类型定义，vue-tsc 零错误
- 执行状态可视化 — 节点行状态差异化（running 蓝色脉冲/completed 绿色微光/failed 红色微光/skipped 半透明）
- WebSocket 实时更新 — 移除 useTimeoutPoll 轮询，改用 connectWebSocket/disconnectWebSocket 生命周期管理
### Documentation
- 迁移说明文档 — `project-docs/phases/95-x6/MIGRATION.md`
- Phase 计划文档 — Phase 完整计划和总结
- 需求文档 — 21 个需求（EDITOR/NODE/CONN/INTERACT/DATA/CLEANUP）
- 回归测试清单 — 14 项自动化测试 + 41 项手动 UI 测试
### Breaking Changes
- **对用户无影响** — 后端 API 和数据格式完全不变，已有工作流自动兼容
- **对开发者** — 不再使用 X6 API，节点开发改用 Vue Flow 的 `<Handle>` 组件和 `useVueFlow` composable
