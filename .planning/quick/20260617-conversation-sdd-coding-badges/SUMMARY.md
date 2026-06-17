---
type: quick
slug: conversation-sdd-coding-badges
status: complete
created: 2026-06-17
completed: 2026-06-17
---

# SUMMARY — 会话列表 SDD / 技术方案 / 编码徽标

## 成果

会话列表每个会话项现可展示三类轻量徽标，一眼可辨产出：
- **SDD**（emerald pill）：会话方案编排产出了 `SddSpec`
- **编码**（sky chip）：会话存在 `CodingSession`
- **方案**（amber chip）：会话存在 `CodingPlan` 但尚未编码（编码已隐含方案，互斥避免重复）

附带完成「仓库卡片 SDD 强调」（同会话，需求 1）：SDD 仓库卡片 emerald 边框 + 淡绿底色 +
镂空绿色半透明 "SDD" 水印；SDD 方法论徽标全站升级为填充 emerald + scroll-text 图标。

## 关键决策

- **PlanSession.conversation_id 用软 UUID 而非跨 app FK**：沿用 `current_plan_version`
  既有「软引用避免 delivery→chat 硬耦合」哲学，避免循环依赖与迁移耦合。
- **SDD 反查走单层 OuterRef**：`Exists(PlanSession.filter(conversation_id=OuterRef(pk),
  current_plan_version__in=SddSpec.values(plan_version_id)))`，内层为非关联子查询，规避
  双层 OuterRef 无法解析的问题。
- **三个 flag 用 annotate Exists**：无 N+1，annotate 列由序列化器直接读属性、async 安全。
- **编码隐含方案**：前端 `has_coding_plan && !has_coding_session` 才显示方案徽标。

## 改动文件

后端：
- `server/delivery/models/plan_session.py` — 新增 `conversation_id` 软 UUID 字段
- `server/delivery/migrations/0022_plansession_conversation_id.py` — 迁移
- `server/delivery/services/plan_session_service.py` — create_session 透传 conversation_id
- `server/services/plan_orchestration/entrypoint.py` — start_orchestration 透传
- `server/agents/tools/plan_research_tools.py` — chat 入口写入 conversation_id
- `server/chat/conversation_service.py` — list_conversations annotate 三 bool
- `server/chat/serializers.py` — ConversationListSerializer 暴露三 bool
- `server/tests/chat/test_conversation_list_badges.py` — 新测试（5 例）

前端：
- `web/src/types/chat.ts` — Conversation 增三可选 bool
- `web/src/components/chat/ConversationBadges.vue` — 新徽标组件
- `web/src/components/chat/ChatConversationList.vue` — 接入徽标
- `web/src/components/chat/__tests__/ConversationBadges.test.ts` — 新测试（6 例）
- （需求 1）`web/src/components/repository/SddMethodologyBadge.vue`、
  `web/src/pages/repositories/index.vue`、`web/src/styles/main.css`

## 验证

- `makemigrations --check` 无遗漏；migrate OK
- 后端：新测试 5 例 + plan session 回归 3 例 + SDD INV-6 守护 7 例全过；ruff 干净
- 前端：ConversationBadges 6 例 + SddMethodologyBadge 4 例全过；eslint 干净；vue-tsc 0 错误

## 后续（未做）

- Wave 编码（`RepoCodingTask`，工作流多仓）在 chat 场景仍无法从 conversation 反查
  （与 PlanSession 不同链路）；当前编码徽标只覆盖 chat `CodingSession` 路径。
- 历史会话的 `PlanSession.conversation_id` 为空（新字段），仅新发起的 chat 编排会回填；
  历史 SDD 会话徽标不会追溯显示。
