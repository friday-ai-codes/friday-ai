# Phase 84: 项目工作台前端 2.0 - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

把项目做成可视、好用的在线工作区前端——大盘（概览/人员带身份/状态栏）+ feature list 进度灯 + 5 文件在线查看/编辑（md 实时渲染 + 编辑回灌同步引擎）+ 记忆编辑/LLM 提议确认 UI + 外部依赖/关联展示 + 项目列表筛选 + 全局/RAG 搜索 + 创建入口。

交付需求：WB-01~05。本 phase 标 UI hint=yes，plan 前先经 `gsd-ui-phase` 产 UI-SPEC.md。
</domain>

<decisions>
## Implementation Decisions

### 工作台布局
- **左侧导航栏 + 右侧主内容区**（split 布局）：左栏列工作区区块（概览/5 文件/外部依赖/搜索等），右侧渲染当前区块主内容。
- 借鉴既有「工作区」体验（`spaces/[id]`），加载稳定 + 空/错兜底（骨架屏 + 错误态）。

### 5 文件查看/编辑
- **md 实时渲染查看 + 源码（codemirror）编辑回灌**：查看态 md 渲染；编辑态用 codemirror 编辑源码，保存经同步引擎（Phase 83）block 级回灌飞书。
- 记忆（MEMORY）复用条目式渲染 + 编辑 + LLM 提议（draft）确认 UI。
- 编辑只允许写"人工区"段（系统区只读，与同步引擎区段分区一致）。

### feature list 展示
- **模块→功能点→验收项 树形折叠 + 进度灯**：分层树形结构，每层可折叠。
- 进度灯：待开发/进行中/测试中/已完成，结合看板 WorkItem 状态点亮。

### 其余（WB-01/04/05）
- 大盘：概览 + 人员带身份（PM/开发负责人/开发者/测试，复用 ProjectMember 角色）+ 状态栏。
- 外部依赖/关联：原型/Spec/缺陷/UI 稿/评审/复盘（复用 `Artifact`）+ 分支/知识/仓库/项目/PR。
- 项目列表：按 空间/状态/成员 筛选 + 全局 + RAG 模糊搜索（搜到上下文→属哪个仓库/项目）+ 创建入口（手动创建、绑定看板）。
- 全量 zh-CN、vue-tsc 绿、不破前端基线。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `web/src/pages/spaces/[id]/index.vue` + 子页（repositories/members/providers/prompts）：split 布局 + 子区块参照模板。
- `web/src/pages/projects/index.vue`、`web/src/pages/projects/[id]/index.vue`：v0.15.0 最小项目页，本期升级为完整工作台。
- `web/src/api/`：barrel re-export，新增 projects 工作区 / 5 文件 / 搜索端点。
- `@tanstack/vue-query`（server state）+ Pinia（本地态）+ codemirror/`@codemirror/*`（源码编辑）+ markdown 渲染。
- `web/src/pages/projects/__tests__/projects-list.spec.ts`：既有列表测试，扩展时保持基线绿。

### Established Patterns
- 派发→轮询范式（useMutation + 条件 refetchInterval）。
- 守护测试以真实 zh-CN.json 作 i18n messages 断言关键文案。
- ApiError + cookie-JWT refresh；`~/` 路径别名。

### Integration Points
- 5 文件编辑保存 → Phase 83 同步引擎回灌端点。
- RAG 搜索 → Phase 85 项目上下文召回端点（本 phase 可先接基础搜索，深化在 85）。
- AppSidebar.vue「项目」tab（Phase 82 注册）→ 工作台入口。

</code_context>

<specifics>
## Specific Ideas

- 编辑器明确用 codemirror（源码）而非 tiptap（富文本），与 md 源同步对齐、避免富文本→md 转换损耗。
- 布局明确左导航+右主区（非单页 tab、非多子页路由）。

</specifics>

<deferred>
## Deferred Ideas

- UI 稿多模态/figma 正文召回（PROJX-01，v2）——本期 UI 稿仅元数据。
- 项目级燃尽图/进度统计（PROJX-05，v2）。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §4.4 五文件形态、§11 阶段总览
- `.planning/REQUIREMENTS.md` — WB-01~05
- `.planning/ROADMAP.md` — Phase 84 Success Criteria + UI hint
- `${phase_dir}/84-UI-SPEC.md` — UI 设计契约（gsd-ui-phase 产出，plan 前必读）

</canonical_refs>
