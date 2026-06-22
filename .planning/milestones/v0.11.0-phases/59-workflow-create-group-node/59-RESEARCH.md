# Phase 59 Research: 工作流自动建群节点（CreateGroupChatNode）

**Researched:** 2026-06-17
**Requirements:** GROUP-01
**Goal answered:** "要把这个 phase 规划好，我需要知道什么？"
**Status:** Ready for planning

---

## TL;DR（规划前必读的一句话）

Phase 59 = 在 `FeishuIMClient`/`FeishuIMService` 新增 **`create_chat`（建群即拉人）** 一个方法（手写 httpx，复用 `get_tenant_access_token` + tenacity rate-limit + `code!=0 → FeishuIMError` 范式，对齐 `add_bot_to_chat`），新增 **`CreateGroupChatNode`** 工作流节点（`@register_node` 自动注册，镜像 `FetchGroupChatNode`/`JoinGroupChatNode` 结构、`execution_mode="server_local"`），节点产出 `chat_id` 一等输出供下游消费，并 **可选 writeback** 把 `chat_id` 写回 `WorkItem.feishu_chat_id` —— 经**新增 `WorkItemService.awriteback_feishu_chat_id`** 单一写入入口（INV-6，绝不进 `_MIRROR_FIELDS`），writeback 失败 **fail-soft**（warning + 节点仍 `completed` 返回 chat_id）；建群本身失败才走 `failed`+`error` handle。

**四个核心实证（已 READ 代码 + 官方文档验证）：**

1. **飞书 create chat 支持「建群即拉人」单步**（D-1，官方实证）：`POST /open-apis/im/v1/chats` body 直接带 `user_id_list`（最多 50）+ `bot_id_list`（最多 5），无需建群后再调 `add_chat_members`。⇒ **单步建群+拉人**，最小新增面。
2. **bot 自动入群 + owner 默认建群 bot**（F-2/F-3，官方实证）：操作此接口的机器人**自动入群无需填 `bot_id_list`**；`owner_id` 不填则**建群机器人为群主**。⇒ 节点不强制配 owner / 不需把自身 bot 塞进成员列表。
3. **`feishu_chat_id` 当前零写入入口**（F-5，已 READ）：`work_item_service.py:246-248` 注释明确 `_refresh_mirror` **绝不写** `feishu_chat_id`（不在 `_MIRROR_FIELDS`/`update_fields`）；全仓无任何 `feishu_chat_id` 写路径。⇒ 本 phase 须**新增**写入入口，且必须走 INV-6 单一收口（grep 守护已有范式 `test_inv6_guard.py`）。
4. **节点范式现成可镜像**（F-4，已 READ）：`FetchGroupChatNode`/`JoinGroupChatNode` 提供 `@register_node` + `config_schema` + `inputs/outputs(default+error)` + `FeishuIMService.create(project)` + `render_template` + `NodeResult(status="failed", next_handle="error")` 的完整范式，`CreateGroupChatNode` 直接照搬。

→ 规划落点：`feishu_im.py` 新增 `FeishuIMClient.create_chat` + `FeishuIMService.create_chat` 委托；`work_item_service.py` 新增 `awriteback_feishu_chat_id`；`workflows/nodes/integrations/feishu_chat.py` 新增 `CreateGroupChatNode`；四层守护测试（含 INV-6 grep 守护扩 `feishu_chat_id`）。**绝不改** `add_bot_to_chat`/`ensure_bot_in_chat`/`_refresh_mirror`/`_MIRROR_FIELDS`。

---

## 1. 需求锚点（逐字对齐 ROADMAP / REQUIREMENTS / CONTEXT / STATE）

- **GROUP-01**：新增"自动建群"工作流节点——可创建飞书群并拉入指定成员（替代现仅能 `add_bot_to_chat` 加入已有群），群 chat_id 作为节点输出可供下游节点 / 写回 `WorkItem.feishu_chat_id` 使用。
- **ROADMAP Phase 59 Success Criteria**（what must be TRUE）：
  1. 新增"自动建群"工作流节点可创建飞书群并拉入指定成员（替代仅能 `add_bot_to_chat` 加入已有群）；
  2. 新建群的 `chat_id` 作为节点输出可供下游节点引用；
  3. 可选把群 `chat_id` 写回 `WorkItem.feishu_chat_id`（writeback 字段，DOMAIN §1.2），失败 fail-soft 不阻断工作流。
