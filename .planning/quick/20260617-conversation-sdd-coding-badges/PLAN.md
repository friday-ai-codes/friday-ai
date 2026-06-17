---
type: quick
slug: conversation-sdd-coding-badges
status: in-progress
created: 2026-06-17
---

# 会话列表 SDD / 技术方案 / 编码徽标

## 目标

在会话列表（`ChatConversationList.vue`）的每个会话项上展示三类轻量徽标，让会话一眼可辨其产出：

- **SDD**：该会话的方案编排产出了 `SddSpec`（领导重点关注）。
- **编码**：该会话进行过容器编码（存在 `CodingSession`）。
- **方案**：该会话产生过技术方案（存在 `CodingPlan`）但尚未编码。

## 背景与数据缺口

- `CodingPlan.conversation` / `CodingSession.conversation` 有直接 FK ✅，但会话列表 API 未序列化。
- `SddSpec` 经 `PlanVersion` 关联，但 `PlanSession`（chat 编排会话）**无 conversation 关联** ❌，
  无法从 conversation 反查 spec。

## 方案

### 后端

1. `PlanSession` 新增软 UUID 字段 `conversation_id`（`null=True, blank=True, db_index=True`）。
   - 沿用 `current_plan_version` 的「软引用、不建跨 app FK」哲学，避免 delivery→chat 硬耦合。
2. 经 `PlanSessionService.create_session` → `start_orchestration` → `start_plan_research`
   把 chat 入口的 `conversation_id` 写入（workflow 入口传 None）。
3. `list_conversations` 用 `Exists(OuterRef)` annotate 三个布尔：
   - `has_coding_plan`：`CodingPlan(conversation_id=conv)` 存在
   - `has_coding_session`：`CodingSession(conversation_id=conv)` 存在
   - `has_sdd_spec`：`SddSpec(plan_version_id ∈ PlanSession(conversation_id=conv).current_plan_version)` 存在
4. `ConversationListSerializer` 暴露三个 bool（read-only，默认 False 向后兼容）。

### 前端

5. `web/src/types/chat.ts` `Conversation` 增加三个可选 bool。
6. 新建 `web/src/components/chat/ConversationBadges.vue`，按 flag 渲染：
   - `has_sdd_spec` → emerald "SDD" pill（scroll-text 图标）
   - `has_coding_session` → 编码 chip（code-2）
   - `has_coding_plan && !has_coding_session` → 方案 chip（clipboard-list）
7. 接到 `ChatConversationList.vue` 会话项（标题与更多菜单之间，shrink-0）。
8. i18n 文案接入 `zh-CN.json`。

## 验收

- `makemigrations --check` 无遗漏；现有 PlanSession/会话测试不回退。
- 新增后端测试：list API 返回三个 bool；有 spec 的会话 has_sdd_spec=True。
- 前端组件单测：按 flag 渲染对应徽标。
- vue-tsc + eslint 干净。

## 原子提交边界

- `feat(quick): add conversation_id to PlanSession + migration`
- `feat(quick): annotate conversation list with SDD/plan/coding flags`
- `feat(quick): show SDD/plan/coding badges in conversation list`
