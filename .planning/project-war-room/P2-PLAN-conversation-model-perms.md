# P2 技术方案：会话模型与权限（后端）

**所属里程碑：** 项目作战室 / 工作区大盘（见 `MILESTONE-PROPOSAL.md`）
**Phase：** P2（Wave 2，后端，本期重头）
**产出方式：** Cursor 技术方案（非 GSD）
**定稿：** 2026-06-27 · 状态：Ready to execute

---

## 1. 目标

在严格 owner 隔离（ISO-01~04）之上，给会话加入 `visibility`（个人/共享）维度与「共享只读 + clone 贡献」权限模型，并让序列化器暴露**贡献者头像+名字、时间、单会话执行时长**，为 P3 内嵌会话栏提供后端契约。

## 2. 范围

**做：** `Conversation.visibility` 字段 + 迁移；统一会话访问判定函数替换散落 owner gate；list/create/patch/fork 扩展；serializer 暴露 贡献者/时间/duration；权限全量测试；观测/审计/脱敏。
**不做：** 前端（P3）、星图（P4）、多人同写（用 clone 规避）、迭代。
**不破坏：** 现有个人会话 owner 隔离语义、frozen/pin 语义、归档语义。

## 3. 现状基线（已核对）

- `server/chat/models.py::Conversation`：有 `space`(可空) / `created_by`(ISO owner 真源) / `bound_project`(绑定项目自动加载上下文) / `status` / `is_deleted` / `is_archived` / `created_at` / `updated_at`。**无 visibility**。
- `server/chat/views.py`：owner gate 散落 ~10+ 处（list 359、detail/messages/SSE/interrupt/runtime 等均 `created_by_id != user.id → 404`，无 superuser bypass；已有 `has_project_access` 作 null-owner/共享行兜底注释）；`bound_project_id` 已可经 PATCH 设置（687–700）。
- `server/chat/serializers.py`：DRF 纯 `Serializer`（非 ModelSerializer，需显式加字段）。已有 `_OwnerBriefSerializer{id,username,display_name}`、`ConversationListSerializer`、`ConversationDetailSerializer`、`ConversationMessageSerializer`、`CreateConversationSerializer`、`ConversationPatchSerializer`(含 bound_project_id)、`ConversationForkRequestSerializer`。
- 执行时长来源：`OrchestrationRun`（按 conversation 关联，有 status/created_at/updated_at 等）。

## 4. 任务分解（文件级）

### T1 — 模型字段 `visibility`
- `chat/models.py`：新增
  ```python
  class Visibility(models.TextChoices):
      PERSONAL = "personal", "个人"
      SHARED = "shared", "项目共享"
  visibility = models.CharField(max_length=16, choices=Visibility.choices,
                                default=Visibility.PERSONAL, db_index=True)
  ```
- 约束：`visibility=shared` 必须 `bound_project_id is not None`（在 service/serializer 校验，非 DB CHECK 以便迁移平滑）。
- 索引：`Meta.indexes += [Index(fields=["bound_project", "visibility", "is_deleted", "is_archived"]), Index(fields=["bound_project", "created_by"])]`。
- 迁移：`makemigrations chat`；存量全部默认 `personal`（行为不回退）。

### T2 — 统一会话访问判定
- 新增 `chat/access.py`（或并入既有 permissions）：
  ```python
  def resolve_conversation_access(user, conv) -> ConvAccess:
      # ConvAccess(can_read, can_write, can_archive, can_delete, can_set_visibility)
  ```
  规则：
  - `personal`：仅 `created_by`==user → 全权；否则全 False（404 语义保持）。
  - `shared`：user 为 `bound_project` 成员 → can_read=True；can_write=（user==created_by）；can_archive=True(任意成员)；can_delete=（user==created_by or 项目管理员）；can_set_visibility=（user==created_by）。非成员 → 全 False（404）。
  - 项目成员/管理员判定复用 `ProjectMember`（has_project_access / 角色 owner/admin）。
  - 提供 async 版（`aresolve_conversation_access`）供 adrf。