- **STATE 约束**：
  - **INV-6 单一写入入口**：`feishu_chat_id` 写入收口到一个 service 方法，禁旁路写表，grep 守护无旁路（精神同 `AuditEvent` / `WorkItem` / `CommentEvent`）；
  - **writeback fail-soft**：写回飞书侧/DB 失败不阻断工作流（建群是主产物，writeback best-effort）；
  - **i18n 默认中文**：节点 `display_name`/`description`/`config_schema.title` 文案中文。
- **Out of Scope**（CONTEXT / REQUIREMENTS）：
  - 群管理全集（解散/转让群主/移除成员/改群信息）—— 仅**建群 + 拉人**；
  - 自动建群的触发/编排策略与去重（同一 work_item 重复建群防护）—— 本 phase 只提供节点，编排由用户连线；
  - 飞书卡片交互组件/多卡片编排（v2 OPENX-03）；
  - 真实飞书租户建群 E2E（需真实应用 + 真实用户 open_id）—— **deferred**（对齐既有飞书 E2E deferred 惯例）。

---

## 2. 关键事实清单（READ + 官方文档实证，不是推断）

### F-1：飞书 create chat 端点 / 鉴权 / 限频（官方文档实证 2026）

| 项 | 值 |
|----|-----|
| HTTP | `POST https://open.feishu.cn/open-apis/im/v1/chats` |
| 鉴权 | `tenant_access_token`（Bearer，复用 `get_tenant_access_token`） |
| 限频 | **1000 次/分钟、50 次/秒**（与 `add_bot_to_chat` 同档） |
| 权限 scope | `im:chat`（获取与更新群组信息）**或** `im:chat:create`（创建群），开启任一即可 |
| query 参数 | `user_id_type`（`open_id`(默认)/`union_id`/`user_id`）、`set_bot_manager`(bool，默认 false)、`uuid`(可选幂等键) |
| 响应 | `{"code":0,"msg":"...","data":{"chat_id":"oc_xxx","name":...,"owner_id":...,"owner_id_type":...,"chat_mode":...,...}}` |

**`OPEN_API_BASE` 复用**：`FeishuIMClient.OPEN_API_BASE = "https://open.feishu.cn/open-apis"` → `f"{self.OPEN_API_BASE}/im/v1/chats"`，与既有方法同源。

### F-2：create chat body 字段（官方文档逐字实证）

| 字段 | 类型 | 必填 | 说明（实证） |
|------|------|------|-------------|
| `name` | string | 否* | 群名称（中文名）。*飞书 API 层允许不填（默认"群聊"），但**本节点业务层要求必填**（见 D-4 缺参语义） |
| `description` | string | 否 | 群描述 |
| `i18n_names` | object | 否 | `{zh_cn,en_us,ja_jp}` 国际化群名（可选，默认中文 → 一般只填 name） |
| `owner_id` | string | 否 | 群主，**不填 → 建群机器人为群主**；ID 类型由 query `user_id_type` 决定，推荐 OpenID |
| `user_id_list` | string[] | 否 | 邀请的群成员，**最多 50**；ID 类型由 query `user_id_type` 决定 |
| `bot_id_list` | string[] | 否 | 邀请的群机器人（用 `app_id`）；**最多 5、群内 bot 总数 ≤15**；**操作此接口的 bot 自动入群无需填** |
| `chat_mode` | string | 否 | 群模式，默认 `group` |
| `chat_type` | string | 否 | `private`(默认)/`public` |
| `avatar` | string | 否 | 群头像 key（本 phase 不用） |

**最小请求 payload（节点产线形态）：**
```
POST /open-apis/im/v1/chats?user_id_type=open_id
Authorization: Bearer <tenant_access_token>
Content-Type: application/json
{
  "name": "需求 12345 协作群",
  "description": "由 Friday 工作流自动创建",
  "user_id_list": ["ou_xxx", "ou_yyy"]
}
```
（`owner_id` 省略 → bot 为群主；当前 bot 自动入群；`chat_mode` 默认 group。）

### F-3：bot 入群 / owner 约束（官方实证 —— 关键行为）

- **操作此接口的机器人会自动入群**，`bot_id_list` 仅用于额外邀请*其他*机器人。⇒ 节点**不需要**把 `self.app_id` 塞进任何列表来保证 bot 在群里（与 `add_bot_to_chat` 语义互补）。
- **`owner_id` 不填 → 建群 bot 为群主**；填了用户 owner 时，可用 query `set_bot_manager=true` 让 bot 同时成为管理员（本 phase 默认不设，owner 可选配置）。
- **当群主是机器人时**，响应 `owner_id`/`owner_id_type` **不返回**（输出群元信息时须容错缺字段）。

