---
phase: 59
slug: workflow-create-group-node
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 59 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. 源自 59-RESEARCH.md §5 四层 Validation Architecture + Nyquist 覆盖矩阵。**纯增量 phase**——新增 `FeishuIMClient.create_chat`（建群即拉人单步）+ `FeishuIMService.create_chat` 委托 + `WorkItemService.awriteback_feishu_chat_id`（writeback 单一入口，INV-6）+ `CreateGroupChatNode`（自动注册节点）。`add_bot_to_chat`/`ensure_bot_in_chat`/`_refresh_mirror`/`_MIRROR_FIELDS`/`FetchGroupChatNode`/`JoinGroupChatNode` **必须逐字保持全绿**（零回归底线）。fail-soft 两类分开：建群失败→`failed`+error handle；writeback 失败→节点仍 `completed` 返回 chat_id（warning 不冒泡）。`feishu_chat_id` 写入**绝不进** `_MIRROR_FIELDS`/`_refresh_mirror`（INV-6 命门）。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio + pytest-django) |
| **Config file** | `server/pyproject.toml` ([tool.pytest]) |
| **Quick run command** | `cd server && uv run pytest tests/services/test_feishu_im.py -q`（Wave 1 封装）/ `cd server && uv run pytest tests/workflows/test_chat_nodes.py -q`（Wave 2 节点） |
| **Full suite command** | `cd server && uv run pytest tests/services/test_feishu_im.py tests/workflows/test_chat_nodes.py tests/delivery/test_work_item_writeback.py tests/delivery/test_inv6_guard.py -q` |
| **Estimated runtime** | ~20 秒 |

---

## Sampling Rate