### T3 — views.py 收口替换
- 把所有 owner gate 处改为调用 `resolve_conversation_access`：
  - 读类（detail / messages / runtime / SSE 构造前）→ `can_read`，否则 404。
  - 写类（send message / interrupt / 编辑历史）→ `can_write`，否则 403/404（保持现有越权语义：存在性用 404，权限用 403，参照现注释）。
  - 管理类（delete → `can_delete`；patch visibility → `can_set_visibility`；archive → `can_archive`）。
  - 列表（list 359）：返回「自己的全部会话」∪「自己为成员的项目的 shared 会话」；保持 `is_deleted=False`、默认 `is_archived=False`；支持 `bound_project`/`visibility` 过滤。
- SSE/interrupt 的 owner gate 必须在流构造/取消动作之前（保持现有 Pitfall 5 / T-08-11 注释约束）。

### T4 — serializer 扩展
- `CreateConversationSerializer`：+ `visibility`(default personal) + `bound_project_id`(可选)；校验 shared⇒bound_project 必填。
- `ConversationPatchSerializer`：+ `visibility`（互转）；视图层用 `can_set_visibility` 把关（共享→个人仅创建者）。
- `ConversationForkRequestSerializer`：+ `bound_project_id`(可选) + `visibility`(目标，默认 personal) —— 支持 clone 到三类之一。
- `ConversationListSerializer` / `ConversationDetailSerializer`：+ `visibility`、+ `created_by`(复用 `_OwnerBriefSerializer`)、+ `duration_ms`。
- `ConversationMessageSerializer`：确保含 `user`(复用 brief) + `created_at`（供 P3 头像/名字/相对时间）。
- 头像：`_OwnerBriefSerializer` 现为 {id,username,display_name}；若 `User` 有头像字段则补 `avatar_url`，否则前端用首字母色块（沿用现有 pattern）——本 Phase 不强制加头像字段。

### T5 — 单会话执行时长
- service 层 annotate `duration_ms`：取该会话所有 `OrchestrationRun` 运行时长之和（有 started/finished 取差值；缺字段时退化为 `updated_at-created_at` 或 0）。
- 仅 annotate 不落冗余真值（避免漂移）；list 用聚合查询批量算，detail 单算。

### T6 — fork（clone 贡献）后端
- 扩展现有 fork 动作：支持目标 `bound_project_id`+`visibility`；clone 出的会话 `created_by=request.user`。
- 共享会话"克隆发言"= 前端调 fork(target: bound_project=同项目, visibility=personal)。

### T7 — 观测 / 审计 / 脱敏
- create / patch(visibility 互转) / delete / fork：structlog `caller` 事件 + `duration_ms` + `component=chat.conversation` + 绑定 user。
- 互转、删除、越权尝试：审计留痕；异常文本 `redact_secrets_in_text`；非成员一律 404 不泄漏 provider/上下文。

### T8 — 测试
- 权限矩阵：个人隔离不破（他人 404）；shared 成员可读、非成员 404；非 owner 不可写；删除仅创建者/管理员；归档任意成员；visibility 互转权限（共享→个人仅创建者）。
- 列表：返回 自己全部 ∪ 成员项目 shared；`bound_project`/`visibility` 过滤生效。
- 序列化：`visibility`/`created_by`/`duration_ms`/message.user 存在且正确。
- fork：clone 到三类、created_by 归属正确。
- 迁移：存量默认 personal。

## 5. 验收标准
- 共享会话：项目成员可见可读，非 owner 输入被拒（写 403/404）；非成员 404。
- 删除限创建者+管理员；归档任意成员；互转受权限+（前端）二次确认。
- 列表正确合并个人与共享；过滤可用。
- 会话/消息返回贡献者(名)、时间、单会话 `duration_ms`。
- 个人会话隔离零回归；全部新增测试通过；async ORM 走 `sync_to_async`。

## 6. 风险与缓解
- **owner gate 散落十余处**：统一函数 + 逐处替换 + 权限矩阵测试兜底（最高风险）。
- **list 合并查询性能**：用 `Q(created_by=me) | Q(visibility=shared, bound_project__in=my_projects)` + 索引；my_projects 一次取。
- **duration 口径**：OrchestrationRun 计时字段不全时按退化口径，文档标注。

## 7. 衔接
- 上游：无（模型/权限地基）。下游：P3 消费序列化契约与 fork/visibility API。

---
*P2 完成后回填 `MILESTONE-PROPOSAL.md` §11 P2 状态。*