### F-4：节点范式现成（READ `feishu_chat.py`，本 phase 主镜像源）

`FetchGroupChatNode` / `JoinGroupChatNode`（`server/workflows/nodes/integrations/feishu_chat.py`）提供完整范式：
- `@register_node` 装饰器 + `node_type` / `display_name` / `description` / `icon` / `category = NodeCategory.INTEGRATION` / `execution_mode = "server_local"`；
- `config_schema`（JSON Schema，`properties` 带 `title`/`description`/`default`，中文文案）；
- `inputs = [NodePort("default", OBJECT)]`、`outputs = [NodePort("default","成功",OBJECT), NodePort("error","失败",OBJECT)]`；
- `async def execute(context) -> NodeResult`：`config = context.node_config` → `context.render_template(config.get(...))` 解析（支持模板变量）→ 取 project（`context.workflow_execution.workflow.project`）→ `im_service = await FeishuIMService.create(project)` → 调 service → 成功 `NodeResult(status="completed", output={...}, next_handle="default")` / 失败 `NodeResult(status="failed", error="...", next_handle="error")`；
- **自动注册**：放 `BaseNode` 子类于 `workflows/nodes/integrations/` 即被 `NodeRegistry._auto_discover()`（`registry.py:134`）pkgutil 扫描注册，**无需手动登记**。

`JoinGroupChatNode` 还示范 **config 优先、input_data 兜底** 取 chat_id（`config.get("chat_id")` 空则 `context.input_data.get("chat_id")`）——`CreateGroupChatNode` 取 work_item 标识时可同样支持上游注入。

### F-5：`feishu_chat_id` 当前零写入入口（READ，INV-6 关键）

- `WorkItem.feishu_chat_id = CharField(max_length=128, blank=True, default="")`（`work_item.py:69`，标 `# writeback（Friday 写回飞书再镜像）`）—— **字段已存在，无需 migration**。
- `WorkItemService._refresh_mirror`（`work_item_service.py:229-296`）注释逐字：**"绝不写 friday_enhanced … 与 writeback（feishu_chat_id）——它们不在 update_fields 内"**；`_MIRROR_FIELDS`（line 53-63）不含 `feishu_chat_id`。
- ⇒ **全仓无任何 `feishu_chat_id` 写路径**；新增 writeback 必须是独立写入方法，**绝不混进 `_MIRROR_FIELDS` / `_refresh_mirror`**。
- WorkItem 定位键 = 三元组 `(feishu_project_key, work_item_type, work_item_id)`（`unique_together`，`WorkItemIdentity` dataclass，`work_item.py:82` + `work_item_service.py:95-101`）。

### F-6：INV-6 grep 守护范式（READ `test_inv6_guard.py`）

- `server/tests/delivery/test_inv6_guard.py` 已守护 `WorkItem.objects.<write>` / `WorkItem(...)` 实例化只允许出现在 `delivery/services/work_item_service.py`（`_ALLOWED_WRITER`），扫描 server/ 源码（剪 venv/缓存/tests/migrations/models）。
- 本 phase 的 writeback 走 `WorkItemService` 方法 → **天然落在 `_ALLOWED_WRITER` 内**，不破现有 INV-6 守护。
- **新增针对 `feishu_chat_id` 的正向守护**：grep 断言"`feishu_chat_id` 的赋值/save 只出现在 `work_item_service.py`"（防后续旁路把 chat_id 写进别处），范式镜像 `test_inv6_guard.py::test_inv6_writer_module_actually_writes`。

### F-7：FeishuIMService.create 凭证解析（READ）

- `FeishuIMService.create(project)`（`feishu_im.py:892`）→ `create_feishu_im_client_for_project(project)`：project 级飞书 app_id/secret → 系统级 `SettingKeys.FEISHU_APP_ID/SECRET` → fallback 任一配置 project；都没有 → `raise ValueError`。节点取 `project = context.workflow_execution.workflow.project` 传入即可（与 `FetchGroupChatNode` 一致）。

---

## 3. 核心决策（已自主拍板，无人值守，无遗留待裁决）

### D-1：建群即拉人 —— 单步 `POST /im/v1/chats`（body 带 user_id_list），**不**两步 add_chat_members

官方实证（F-2）：create chat body 直接支持 `user_id_list`（≤50）+ `bot_id_list`（≤5）。⇒ `create_chat` **一次调用**完成建群+拉人，无需建群后再 `POST /im/v1/chats/{id}/members`。**理由**：① 官方原生支持，最小调用面/最小新增；② 原子性更好（避免建群成功但拉人失败的半态）；③ 成员超 50 的分批拉人不在本 phase scope（CONTEXT Out of Scope，可后续加）。**已决。**

