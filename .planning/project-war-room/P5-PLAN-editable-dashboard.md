# P5 技术方案：大盘可编辑增强

**所属里程碑：** 项目作战室 / 工作区大盘（见 `MILESTONE-PROPOSAL.md`）
**Phase：** P5（Wave 3）
**产出方式：** Cursor 技术方案（非 GSD）
**定稿：** 2026-06-27 · 状态：Ready to execute（依赖 P1 大盘）

---

## 1. 目标

让大盘"不只是展示"——项目成员可在大盘各分区**就地编辑/补充**信息。最大化复用 v0.16.0 已有写端点，前端为主，补权限闸与移动端打磨。

## 2. 范围

**做：** 文档人工区就地编辑、API 清单 CRUD、记忆补充、feature/工作项"补充说明"承载、成员写权限闸、错误处理、移动端、测试。
**不做：** 新建写后端端点（除非缺口）、改 feature/work item 真相源（派生数据不直接改）、迭代、星图（P4）。
**不破坏：** 飞书双向同步的 system/human 分区机制（系统区只读）。

## 3. 现状基线（已核对）

- 已有写端点（复用）：
  - 文档人工区：`projectWorkspaceApi.updateHumanBlocks(projectId, docType, blocks)`（仅 human 区可写，system 区只读）。
  - API 清单：`state-apis` `upsertStateApi/patchStateApi/deleteStateApi`。
  - 项目记忆：`projectMemory` 条目式新增/编辑（draft/confirm 流）。
- 已有编辑组件：`MarkdownSourceEditor.vue`、`MemorySection.vue`、`DocsSection.vue`。
- 权限：`usePermission(spaceId)` / `isSpaceAdmin`；项目成员判定（P2 亦收口）。

## 4. 任务分解（文件级）

### T1 — 文档分区就地编辑
- 大盘文档 zone：human 区块进入编辑态（复用 `MarkdownSourceEditor`）→ 保存调 `updateHumanBlocks`；system 区只读并标注"系统维护"。
- 乐观更新 + 失败回滚 + toast；保存中禁用按钮。

### T2 — API 清单 CRUD
- 大盘"API 清单" zone：行内新增/编辑/删除（`upsertStateApi`/`patchStateApi`/`deleteStateApi`）；method/path/params/status 字段校验（vee-validate + zod）。

### T3 — 记忆补充
- 大盘"项目记忆" zone：新增条目（走既有 draft/confirm 流）；展示贡献者/时间。

### T4 — feature/工作项"补充"
- feature/work item 为派生数据**不直接改**；提供"补充说明"入口 → 落到项目记忆（关联该 feature 名）或备注段，避免动看板真相源。

### T5 — 权限闸
- 统一：仅项目成员可进入编辑态；非成员只读（按钮隐藏/禁用 + 语义 disabled）。
- 与 P2 后端写权限对齐；前端仅显隐，越权以后端为准。

### T6 — i18n / 移动端 / 观测
- `projects.warroom.edit.*`：编辑/保存/取消/补充/系统区只读提示/校验错误。
- 移动端：编辑态弹层/抽屉，避免窄屏溢出；触控 ≥44px；保存反馈。
- 观测：写操作复用既有后端端点日志（已具 caller 埋点）；前端 `useErrorHandler` 统一错误。

### T7 — 测试
- 文档 human 区编辑保存/回滚；system 区只读。
- state-apis 增删改 + 校验。
- 记忆补充 draft 流。
- 权限闸：非成员只读。
- 移动端编辑不溢出。

## 5. 验收标准
- 成员可在大盘就地编辑文档人工区、增删改 API 清单、补充记忆。
- 系统区只读不可改；非成员全只读。
- 编辑有保存/失败反馈；移动端可用不溢出。
- 复用既有写端点，无绕过同步/脱敏；新增测试通过。

## 6. 风险与缓解
- **system/human 边界**：严格只让 human 区可写，复用既有分区标记，防写穿系统区。
- **乐观更新一致性**：失败回滚 + 重新拉取；与飞书双向同步的延迟写不冲突（仍走既有 service）。
- **派生数据误编辑**：feature/work item 明确只读 + "补充"改走记忆，避免污染真相源。

## 7. 衔接
- 上游：P1 大盘分区。下游：里程碑收尾（回填进度 + 同步 ROADMAP）。

---
*P5 完成后回填 `MILESTONE-PROPOSAL.md` §11 P5 状态，并将本里程碑同步入 `.planning/ROADMAP.md`/`STATE.md`（若纳入正式里程碑）。*
