# 82-02 Summary — 项目工作区写入与外呼层

**Plan:** 82-02 (wave 2) · **Status:** 完成 · **Date:** 2026-06-26

## 交付内容

兑现 WS-04 / DOC-01~06（单向首建落地，不含 Phase 83 双向同步）。

### 新增/修改文件

| 文件 | 改动 |
|------|------|
| `server/services/feishu_doc.py` | 新增 `FeishuDocClient.create_folder(name, folder_token) -> str`，镜像 `create_document` 的 token/headers/@retry/错误码（`99991400`/rate limit → `RateLimitError` 退避；非 0 → `FeishuDocAPIError`；缺 token → `FeishuDocAPIError`）。端点 `POST /drive/v1/files/create_folder`。 |
| `server/initiatives/services/project_doc_service.py` | **新建** `ProjectDocService`：三模型唯一写入入口（`upsert_doc` / `set_doc_feishu` / `set_sync_status` / `upsert_block_map` / `upsert_state_api` / `remove_state_api`）+ `provision_dispatch` / `_provision_workspace_coro` / `rebuild_workspace` 后台编排。 |
| `server/initiatives/services/project_service.py` | 新增 `set_folder_token`（专用方法，不进 update 白名单）+ 审计 `project.workspace_provisioned`；`create()` 成功后 best-effort `ProjectDocService().provision_dispatch(...)`（函数级 import，吞异常不阻断）。 |
| `server/initiatives/services/__init__.py` | re-export `ProjectDocService`。 |
| `server/audit/services/taxonomy.py` | 三处登记 `ACTION_PROJECT_WORKSPACE_PROVISIONED` / `ACTION_PROJECT_STATE_API_ADDED` / `ACTION_PROJECT_STATE_API_REMOVED`。 |
| `server/tests/services/test_feishu_doc_create_folder.py` | **新建** create_folder 四形状 + 限流退避（patch `asyncio.sleep` 瞬时）。 |
| `server/tests/initiatives/test_project_doc_service.py` | **新建** 写入/幂等 + set_folder_token + provision happy/broken/无父文件夹/看板幂等 + 静态守护（无 `asyncio.gather(`、脱敏在用、日志无 token/正文）。 |
| `server/tests/initiatives/test_project_doc_inv6_guard.py` | **新建** 三模型 INV-6 grep 守护 + writer-actually-writes 有效性断言。 |

### 编排关键点（已落地）

- 串行：文件夹 → 5 文件 → 互链 → 看板，全程 `await`，无 `asyncio.gather`（5QPS/不可并发）。
- fail-soft：无父文件夹/无凭证 → 5 doc 置 `broken`；单文件失败置该 doc `broken` 并继续；任一外呼失败不抛、不阻断建项目。`broken` 持久化 DB（重启不丢，供一键重建）。
- 归因：`provision_dispatch` 经 `run_in_background(initiated_by_user_id=)`，worker 入口 re-bind；coro 直接收 `initiated_by_user_id` 用于 `set_folder_token` 审计；未知记 `system`。
- 观测：`project_workspace_provision_started/completed/failed` + `duration_ms` + ready/broken 计数 + `component=initiatives` / `category=caller`。
- 脱敏：飞书上游异常文本经 `redact_secrets_in_text` 后入日志；日志只记 doc_id/doc_type/计数/sync_status。
- DOC-06：5 文件就绪后头部 `append_markdown` 互链（block 级，绝不整篇 replace）；看板描述 read-then-append「📁 项目工作区」段（marker 幂等）。

## 测试结果

- `tests/services/test_feishu_doc_create_folder.py` — 5 passed
- `tests/initiatives/test_project_doc_service.py` + `test_project_doc_inv6_guard.py` — 19 passed
- 既有零回归：`test_project_inv6_guard` / `test_artifact_inv6_guard` / `tests/audit/` / `test_project_service` — 95 passed
- INV-6 red/green 自检：注入旁路写 → 红；移除 → 绿（已验证）
- `makemigrations --check --dry-run` — No changes detected
- `ruff check`（全部改动文件）— All checks passed

## Deferred / 待 live 验证（不阻断）

- **A1**：`create_folder` 端点形态（`POST /drive/v1/files/create_folder`，body `{name, folder_token}`，返回 `data.token`）按 MILESTONE-PROPOSAL §10 + `create_document` 约定实现，已 fail-soft，标注 `# A1` 待真实飞书 app 验证。
- **A2**：看板工作项 `description` field_key 与 `work_item_type`（默认 `story`）待 live 验证；缺看板引用/失败均 fail-soft 跳过。

## Blockers

无。