### D-2：`create_chat` 手写 httpx，复用 `add_bot_to_chat` 基建

`FeishuIMClient.create_chat` 复用 `get_tenant_access_token()` + `httpx.AsyncClient` + `data.get("code")==0` 判定 + structlog + **tenacity rate-limit 重试**（`@retry` `retry_if_exception_type(RateLimitError)`，对齐 `send_card`/`add_bot_to_chat` 的 99991400 处理），`code!=0 → raise FeishuIMError`。放置：直接进 `feishu_im.py`（群聊成员管理区块下，与 `add_bot_to_chat` 同类）。**不**用 lark-oapi SDK（全仓 IM 手写 httpx，端点已 100% 确认，SDK 无确定性收益——同 Phase 58 D-1）。**已决。**

**方法签名（建议给 plan）：**
```
async def create_chat(
    self,
    name: str,
    *,
    user_id_list: list[str] | None = None,
    bot_id_list: list[str] | None = None,
    owner_id: str = "",
    description: str = "",
    user_id_type: Literal["open_id", "union_id", "user_id"] = "open_id",
    set_bot_manager: bool = False,
) -> dict[str, Any]:
    """创建飞书群并拉入成员，返回 data（含 chat_id）。code!=0 抛 FeishuIMError。"""
```
- query：`{"user_id_type": user_id_type}`（+ `set_bot_manager` 仅当 owner_id 非空且需设管理员）；
- body：仅放非空字段（`name` 恒放；`user_id_list`/`bot_id_list`/`owner_id`/`description` 非空才放）；
- 返回 `data.get("data", {})`（节点取 `data["chat_id"]`）。

### D-3：`FeishuIMService.create_chat` 委托方法（节点经 service 调用）

镜像既有 `ensure_bot_in_chat`/`get_chat_id_for_work_item` 委托范式：`FeishuIMService.create_chat(...)` 透传给 `self.client.create_chat(...)`，返回 `dict`（含 chat_id + 群元信息）。节点经 `FeishuIMService.create(project)` 取实例后调用（与 `FetchGroupChatNode` 对称）。**已决。**

### D-4：`CreateGroupChatNode` 设计 —— 镜像 feishu_chat 节点

- `node_type = "create_group_chat"`、`display_name = "创建群聊"`、`icon = "users"`(或 "message-circle-plus")、`category = NodeCategory.INTEGRATION`、`execution_mode = "server_local"`。
- `config_schema.properties`（全中文 title/description）：
  - `name`（群名，**业务必填**，支持模板变量）；
  - `description`（群描述，可选）；
  - `owner_id`（群主 open_id，可选，留空 → bot 为群主）；
  - `member_ids`（成员 ID 列表，支持模板变量；**格式见 D-5**）；
  - `user_id_type`（默认 `open_id`，枚举 open_id/union_id/user_id）；
  - **writeback 三件套（可选）**：`project_key` / `work_item_id` / `work_item_type`（默认 `story`）—— **命名与 `FetchGroupChatNode` 完全一致**（降低用户认知成本，CONTEXT the agent's Discretion 倾向一致）。
- `inputs = [NodePort("default","输入",OBJECT)]`；`outputs = [NodePort("default","成功",OBJECT), NodePort("error","失败",OBJECT)]`。
- `execute`：解析 name/member_ids（render_template）→ **name 或 member_ids 缺 → `failed`+error**（缺参语义，对齐 `FetchGroupChatNode` 缺 work_item 参数）→ 取 project + `FeishuIMService.create` → `create_chat` →（成功）取 `chat_id` →（可选）writeback fail-soft → `completed` 输出 chat_id。
- **缺参判定**：群名为空 **或** 成员列表为空 → `NodeResult(status="failed", error="缺少群名/成员", next_handle="error")`（"建群并拉入指定成员"是 SC-1 核心语义，空成员无意义）。**已决。**

### D-5：`member_ids` 配置格式 —— 复用 `normalize_repositories` 同款解析（逗号分隔 / JSON 列表 / 模板）