- **After every task commit:** Run 对应改动文件的快测（Wave 1 → `tests/services/test_feishu_im.py` + `tests/delivery/test_work_item_writeback.py` + `tests/delivery/test_inv6_guard.py`；Wave 2 → `tests/workflows/test_chat_nodes.py`）
- **After every plan wave:** Run full suite command（含 INV-6 grep 守护 + 既有 feishu_im 群方法 + 既有 feishu_chat 节点——零回归门禁）
- **Before `$gsd-verify-work`:** 上述 full suite 全绿
- **Max feedback latency:** 30 秒

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 59-01-1 FeishuIMClient.create_chat + Service 委托 | 01 | 1 | GROUP-01 | T-59-01 | 端点 `POST /im/v1/chats`、query `user_id_type=open_id`、body 仅非空字段；`code!=0` → `FeishuIMError`；token 复用 `get_tenant_access_token`；rate-limit(99991400) → `RateLimitError` | unit | `cd server && uv run pytest tests/services/test_feishu_im.py -q` | ✅ (扩展) | ⬜ pending |
| 59-01-2 WorkItemService.awriteback_feishu_chat_id + INV-6 守护 | 01 | 1 | GROUP-01 | T-59-02 | 三元组定位 + `save(update_fields=["feishu_chat_id","updated_at"])`；不存在返回 False 不抛；**绝不**写 `_MIRROR_FIELDS`/mirror 字段；INV-6 grep 守护 `feishu_chat_id` 写入仅在 work_item_service.py | unit + db | `cd server && uv run pytest tests/delivery/test_work_item_writeback.py tests/delivery/test_inv6_guard.py -q` | ❌ W0 (新文件) | ⬜ pending |
| 59-02-1 CreateGroupChatNode 建群→输出 chat_id + member_ids 三形态 | 02 | 2 | GROUP-01 | T-59-03 | 缺群名/成员 → `failed`+`error`；建群失败(`FeishuIMError`) → `failed`+`error`（主产物失败走 error handle，D-7）；member_ids 逗号/JSON/模板 → `user_id_list` 正确；`output["chat_id"]` 一等字段 | integration | `cd server && uv run pytest tests/workflows/test_chat_nodes.py -q` | ✅ (扩展) | ⬜ pending |
| 59-02-2 节点 writeback fail-soft + 自动注册 | 02 | 2 | GROUP-01 | T-59-04 | 配 work_item 标识 → 调 `awriteback_feishu_chat_id`；writeback 抛错/返回 False → 节点**仍 completed** 返回 chat_id（warning 不冒泡，best-effort）；未配标识 → 不调 writeback；`node_type=="create_group_chat"` 经 `@register_node` 自动注册 | integration | `cd server && uv run pytest tests/workflows/test_chat_nodes.py -q` | ✅ (扩展) | ⬜ pending |
| 59-零回归 | 01/02 | 1+2 | GROUP-01 | T-59-05 | `add_bot_to_chat`/`ensure_bot_in_chat`/`get_chat_members`/`_refresh_mirror`/`_MIRROR_FIELDS`/`FetchGroupChatNode`/`JoinGroupChatNode` 符号逐字不变；既有 feishu_im / feishu_chat 节点测试全绿 | integration | `cd server && uv run pytest tests/services/test_feishu_im.py tests/workflows/test_chat_nodes.py tests/delivery/test_inv6_guard.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/delivery/test_work_item_writeback.py` — **新文件**：`WorkItemService.awriteback_feishu_chat_id` 的 DB 单测（`@pytest.mark.django_db`）：建 `WorkItem` → 调用 → reload 断言 `feishu_chat_id` 写入；**断言 mirror 字段（title/status_state_key 等）未被动**（writeback 不污染 mirror，P-5）；WorkItem 不存在 → 返回 `False` 不抛。
- [ ] `server/tests/delivery/test_inv6_guard.py` — **扩展既有文件**：新增 `feishu_chat_id` 正向 grep 守护——断言 `feishu_chat_id` 的赋值/`save` 只出现在 `delivery/services/work_item_service.py`（防旁路），并断言 `awriteback_feishu_chat_id` 确实写 `feishu_chat_id`（守护有效性，镜像 `test_inv6_writer_module_actually_writes` 范式）。既有 INV-6/INV-3 测试逐字保留。
- [ ] `server/tests/services/test_feishu_im.py` — **扩展既有文件**：新增 `create_chat` httpx 形状单测，复用既有 `_make_client()`（预置 `_tenant_token`）+ `_mock_response()` + `patch("httpx.AsyncClient")` 范式（无 DB）。
- [ ] `server/tests/workflows/test_chat_nodes.py` — **扩展既有文件**：新增 `CreateGroupChatNode` 集成测，复用既有 `_make_context()` + `_mock_im_service()` + `patch(...FeishuIMService.create)` 范式。

*既有 `test_feishu_im.py`（`_make_client`/`_mock_response`/`patch httpx.AsyncClient`）、`test_chat_nodes.py`（`_make_context`/`_mock_im_service`/`patch FeishuIMService.create`）、`test_inv6_guard.py`（grep 守护 + `_ALLOWED_WRITER`）三套范式可直接复用，框架（pytest/pytest-django）已在 `server/pyproject.toml` 依赖，无需安装。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实飞书租户建群 + 拉入真实成员端到端成功 | GROUP-01 / Success #1·#2 | 需真实飞书应用（已开通 `im:chat` 或 `im:chat:create` scope）+ 真实用户 `open_id` 列表，自动化无法验证真实租户副作用 | 配置飞书 App + 真实成员 open_id，在工作流中放 `CreateGroupChatNode` 跑一次 → 飞书客户端确认新群已建、指定成员已拉入、bot 自动入群、`chat_id` 输出可被下游 `JoinGroupChatNode` 消费；配 work_item 标识 → 确认 `WorkItem.feishu_chat_id` 写回 |

*其余 phase 行为（端点/payload/user_id_type 形状、建群即拉人单步、member_ids 三形态解析、缺参/建群失败 error handle、writeback happy/fail-soft、INV-6 单一入口、mirror 不污染、零回归）均有自动化验证。真实租户 E2E 对齐既有飞书 E2E deferred 惯例。*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