`base.py` 已有 `normalize_repositories`（line 667-787）的成熟解析：支持 **JSON 对象数组 / JSON 字符串数组 / 逗号分隔字符串 / 模板变量 `{{...}}`**。`member_ids` 解析**复用同款思路**（plan 可抽一个轻量 `_parse_id_list(value, context) -> list[str]`，或在节点内内联）：
- 模板变量 → `context.get_template_value`（保留 list 类型，上游可注入 `["ou_a","ou_b"]`）；
- 字符串 → 优先 JSON 解析（`["ou_a","ou_b"]`），否则逗号分隔（`ou_a, ou_b`）；
- list → 逐项 str 化去空。
**默认建议**：节点 UI 文案标注「逗号分隔 或 JSON 列表，支持 `{{nodes.x.member_ids}}` 模板」。**user_id_type 默认 `open_id`**（飞书默认 + 推荐，F-1）。**已决。**

### D-6：writeback 单一入口 —— 扩 `WorkItemService.awriteback_feishu_chat_id`（**不**新建 service）

**落点决策**：在既有 `WorkItemService` 新增 async 方法（**不**新建轻量 service），因为 ① INV-6 守护 `test_inv6_guard.py` 已把 `WorkItem` 唯一 writer 锚定为 `work_item_service.py`，复用即天然合规、无需扩守护白名单；② WorkItem 定位逻辑（三元组）已在该 service；③ 最小新增面。

**方法签名 + 实现契约（给 plan）：**
```
async def awriteback_feishu_chat_id(
    self,
    feishu_project_key: str,
    work_item_type: str,
    work_item_id: int,
    chat_id: str,
) -> bool:
    """把建群 chat_id 写回 WorkItem.feishu_chat_id（writeback 单一入口，INV-6）。

    三元组定位 WorkItem；save(update_fields=["feishu_chat_id", "updated_at"])。
    WorkItem 不存在 → 返回 False（不抛，调用方 fail-soft）。
    绝不进 _MIRROR_FIELDS / _refresh_mirror。
    """
```
- 用 `@sync_to_async` 包同步块：`WorkItem.objects.filter(三元组).first()`；无 → 返回 False；有 → `wi.feishu_chat_id = chat_id; wi.save(update_fields=["feishu_chat_id", "updated_at"])`；返回 True。
- **绝不**触碰 `_MIRROR_FIELDS` / `field_provenance` 的 mirror 语义（writeback 是独立来源，可选记 `field_provenance["feishu_chat_id"]="workflow_create_group"` —— plan 自决，非必需）。
**已决。**

### D-7：fail-soft 边界 —— 建群失败 vs writeback 失败两类分开

| 失败类型 | 处理 | 节点结果 |
|---------|------|---------|
| **建群失败**（`create_chat` 抛 `FeishuIMError`/缺参） | `try/except FeishuIMError` 捕获 | `NodeResult(status="failed", error=..., next_handle="error")` —— 主产物失败，走 error handle |
| **writeback 失败**（WorkItem 不存在 / DB 异常） | `try/except Exception` + 结构化 `log.warning` | **节点仍 `completed`**，output 含 chat_id（writeback best-effort，绝不冒泡） |

writeback **仅当** 配了 work_item 标识（`project_key` + `work_item_id` 均非空）才执行；未配 → 跳过（正常 completed）。建群成功是 SC-1/SC-2 主交付，writeback 是 SC-3 可选附加。**已决。**

### D-8：节点输出形状 —— chat_id 一等字段 + 群元信息

```
output = {
    "chat_id": chat_id,                # 一等字段，下游 JoinGroupChatNode/发卡节点直接消费
    "chat_name": data.get("name", ""),
    "owner_id": data.get("owner_id", ""),   # bot 为群主时飞书不返回，容错空串
    "source": "create_group_chat",
    "writeback": {"attempted": bool, "success": bool},  # 可选，writeback 状态透出
}
```
与 `FetchGroupChatNode` 输出 `chat_id`/`source` 对称，下游 `JoinGroupChatNode`（`config.get("chat_id")` 空则读 `input_data["chat_id"]`）可直接串联。**已决。**

---

## 4. 推荐改动落点（给 plan 的最小可执行清单）

1. **`server/services/feishu_im.py`（新增，不改既有签名）**：
   - `FeishuIMClient.create_chat(name, *, user_id_list, bot_id_list, owner_id, description, user_id_type, set_bot_manager) -> dict`（POST `/im/v1/chats`，query `user_id_type`(+`set_bot_manager`)，body 仅非空字段，`@retry` rate-limit，`code!=0 → FeishuIMError`，返回 `data`）。
   - `FeishuIMService.create_chat(...)` 委托方法。
   - 复用 `get_tenant_access_token` / httpx / structlog / tenacity / `RateLimitError`（99991400）。
2. **`server/delivery/services/work_item_service.py`（新增方法）**：
   - `WorkItemService.awriteback_feishu_chat_id(feishu_project_key, work_item_type, work_item_id, chat_id) -> bool`（三元组定位 + `save(update_fields=["feishu_chat_id","updated_at"])`，不存在返回 False，绝不进 `_MIRROR_FIELDS`）。
3. **`server/workflows/nodes/integrations/feishu_chat.py`（新增节点）**：
   - `CreateGroupChatNode(BaseNode)` `@register_node`（自动注册），按 D-4/D-5/D-7/D-8。
   - 成员解析 helper（复用 `normalize_repositories` 思路，可抽 `_parse_id_list`）。
4. **守护测试**（落 `server/tests/`）：见 §5 四层架构。
5. **零回归保护**：`add_bot_to_chat`/`ensure_bot_in_chat`/`get_chat_members`/`_refresh_mirror`/`_MIRROR_FIELDS`/`FetchGroupChatNode`/`JoinGroupChatNode` 逐字不变；既有 `test_feishu_im.py` / delivery work_item 测试全绿。

---

## 5. Validation Architecture（供 VALIDATION.md 生成 / nyquist 校验）

四层可验证测试架构。mock 范式沿用既有 `test_feishu_im.py`（`patch httpx.AsyncClient` + `_make_client()` 预置 token + `_mock_response`）。

### 5.1 `create_chat` httpx 形状纯单测（mock httpx，扩 `test_feishu_im.py`）
- 断言 POST `/im/v1/chats`、query `user_id_type=open_id`；
- body 含 `name`、`user_id_list`（成员 id_list 正确传入）；空字段不放（`owner_id`/`description` 省略时 body 无该键）；
- 成功 → 返回 `data`，`result["chat_id"]` 命中（mock `{"code":0,"data":{"chat_id":"oc_new"}}`）；
- `code!=0` → 抛 `FeishuIMError`（如 `{"code":230002,"msg":"no permission"}`）；
- rate-limit（99991400）→ `RateLimitError`（tenacity 重试范式，可断言抛 RateLimitError）。
- **mock 点**：`patch("httpx.AsyncClient")`，无 DB。

### 5.2 节点集成测（mock `FeishuIMService.create_chat`）
- happy path：mock `FeishuIMService.create` 返回带 `create_chat=AsyncMock(return_value={"chat_id":"oc_x","name":"群"})` 的服务 → 节点 `execute` → 断言 `status=="completed"`、`next_handle=="default"`、`output["chat_id"]=="oc_x"`；
- 缺群名 → `failed`+`next_handle=="error"`；
- 缺成员（member_ids 空）→ `failed`+`error`；
- `create_chat` 抛 `FeishuIMError` → `failed`+`error`（建群失败走 error handle，D-7）；
- member_ids 解析：逗号分隔 `"ou_a, ou_b"` / JSON `["ou_a","ou_b"]` / 模板 `{{nodes.x.ids}}` 三形态 → 断言传入 `user_id_list==["ou_a","ou_b"]`。
- **mock 点**：`patch FeishuIMService.create`（AsyncMock）+ 构造 `ExecutionContext`（含 `workflow_execution.workflow.project`，参考既有节点测试构造）。

### 5.3 writeback happy + fail-soft 测
- 配 work_item 标识 + mock `WorkItemService.awriteback_feishu_chat_id` 返回 True → 断言被调用（三元组 + chat_id 入参正确）、节点 `completed`；
- **fail-soft**：`awriteback_feishu_chat_id` 抛 `Exception`（DB 异常）→ 断言节点**仍 `completed`** + `output["chat_id"]` 在、异常**不冒泡**、有 warning；
- WorkItem 不存在（返回 False）→ 节点 `completed`、`output["writeback"]["success"]==False`；
- 未配 work_item 标识 → 不调 writeback、`completed`。
- **service 层单测**（DB 测，`@pytest.mark.django_db`）：建 WorkItem → `awriteback_feishu_chat_id` → reload 断言 `feishu_chat_id` 写入；**断言 mirror 字段（title/status 等）未被动**（writeback 不污染 mirror）；WorkItem 不存在 → 返回 False 不抛。

### 5.4 INV-6 grep 守护 + 零回归
- **INV-6 守护**（扩/新增 grep 守护测试，镜像 `test_inv6_guard.py`）：
  - 既有 `test_inv6_no_bypass_work_item_write` 仍绿（writeback 经 `WorkItemService` → 天然合规）；
  - **新增** `feishu_chat_id` 写入正向守护：grep 断言 `feishu_chat_id` 的赋值 + save 只出现在 `work_item_service.py`（防旁路），并断言 `awriteback_feishu_chat_id` 确实写 `feishu_chat_id`（守护有效性，否则断言形同虚设）。
- **零回归**：`test_feishu_im.py`（群方法/IM）+ delivery `work_item_service` 测试 + 既有 feishu_chat 节点测试全绿；`_MIRROR_FIELDS` 不含 `feishu_chat_id`（断言）、`_refresh_mirror` 不写 `feishu_chat_id`（grep/快照）。
- 真实飞书租户建群 E2E（需真实 open_id）→ **deferred**（人工验收，对齐既有飞书 E2E deferred）。
- **测试命令**：`cd server && uv run pytest tests/ -q -k "feishu or work_item or create_group or inv6"`（plan 核对实际选择器）。

### Nyquist 采样覆盖矩阵（每个需求/约束 ≥1 可验证断言）
| 需求/约束 | 验证层 | 断言要点 |
|-----------|--------|----------|
| GROUP-01 / SC-1（建群+拉人） | 5.1 + 5.2 | POST /im/v1/chats body 带 user_id_list、节点 completed |
| SC-2（chat_id 节点输出） | 5.2 | `output["chat_id"]` 一等字段、下游可消费 |
| SC-3（writeback + fail-soft） | 5.3 | writeback 写入 feishu_chat_id；失败节点仍 completed 不冒泡 |
| 建群即拉人单步（D-1） | 5.1 | 单次 POST 含成员，无第二次 add_members 调用 |
| 缺参 error handle（D-4） | 5.2 | 缺群名/成员 → failed + next_handle=error |
| 建群失败 error（D-7） | 5.2 | FeishuIMError → failed + error |
| writeback 不污染 mirror | 5.3 | service 测断言 mirror 字段未动、不进 _MIRROR_FIELDS |
| INV-6 单一写入入口 | 5.4 | grep 守护 feishu_chat_id 仅经 work_item_service |
| member_ids 多格式（D-5） | 5.2 | 逗号/JSON/模板三形态 → user_id_list 正确 |
| 零回归 | 5.4 | test_feishu_*/work_item 全绿、既有方法逐字不变 |
| i18n 中文（STATE） | 5.2 | 节点 display_name/config title 中文 |

---

## 6. Pitfalls / 约束（execute 时易踩）

- **P-1 user_id_type 一致性**：`owner_id` 与 `user_id_list` 的 ID 类型**必须与 query `user_id_type` 一致**（都 open_id 或都 user_id），混用 → 飞书报错/拉人失败。节点默认 `open_id`，文案须提示「成员 ID 与 owner 用同一类型」。
- **P-2 bot 自动入群，勿重复塞**：操作接口的 bot **自动入群**（F-3），不要把 `self.app_id` 塞进 `bot_id_list`/`user_id_list`（user_id_list 是 user open_id，塞 app_id 会报错）。`bot_id_list` 仅用于额外邀请其他 bot（本 phase 一般留空）。
- **P-3 owner 为 bot 时响应缺字段**：群主是机器人时响应 **不返回 `owner_id`/`owner_id_type`**（F-3）。输出群元信息须 `data.get("owner_id","")` 容错，**不可** assert owner_id 必有。
- **P-4 成员上限**：`user_id_list` ≤50、`bot_id_list` ≤5（群内 bot ≤15）。超限飞书报错；本 phase 不做分批（Out of Scope），但节点对超长列表应让 API 错误如实走 error handle（不静默截断）。
- **P-5 writeback 绝不污染 mirror（INV-6 命门）**：`awriteback_feishu_chat_id` 只 `save(update_fields=["feishu_chat_id","updated_at"])`，**绝不**把 `feishu_chat_id` 加进 `_MIRROR_FIELDS`、绝不在 `_refresh_mirror` 里写它（sync 会覆盖回空！）。这是 writeback vs mirror 三分类（DOMAIN §1.2）的核心边界。
- **P-6 INV-6 旁路防护**：writeback 必须经 `WorkItemService` 方法，**禁**在节点里直接 `WorkItem.objects.filter(...).update(...)` 或 `wi.save()`（会被 `test_inv6_guard.py` grep 命中 fail）。节点只调 service 方法。
- **P-7 fail-soft 边界两类分开（D-7）**：「建群失败」（主产物失败 → error handle）≠「writeback 失败」（best-effort → 仍 completed）。不可把建群失败也 fail-soft 吞掉（否则下游拿不到 chat_id 还以为成功）；也不可让 writeback 失败掀翻整节点。
- **P-8 限频（50/s、1000/min）**：与 `add_bot_to_chat` 同档，复用 `RateLimitError`（99991400）+ tenacity 指数退避。工作流批量建群场景须注意（本 phase 单次建群，风险低）。
- **P-9 scope 权限**：建群需 `im:chat` 或 `im:chat:create` scope；未开通 → `code` 权限错（如 230002）→ `FeishuIMError` → 节点 error handle（如实暴露，不静默）。文档/节点说明须提示该 scope。
- **P-10 async / ruff 约定**：方法 `async def` + `httpx.AsyncClient`；line length 100、注释/docstring 中文、import 排序（ruff I）；ORM 写经 `sync_to_async`（writeback 方法）。与既有 `feishu_im.py`/`work_item_service.py` 风格一致。
- **P-11 work_item_id 类型**：节点配置 `work_item_id` 是 string（模板渲染后），writeback 需 `int(work_item_id)`；转换失败应 fail-soft（warning，跳过 writeback，不掀翻建群成功）—— 对齐 `FetchGroupChatNode` 的 `int()` 容错（但那里是 error，本处因 writeback best-effort 故 warning 跳过）。
- **P-12 节点自动注册零配置**：放进 `workflows/nodes/integrations/feishu_chat.py` 即被 `_auto_discover` 注册；`node_type` 须**全局唯一**（不可与既有 `fetch_group_chat`/`join_group_chat` 撞），用 `create_group_chat`。前端 `node-definitions.json` 的 ui_schema 为可选注入（缺失不影响后端注册，`get_ui_schema` 返回 None 容错）。

---

## 7. Open Questions（plan 阶段已自主决断，无遗留）

- **OQ-1 建群即拉人 vs 两步** → D-1：单步 POST /im/v1/chats（body 带 user_id_list，官方支持）。**已决。**
- **OQ-2 writeback service 落点** → D-6：扩 `WorkItemService.awriteback_feishu_chat_id`（不新建 service，复用 INV-6 守护白名单）。**已决。**
- **OQ-3 member_ids 格式** → D-5：逗号分隔 / JSON 列表 / 模板三形态（复用 `normalize_repositories` 思路），`user_id_type` 默认 `open_id`。**已决。**
- **OQ-4 owner / bot 入群** → D-2/F-3：owner 可选（留空 bot 为群主），bot 自动入群不重复塞。**已决。**
- **OQ-5 fail-soft 边界** → D-7：建群失败走 error handle，writeback 失败仍 completed。**已决。**
- **OQ-6 节点 work_item 参数命名** → D-4：复用 `FetchGroupChatNode` 的 `project_key`/`work_item_id`/`work_item_type`（一致性）。**已决。**

---

## RESEARCH COMPLETE

**核心发现**：Phase 59 在 `FeishuIMClient`/`FeishuIMService` 手写 httpx 新增 **`create_chat`（建群即拉人，单步 `POST /im/v1/chats`，官方实证 body 带 `user_id_list`≤50 + `bot_id_list`≤5，query `user_id_type` 默认 open_id，复用 token/tenacity/`code!=0→FeishuIMError` 基建）**，新增 **`CreateGroupChatNode`**（`@register_node` 自动注册，镜像 `FetchGroupChatNode`，`execution_mode=server_local`，config 群名/描述/owner/member_ids（逗号|JSON|模板）/可选 work_item writeback 三件套，输出 `chat_id` 一等字段供下游），并经**新增 `WorkItemService.awriteback_feishu_chat_id` 单一写入入口（INV-6）** 可选写回 `WorkItem.feishu_chat_id`（三元组定位 + `save(update_fields=["feishu_chat_id"])`，**绝不进 `_MIRROR_FIELDS`/`_refresh_mirror`**——当前该字段零写入入口）。fail-soft 两类分开：建群失败→`failed`+error handle；writeback 失败→节点仍 `completed` 返回 chat_id（best-effort warning，不冒泡）。给出 3 文件落点、四层 Validation（create_chat httpx 形状单测 / 节点集成 mock service / writeback happy+fail-soft+service DB 测 / INV-6 grep 守护+零回归）、Nyquist 全需求覆盖矩阵、12 条 pitfalls（user_id_type 一致性 / bot 自动入群勿重塞 / owner 为 bot 响应缺字段 / 成员上限 / writeback 不污染 mirror / INV-6 旁路防护 / fail-soft 两类边界 / 限频 / scope 权限 / async-ruff / work_item_id 转换 / 自动注册唯一 node_type）。关键决策 D-1（建群即拉人单步）/D-6（writeback 扩 WorkItemService）/D-5（member_ids 三形态）均自主拍板，无遗留；真实租户 E2E 记 deferred。
