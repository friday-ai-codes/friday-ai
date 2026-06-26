# Phase 83: 飞书文档双向同步引擎 - Research

**Researched:** 2026-06-26
**Domain:** 飞书 docx 双向同步（事件订阅 + 回拉 + block 级增量写 + block_id 结构化匹配 + 三方合并 + durable 串行队列 + 缓存 + 兜底轮询）
**Confidence:** MEDIUM（代码地基与既有模式 HIGH 可信、已 grep 验证；飞书具体 API 请求体/事件结构需 live-Feishu UAT，标注为 ASSUMED/MEDIUM）

> 说明：GSD 工件文案可能写 "friday-ai"，本仓真实根为 `/Users/zaneliu/Projects/open-source/friday-clean`，全部以 friday-clean 为准。

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（锁定，research 只服务这些，不探索替代方案）

**同步落地顺序**
- **5 文件齐头并进**：同步引擎对 5 类 `ProjectDoc` 统一抽象（区段所有权分区 + block_id 映射表通用），一次性把 MEMORY/STATE/MILESTONES/RESEARCH/PREFLIGHT 全部接入双向同步。
- 引擎按 doc_type 配置"系统区/人工区"切分与 Agent 写法（MEMORY=append 条目、STATE/MILESTONES=系统派生区+人工补充段、RESEARCH/PREFLIGHT=AI 待确认区+人工正文），但**同步机制单一实现**，不为某文件单独造链路。

**Friday→飞书 推送策略**
- **debounce 合并后批量 block 推送**：DB 写不逐条即时推，合并静默窗口内多次写后批量 block 级增量更新（`docx blocks` API），抗飞书频控。
- per-doc 串行队列 + 限流退避；create_folder/文档块写不并发。
- **永不整篇 replace（硬约束）**。

**防"编辑被冲掉"四机制（全部叠加）**
1. 永不整篇覆盖，只写 block 级（飞书 OT 合并不同块并发）。
2. 区段所有权分区：系统只写系统区、人只写人工区，物理不相交。
3. Agent 写一律 append 新 block，绝不就地改既有 block。
4. 编辑感知延迟写：推送前探测文档近 N 秒是否有人编辑（drive 事件/last-edit），活跃则入队、静默窗口再落；带乐观并发（last-synced revision 校验，变了先 rebase 再写）。

**diff 策略**
- block_id 结构化逐块匹配（新增/编辑/删除）+ last-synced 快照 + 映射表，**代替整篇文本 diff**。
- 真同块冲突 → 三方合并（base=last-synced/theirs=飞书/ours=DB）；不相交自动并、相交 capture-never-clobber（落败方存 revision + 标记 + 飞书评论提示），**绝不静默丢**。
- block_id 漂移边角 → 就近匹配 + capture，不丢内容。

**缓存（SYNC-05）**
- redis read-through，写时/收事件失效，TTL 兜底；redis 不可用降级直读 DB（best-effort）。

**边界/失败模式全覆盖（SYNC-06，fail-soft 不反噬）**
- 漏事件 → 进行中项目 TTL 轮询比对 revision 兜底。
- 文档被删/移 → 回拉 not-found → 标 broken + 通知 + 一键重建。
- 项目归档/终止 → 停双向同步 + 停 subscribe，文档转只读快照入 DB。
- 非成员在飞书编辑 → fail-soft 接受 + 归因（operator→resolve_feishu_user，未映射 system）。
- 飞书限流 → 退避 + per-doc 串行队列。

### Claude's Discretion（可裁量，research 给推荐）
- 5 文件统一抽象的具体落点（service 命名、block_id 匹配算法实现）。
- ProjectDocBlockMap 字段是否扩展（content_hash/section/order 等）。
- per-doc 串行队列在 durable 队列上的实现细节（lock / debounce 窗口 / rebase）。
- redis read-through 的实现（Django cache 框架 vs 自写 wrapper）。

### Deferred Ideas（OUT OF SCOPE，完全忽略）
- 飞书文档跨系统亚秒级 OT 实时协同（不可达，按秒级最终一致 + block 级不冲突交付）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SYNC-01 | 飞书→Friday：按文件 `subscribe` + 现有事件链路路由 `drive.file.edit_v1`（不含正文）→ 回拉正文；进行中项目 TTL 轮询兜底防漏事件 | §链路接入（事件 ingress 两路 + 新 normalizer/handler）；`FeishuDocClient.get_document_content` 已就绪可回拉；TTL 轮询复用 `runapscheduler` + `poll_repository_updates` 范式 |
| SYNC-02 | Friday→飞书：DB 写触发 block 级增量推送（`docx blocks` API），**永不整篇覆盖**；per-doc 串行队列 + 限流退避 | `FeishuDocClient._write_blocks`/`append_markdown` 已有 children/descendant 写；需新增 update/delete block 方法；durable `lock=` 实现 per-doc 串行 |
| SYNC-03 | block_id 结构化匹配（新增/编辑/删除）+ last-synced 快照 + 映射表代替整篇 diff；MEMORY 飞书编辑按 block_id 落 revision | `ProjectDoc.last_synced_revision/last_synced_snapshot` + `ProjectDocBlockMap(feishu_block_id↔db_ref, section, content_hash)` 已就绪；MEMORY revision 落 `MemoryService.edit` |
| SYNC-04 | 冲突处理：区段所有权分区 + Agent append + 三方合并 + capture-never-clobber + 编辑感知延迟写 | `ProjectDocBlockMap.section` 系统/人工区已就绪；三方合并 + capture 为净新算法；编辑感知延迟写经 durable `run_at` + 活跃探测 |
| SYNC-05 | redis read-through，写时/收事件失效，TTL 兜底，redis 不可用降级直读 DB | Django `CACHES`（django_redis / LocMem 自动回退）已配置，直接复用 |
| SYNC-06 | 边界/失败模式全覆盖，全部 fail-soft 不反噬主流程 | 复用 `ProjectDoc.sync_status=broken` + `provision_dispatch` 一键重建；归因复用 `resolve_feishu_user`；归档停同步复用 `Project` 状态机 |
</phase_requirements>

## Summary

Phase 83 是**净新增的同步引擎**，但几乎所有"底座"都已在前序里程碑落地、可直接复用，**严禁重造**：飞书事件 ingress（WS 长连 + HTTP webhook 双路）、`FeishuDocClient`（回拉 + block 写）、durable 队列（Procrastinate `lock` 原生串行 + `idempotency_key` 去重 + `run_at` 延迟）、Django 缓存框架（redis/LocMem 自动回退）、apscheduler 周期轮询、`ProjectDoc`/`ProjectDocBlockMap` 映射表骨架、`MemoryService`/`ProjectDocService` 单一写入收口、`resolve_feishu_user` 归因、`redact_secrets_in_text` 脱敏。**本期真正要"造"的只有：(1) `drive.file.edit_v1` 的事件路由分支 + normalizer + handler；(2) `FeishuDocClient` 新增 subscribe / update block / delete block 方法；(3) 一个统一的 `DocSyncService`（block_id 结构化匹配 + 三方合并 + capture-never-clobber）；(4) durable 上的 per-doc 串行队列 + debounce + 编辑感知延迟写 + rebase；(5) TTL 兜底轮询 job。**

最大不确定性集中在**飞书 docx API 的真实请求体/事件结构**（block update/delete/订阅端点、`drive.file.edit_v1` 事件字段、回拉 blocks 的 `block_id`/`revision_id` 形态）。代码已存在的 `get_document_content`（GET `/docx/v1/documents/{id}/blocks?page_size=500`）与 children/descendant 写 API 给了可信锚点，但增量 update/delete block、按文件 subscribe、revision 取材**必须 live-Feishu UAT** 验证后再固化，先以 `[ASSUMED]` 标注。

**本期无 LLM 调用、无 RAG 召回**（同步引擎纯结构化 diff）——确认**不需要新增 `call_source`、不需要写 `RetrievalTrace`**（那是 Phase 85/86 的事）。观测重点是：drive 事件 handler 带 `initiated_by_user_id`（worker 入口 re-bind）、飞书正文入日志前 `redact_secrets_in_text` 脱敏、写入收口 `MemoryService`/`ProjectDocService`（INV-6）、新增结构化 structlog 事件目录。

**Primary recommendation:** 建一个 `initiatives/services/doc_sync_service.py`（统一 `DocSyncService`，pull + push + 三方合并单一实现，按 doc_type 配置差异），事件 ingress 加 `drive.file.edit_v1` 路由→后台投递 `DocSyncService.pull`（durable，per-doc `lock`），DB 写侧经 `ProjectDocService`/`MemoryService` 钩子投递 `DocSyncService.push`（durable，per-doc `lock` + `run_at` debounce）。先把 **MEMORY（append 最简）** 端到端跑通（含三方合并/capture），再按 doc_type 套 STATE/MILESTONES/RESEARCH/PREFLIGHT，避免 5 套链路。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 飞书事件接收（drive.file.edit_v1） | API/Backend（feishu app：WS 长连 / HTTP webhook） | — | 现有飞书事件链路单一收口，按 event_type 多路复用 |
| 回拉文档正文 | Service（`FeishuDocClient.get_document_content`） | API/Backend | tenant_access_token 鉴权，外呼飞书 OpenAPI |
| block_id 结构化匹配 + 三方合并 | Service（净新 `DocSyncService`） | DB（`ProjectDocBlockMap`/`ProjectDoc` 快照） | 纯算法 + 映射表读写，无 IO 副作用（外呼/入库各自收口） |
| DB→飞书 block 级增量写 | Service（`FeishuDocClient` 新增方法） | Durable 队列 | per-doc 串行 + 限流退避属并发治理层 |
| per-doc 串行队列 + debounce + rebase | Durable（Procrastinate `lock`/`run_at`） | Service | 复用 durable 底座，不自研队列 |
| read-through 缓存 | Cache（Django `CACHES`，redis/LocMem） | DB | DB canonical，缓存只读加速，失效/降级 best-effort |
| TTL 兜底轮询 | Scheduler（apscheduler 单实例） | Service | 复用 `runapscheduler` flock 单实例 + `poll_*` 范式 |
| 写入收口（INV-6） | Service（`MemoryService`/`ProjectDocService`） | — | 所有 DB 写经单一 service，grep 守护 |
| 归因/脱敏/观测 | Cross-cutting（`resolve_feishu_user`/`redact_secrets_in_text`/structlog） | — | 观测规范强制，best-effort 不反噬 |

## Standard Stack

本期**不新增第三方依赖**，全部复用既有栈。下表是"该用哪个既有模块/能力"。

### Core（复用，不重造）

| 能力 | 模块/符号 | 用途 | 为什么是它 |
|---|---|---|---|
| 飞书 docx 读 | `server/services/feishu_doc.py::FeishuDocClient.get_document_content` | 事件回拉正文（返回 `(markdown, raw_blocks)`） | 已实现 GET `/docx/v1/documents/{id}/blocks?page_size=500` + 错误码分类（PermissionDenied/NotFound/RateLimit）+ tenacity 退避 |
| 飞书 docx 写 | `FeishuDocClient._write_blocks` / `_write_regular_blocks`（children）/ `_write_table_via_descendants`（descendant）/ `append_markdown` | block 级追加写 | 已实现 children/descendant 增量写；update/delete 需净新增（见 Don't Hand-Roll） |
| 文件夹 | `FeishuDocClient.create_folder` | 一键重建 | Phase 82 已落（5QPS/不可并发） |
| 客户端工厂 | `agents/tools/feishu_doc_tools.py::create_feishu_doc_client_for_project(space)` | 取 app 凭证建 client（项目 IM 配置优先，回退 SystemSetting） | Phase 82 已用同一入口 |
| 事件 ingress（WS） | `server/feishu/websocket_client.py::FeishuWebSocketClient._build_event_handler` | lark SDK 长连，注册 `register_p2_*` handler | drive 事件加 `register_p2_drive_file_edit_v1`（需 lark-oapi 支持，live 验证） |
| 事件 ingress（HTTP） | `server/feishu/views.py::IMMessageWebhookView` / `FeishuWebhookView` | 单回调地址按 `header.event_type` 多路复用 | drive 事件落 event-subscription URL，加路由分支 |
| durable 队列 | `server/durable/service.py::DurableTaskService.defer(task, payload, queue=, idempotency_key=, lock=, run_at=, initiated_by_user_id=)` | per-doc 串行 + 去重 + 延迟写 | Procrastinate 原生 `lock`（doing 串行）+ `idempotency_key`（todo 去重）+ `run_at`（debounce） |
| durable 任务定义 | `server/durable/tasks.py`（`@app.task(name=, queue=)`）+ `tasks_impl.py` + `queues.py` | 注册新同步任务 | 新增 `QUEUE_DOC_SYNC` + `durable_doc_sync_pull/push` 包壳 |
| 缓存 | `django.core.cache`（settings `CACHES`：`django_redis.cache.RedisCache` / `LocMemCache` 自动回退） | SYNC-05 read-through | redis 在则共享、不在则 LocMem，**已配置开箱即用** |
| 周期轮询 | `server/agents/management/commands/runapscheduler.py`（flock 单实例 + `poll_repository_updates` 范式） | TTL 兜底比对 revision | 加一个 `poll_project_docs_revisions` job |
| 记忆写入收口 | `server/initiatives/services/memory_service.py::MemoryService`（append/edit/supersede + revision + 脱敏 + 成员校验） | MEMORY 飞书编辑落 revision | INV-6 单一入口，append-only revision |
| 文件/映射写入收口 | `server/initiatives/services/project_doc_service.py::ProjectDocService`（upsert_doc/set_doc_feishu/set_sync_status/upsert_block_map/upsert_state_api） | 映射表/快照/状态/STATE API 写 | INV-6 单一入口，已含 broken/重建 |
| 归因 | `server/feishu/services/identity.py::resolve_feishu_user(open_id= / feishu_user_key=)` | operator→Friday user，未映射 `system` | Phase 14/82 已用同一范式 |
| 脱敏 | `server/common/logging.py::redact_secrets_in_text` | 飞书正文/异常文本入日志前脱敏 | 强制规范，纯函数 |
| 入站留痕 | `server/system/webhook_recorder.py::record_inbound_webhook` | drive webhook 原始 payload 脱敏落库 | 已在 IM/卡片/webhook 三入口用 |

### Supporting

| 模块 | 用途 | 何时用 |
|---|---|---|
| `resumable/locks.py::InstanceLock`（可选 redis `SET NX PX`） | TTL 轮询集群级互斥（多副本只跑一份） | 轮询 job 包一层（redis 不可用退化放行，DB 兜底） |
| `ProjectMemoryRevision`（已存在） | MEMORY capture-never-clobber 落败方留史 | MEMORY 同块冲突 |
| `Project` 状态机（developing/archived/terminated） | 归档停同步判定 | pull/push 入口 gate |

### Alternatives Considered

| 代替 | 可选 | 取舍 |
|---|---|---|
| durable（Procrastinate） | `resumable/`（DB-CAS 租约） | **用 durable**：原生 `lock` 串行 + `run_at` 延迟写正是 per-doc 队列 + debounce 所需；`resumable` 无延迟/串行原语。注意 CONTEXT/MILESTONE 写 "server/resumable/"，**真实底座是 `server/durable/`**（resumable 是更老的 DB-CAS 续跑，索引/图谱已迁到 durable） |
| Django `CACHES` 框架 | 自写 redis wrapper（仿 `InstanceLock`） | **用 Django CACHES**：已配置 redis/LocMem 自动回退，`OPTIONS.IGNORE_EXCEPTIONS` 可让 redis 故障静默回退（降级直读 DB）。自写 wrapper 重复造轮子 |
| 后台投递 = durable | `services.background_runner.run_in_background`（fire-and-forget） | **用 durable**：同步任务需重启不丢 + per-doc 串行；background_runner 仅适合 best-effort 一次性派发（如 Phase 82 provision） |

**Installation:** 无新增依赖。

**Version verification:** N/A（无新增 pip 包）。

## Package Legitimacy Audit

> 本期**不安装任何外部包**，全部复用既有依赖（procrastinate / django-redis / lark-oapi / apscheduler / structlog 均已在 `server/pyproject.toml`）。Package Legitimacy Gate 不适用。

| Package | Disposition |
|---------|-------------|
| （无新增） | N/A |

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────── 飞书（Lark）──────────────────────────┐
                         │  用户在 docx 编辑  ─────────────►  drive.file.edit_v1 事件(无正文) │
                         └───────────────┬──────────────────────────────┬────────────────────┘
                                         │ (WS 长连)                     │ (HTTP webhook 单地址多路复用)
                                         ▼                              ▼
              feishu/websocket_client.py             feishu/views.py (IMMessage/FeishuWebhookView)
              register_p2_drive_file_edit_v1   ──►   按 header.event_type 路由 "drive.file.edit_v1"
                                         │                              │
                                         └──────────────┬───────────────┘
                                                        ▼  (净新) drive 事件 normalizer：取 file_token/doc_id + operator
                                                  DurableTaskService.defer("durable_doc_sync_pull",
                                                      lock=f"docsync-{doc_id}", idempotency_key=...)
                                                        │  per-doc 串行 + 去重，worker 入口 re-bind initiated_by
                                                        ▼
                            ┌────────────── DocSyncService.pull(doc) (净新) ──────────────┐
                            │ 1. 归档/broken gate（fail-soft 跳过）                         │
                            │ 2. FeishuDocClient.get_document_content → blocks + revision  │
                            │ 3. 逐 block 算 content_hash，对 ProjectDocBlockMap：          │
                            │      新增→建条目/段 | 改→落 revision | 删→标 superseded      │
                            │ 4. 同块冲突 → 三方合并(base=last_synced/theirs=飞书/ours=DB) │
                            │      不相交自动并 | 相交 capture-never-clobber(+飞书评论)    │
                            │ 5. 写入收口 MemoryService(MEMORY) / ProjectDocService(其余)  │
                            │ 6. 更新 last_synced_revision/snapshot + block_map            │
                            │ 7. 失效缓存 caches["default"].delete(doc 缓存键)             │
                            └──────────────────────────────────────────────────────────────┘
                                                        ▲
       ┌────────────────────────────────────────────────┤
       │ TTL 兜底轮询(apscheduler 单实例) poll_project_docs_revisions：
       │   进行中项目的 READY doc → get_document revision 比对 last_synced → 变了 defer pull
       │
   DB 写侧（Friday→飞书）                                  read-through 缓存(SYNC-05)
   MemoryService / ProjectDocService 写完 ──► 钩子          render(doc) ──► caches.get → 命中返回
   DurableTaskService.defer("durable_doc_sync_push",                     未命中 ──► 读 DB ──► caches.set(TTL)
       lock=f"docsync-{doc_id}", run_at=now+debounce窗口,                redis 不可用 → IGNORE_EXCEPTIONS 直读 DB
       idempotency_key=f"docpush:{doc_id}")  ◄── debounce 合并多次写
                            │
                            ▼
       DocSyncService.push(doc) (净新)：
         1. 编辑感知：近 N 秒有 drive 事件/last-edit → 重排 run_at 再退避(活跃则不抢写)
         2. 乐观并发：重拉 revision，若 != last_synced → 先 pull rebase 再 push
         3. 只对"系统区"block 算期望态，与 block_map diff → children新增 / update改 / delete删
            **永不整篇 replace**；per-doc 串行 + 限流退避(RateLimitError→tenacity)
         4. 更新 block_map + last_synced_revision/snapshot
```

### Recommended Project Structure

```
server/initiatives/services/
├── doc_sync_service.py        # 净新：DocSyncService（pull/push/三方合并/diff 单一实现）
├── doc_sync_diff.py           # 净新（可选）：纯函数 block diff + 三方合并（无 IO，易测）
server/services/feishu_doc.py  # 扩展：新增 subscribe_file / update_block / delete_blocks 方法
server/durable/
├── queues.py                  # 扩展：+ QUEUE_DOC_SYNC
├── tasks.py                   # 扩展：+ @app.task durable_doc_sync_pull / _push 包壳
├── tasks_impl.py              # 扩展：+ run_doc_sync_pull / run_doc_sync_push（worker 入口 bind 用户）
server/feishu/
├── views.py 或 websocket_client.py  # 扩展：drive.file.edit_v1 路由分支 + normalizer
server/agents/management/commands/runapscheduler.py  # 扩展：+ poll_project_docs_revisions job
server/tasks/                  # 可选：poll_project_docs_revisions 实现（仿 index_trigger_tasks）
```

### Pattern 1: drive 事件路由（normalizer → 投三元组 ID，正文后台回拉）
**What:** 飞书事件不含正文，webhook/WS 入口只解析出 `file_token`/`document_id` + `operator` + `event_id`（幂等键），投递后台 durable pull 回拉正文，**主响应不被回拉阻塞**（Phase 14 范式：handler 只投 ID，取材在后台）。
**When:** SYNC-01 接入。
**Example（既有范式，本期镜像）:**
```python
# Source: server/feishu/views.py 现有 _schedule_delivery_upsert / _maybe_schedule_project_board_sync
# 新增分支（伪代码）：
if event_type == "drive.file.edit_v1":
    file_token = payload.get("file_token", "")
    operator = str(payload.get("operator_id", {}).get("open_id") or "")
    initiated_by = "system"
    user = await resolve_feishu_user(open_id=operator)
    if user is not None:
        initiated_by = str(user.id)
    await DurableTaskService.defer(
        "durable_doc_sync_pull",
        {"file_token": file_token, "event_id": event_id},
        queue=QUEUE_DOC_SYNC,
        lock=f"docsync-{file_token}",                 # per-doc 串行
        idempotency_key=f"docpull:{file_token}:{event_id}",
        initiated_by_user_id=initiated_by,            # worker 入口 re-bind（CTX-02）
    )
```

### Pattern 2: per-doc 串行队列 + debounce（durable lock + run_at）
**What:** Procrastinate 原生 `lock`（同 lock job 串行执行，doing 互斥）= per-doc 串行；`idempotency_key`（=queueing_lock，todo 唯一）= debounce 合并多次写；`run_at=now+窗口` = 静默窗口延迟落。
**When:** SYNC-02/04 推送侧。
**Example:**
```python
# DB 写后钩子（push 侧）：同一 doc 在 debounce 窗口内多次写只保留一份 todo
await DurableTaskService.defer(
    "durable_doc_sync_push",
    {"doc_id": str(doc_id)},
    queue=QUEUE_DOC_SYNC,
    lock=f"docsync-{doc_id}",                          # pull/push 共用同 lock → 同 doc 全串行，天然防 pull/push 交叉
    idempotency_key=f"docpush:{doc_id}",               # 窗口内多次写去重合并
    run_at=timezone.now() + timedelta(seconds=DEBOUNCE_SECONDS),
)
```
> ⚠️ in-process fallback（SQLite/dev/pytest）忽略 `lock` 串行语义、`run_at` 行为需确认（见 Pitfall）。生产 Postgres 才有真实 doing 串行。

### Pattern 3: block_id 结构化匹配（代替整篇 diff）
**What:** 维护 `last_synced_snapshot`（base）+ `ProjectDocBlockMap`（飞书 block_id ↔ db_ref + content_hash + section）。回拉 blocks 后逐块比对 content_hash。
**When:** SYNC-03。
```
飞书 block_id 不在 block_map      → 用户新增 → 建条目/段（写 db_ref + 新 map 行）
block_id 在 map、content_hash 变  → 用户编辑 → 落 revision（MEMORY 走 MemoryService.edit）
block_id 在 map、飞书已无         → 用户删除 → 标 superseded（不真删）+ 清 map 行
→ 更新 last_synced_snapshot + block_map（content_hash/order）
```

### Pattern 4: 三方合并 + capture-never-clobber
**What:** 真同块两边都改（base≠theirs 且 base≠ours）→ 不相交自动并；相交 = 系统侧/DB 侧落败，存 revision（MEMORY 用 `ProjectMemoryRevision`；STATE/RESEARCH/PREFLIGHT 需净新 revision 落点）+ 标记 + 飞书发评论提示，**绝不静默丢用户内容**（用户编辑永远优先保留）。
**When:** SYNC-04。

### Anti-Patterns to Avoid
- **整篇 replace 飞书文档**（硬禁止）——只走 children/update/delete block。
- **系统写人工区 / 就地改 Agent 既有 block**——违反四机制 2/3。
- **pull 与 push 并发跑同一 doc**——必须共用 `lock=f"docsync-{doc_id}"` 串行。
- **在 async 上下文裸访问 lazy FK**——预取（`select_related`）或 `sync_to_async`（Phase 82 已踩，见 `_aget_project_with_space`）。
- **把飞书正文/token 写进日志或 message 拼接**——只记 doc_id/doc_type/计数/event 名 + 脱敏。
- **同步失败抛回 webhook/编辑主流程**——全部 fail-soft，标 broken + 通知。

## Don't Hand-Roll

| 问题 | 别自己造 | 用 | 为什么 |
|---|---|---|---|
| 飞书事件去重 | 自写 dedup | `ProcessedEvent`（DB unique）+ durable `idempotency_key` | 已有 DB 级幂等 `is_event_processed_db`/`mark_event_processed_db` |
| per-doc 串行 + 延迟 | 自写队列/定时器 | durable `lock` + `run_at` + `idempotency_key` | Procrastinate 原生，多副本安全、重启不丢 |
| 限流退避 | 自写 sleep loop | `FeishuDocClient` 既有 `@retry(RateLimitError, wait_exponential)` | 已对 `99991400`/"rate limit" 分类退避 |
| read-through 缓存 + 降级 | 自写 redis 封装 | `django.core.cache` + `OPTIONS.IGNORE_EXCEPTIONS=True` | 已配置 redis/LocMem 自动回退 |
| 集群单实例轮询 | 自写 leader 选举 | apscheduler flock 单实例 + 可选 `InstanceLock` | `runapscheduler` 已 flock 强制单实例 |
| 归因解析 | 自写 open_id 映射 | `resolve_feishu_user` | Phase 14/82 同一入口 |
| 脱敏 | 自写正则 | `redact_secrets_in_text` / `redact_for_ledger` | 强制规范 |
| Markdown↔blocks | 自写解析 | `feishu_doc.py::markdown_to_blocks`/`blocks_to_markdown` | 已实现（mistune + 表格） |

**Key insight:** 本期"难"在算法（结构化 diff + 三方合并 + 编辑感知延迟 + rebase）与飞书 API 真实形态，**不在基础设施**——基础设施 95% 已就绪，重造任何队列/缓存/幂等/退避都是反模式。

## Runtime State Inventory

> 本期会在飞书侧**注册 subscribe**（OS/外部服务注册态），需显式管理。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `ProjectDoc.last_synced_revision`/`last_synced_snapshot`、`ProjectDocBlockMap`（feishu_block_id↔db_ref/content_hash/section）——同步水位与映射的 DB 真相源，本期开始真正写入 | 代码写入（pull/push 更新水位+映射）；首次同步初始化映射 |
| Live service config | **飞书按文件 `subscribe`**：每个 doc `feishu_document_id` 需向飞书注册文件订阅，订阅态在飞书侧、**不在 git/DB**。归档/删除/重建时需 unsubscribe/re-subscribe | 净新：`FeishuDocClient.subscribe_file`/`unsubscribe`；DB 记 `subscribed` 标志（建议 ProjectDoc 扩字段）；归档停同步要主动退订（live 验证退订端点） |
| OS-registered state | 无（不涉 cron/任务计划/launchd） | None — 已确认，TTL 轮询走 apscheduler in-DB job |
| Secrets/env vars | 复用既有飞书 app 凭证（SystemSetting `FEISHU_APP_ID/SECRET` + 项目 IM 配置）；无新增密钥 | None — 复用 `create_feishu_doc_client_for_project` |
| Build artifacts | 无（纯 Python 模块新增 + 1 个 migration 若扩 ProjectDoc/BlockMap 字段） | 若扩字段需 `makemigrations`（initiatives app） |

**canonical 问题（所有文件改完后还有什么运行态没同步）:** 飞书侧的**文件订阅注册**——这是唯一"代码改完但运行态仍在外部"的项；plan 必须覆盖 subscribe 的注册/退订/重建生命周期，且 subscribe 失败 fail-soft（退化为 TTL 轮询兜底）。

## Common Pitfalls

### Pitfall 1: `drive.file.edit_v1` 事件结构与回拉字段未经真实验证
**What goes wrong:** 事件 payload 字段名（`file_token`/`operator_id`/`event_id`）、回拉 blocks 的 `block_id`/`revision_id` 形态、按文件 subscribe 端点全部基于训练知识，真实飞书可能不同。
**Why:** 飞书 OpenAPI 演进 + 本仓尚无 drive 事件接入（grep 确认 `subscribe`/`drive.file` 仅命中 chat WS，无飞书 drive）。
**How to avoid:** plan-phase **先 live-Feishu UAT**：订一个真实 docx、人工编辑、抓 webhook/WS 原始 payload（`record_inbound_webhook` 已落库可查）确认字段；blocks 回拉先打印 raw 结构确认 `block_id`/`revision_id`。所有相关声明本研究标 `[ASSUMED]`。
**Warning signs:** 事件到达但 normalizer 取不到 file_token；pull 拿不到 revision。

### Pitfall 2: 增量 update/delete block API 形态未知（只验证了 children/descendant 写）
**What goes wrong:** `FeishuDocClient` 现只有"追加"（children）与"建表"（descendant），**没有**改块/删块；SYNC 的"编辑/删除"分支无对应外呼。
**Why:** Phase 82 只需建文档 + 追加，未实现 update/delete。
**How to avoid:** 净新 `update_block`（PATCH `/docx/v1/documents/{id}/blocks/{block_id}`）+ `delete_blocks`（DELETE `/docx/v1/documents/{id}/blocks/{block_id}/children/batch_delete`，按 index 范围删）——端点/请求体 live 验证。镜像既有方法的 token/headers/retry/错误码处理。
**Warning signs:** push 只能 append、改/删落空，飞书文档膨胀。

### Pitfall 3: in-process fallback（SQLite/pytest）不具备 `lock` 串行/`run_at` 语义
**What goes wrong:** 测试在 SQLite 上跑，durable 走 in-process backend，`lock` 被忽略、`run_at`/debounce 行为与生产不同 → 测试绿但生产并发行为未覆盖。
**Why:** `DurableTaskService.defer` 文档明确 in-process 忽略 `lock`。
**How to avoid:** 串行/rebase 的正确性**不能只靠 durable lock**——`DocSyncService.pull/push` 内部用乐观并发（重拉 revision 比对 + CAS 式 `ProjectDoc.last_synced_revision` 条件 update）兜底，lock 只是减少争用。测试覆盖"revision 变了先 rebase"路径（不依赖真实 doing 锁）。
**Warning signs:** 多副本生产偶发覆盖；pytest 无法复现。

### Pitfall 4: MEMORY 非成员飞书编辑 vs MEM-02 fail-closed 冲突
**What goes wrong:** SYNC-06 要求非成员飞书编辑 **fail-soft 接受 + 归因**；但 `MemoryService.append/edit/supersede` 对非成员 `MemoryPermissionError` **fail-closed 拒绝**（MEM-02）。两条规矩直接冲突。
**Why:** MEMORY 写入收口强制成员校验，飞书侧任何有权限的人都能编辑。
**How to avoid:** plan 须裁决（Open Question OQ-1）。建议：飞书镜像编辑走**独立 sync 路径**——非成员编辑**捕获为 revision/草稿态**（归因 system/未映射），不直接进 active `ProjectMemory`，或给 `MemoryService` 加 `_skip_member_check`+`origin=feishu_sync` 的受限入口（仍脱敏 + 审计 + 标注来源），保持 MEM-02 对"前端贡献"仍 fail-closed。**绝不静默丢**（capture-never-clobber）。
**Warning signs:** 非成员编辑被静默拒绝、用户内容丢失。

### Pitfall 5: STATE/MILESTONES/RESEARCH/PREFLIGHT 没有 revision 落点（capture 无处存）
**What goes wrong:** MEMORY 有 `ProjectMemoryRevision` 可留落败方，但其余 4 文件的"人工区/正文段"目前无 revision 表，capture-never-clobber 没地方存。
**Why:** Phase 82 只建了 `ProjectDoc`/`ProjectDocBlockMap`/`ProjectStateApi`，无通用段 revision。
**How to avoid:** plan 决定通用落点（Claude 裁量）：建议复用 `last_synced_snapshot`/`ProjectDocBlockMap.content_hash` 之外，新增轻量 `ProjectDocBlockRevision`（doc+block_id+content+source+captured_at）或把落败内容追加到飞书评论 + DB 留痕字段。至少保证 capture 有持久落点。
**Warning signs:** 同块冲突时除 MEMORY 外内容丢失。

### Pitfall 6: 归档/删除文档的订阅生命周期遗漏
**What goes wrong:** 项目归档/终止要"停同步 + 停 subscribe + 转只读快照"；文档被删/移要"标 broken + 通知 + 一键重建"。若只停 push 不退订，飞书仍推事件、pull 仍尝试回拉报 not-found。
**How to avoid:** pull/push 入口统一 gate：`Project.status != developing` → 跳过 + 退订（best-effort）；回拉 `DocumentNotFoundError` → `ProjectDocService.set_sync_status(broken)` + 通知 + 提供 `rebuild_workspace`（Phase 82 已有一键重建）。
**Warning signs:** 归档项目仍消耗飞书配额；broken doc 反复报错刷屏。

### Pitfall 7: 高频编辑导致 INFO 刷屏 / 缓存击穿
**What goes wrong:** 用户连续编辑触发大量 drive 事件 → pull 每次 INFO + 缓存频繁失效。
**How to avoid:** 高频内部步骤用 `category=sampling` + debug 或采样（观测规范）；debounce 合并；缓存失效用 delete 而非 set 空（下次读再回填）。

## Code Examples

### 注册新 durable 任务（pull/push 包壳）
```python
# Source: server/durable/tasks.py 既有 durable_index/durable_repo_summary 范式
@app.task(name="durable_doc_sync_pull", queue=QUEUE_DOC_SYNC)
async def durable_doc_sync_pull(
    *, file_token: str = "", event_id: str = "", initiated_by_user_id: str | None = None
) -> dict[str, Any]:
    from durable.tasks_impl import run_doc_sync_pull
    return await run_doc_sync_pull(
        file_token=file_token, event_id=event_id, initiated_by_user_id=initiated_by_user_id
    )
```

### worker 入口 re-bind 触发用户（CTX-02）
```python
# Source: server/durable/tasks_impl.py 既有 run_index 同模式
async def run_doc_sync_pull(*, file_token, event_id, initiated_by_user_id=None):
    from common.log_context import bind_task_context
    cm = bind_task_context(
        user_id=initiated_by_user_id or "system", source="durable", component="doc_sync"
    )
    with cm:
        # DocSyncService().pull(...) — 全程 best-effort，异常吞掉记 failed 事件
        ...
```

### read-through 缓存（SYNC-05）
```python
# Source: settings.py CACHES（django_redis / LocMem 自动回退）
from django.core.cache import cache
def render_doc_cached(doc_id):
    key = f"projdoc:render:{doc_id}"
    val = cache.get(key)          # redis 不可用 + IGNORE_EXCEPTIONS → 返回 None（降级直读 DB）
    if val is not None:
        return val
    val = _render_from_db(doc_id)  # DB canonical
    cache.set(key, val, timeout=300)
    return val
# 写时/收事件失效：cache.delete(f"projdoc:render:{doc_id}")
```

## State of the Art

| 旧做法 | 现做法 | 何时变 | 影响 |
|---|---|---|---|
| 整篇文本 diff/replace 同步文档 | block_id 结构化匹配 + block 级增量写 | 本期决策 | 跨系统不冲突的根本机制 |
| `resumable/`（DB-CAS 续跑） | `durable/`（Procrastinate over Postgres） | v0.12（Phase 60–64） | 索引/图谱已迁；本期同步队列直接用 durable，**不要再往 resumable 加** |
| 无 CACHES（默认 LocMem 每 worker 一份） | `CACHES` redis 共享 / LocMem 回退 | 近期（260623-ax1 等） | SYNC-05 直接复用 |

**Deprecated/outdated:**
- CONTEXT/MILESTONE 文案的 "server/resumable/ durable 队列" 表述**口径过时**——真实 durable 底座是 `server/durable/`（DurableTaskService）；`server/resumable/` 是更老的 DB-CAS 续跑（仍在跑 index/graph recovery handler，但新功能不应往里加）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `drive.file.edit_v1` 事件 payload 含 `file_token`/`operator_id`/`event_id`，落现有 event-subscription 回调地址，按 `header.event_type` 可路由 | Pattern 1 / SYNC-01 | normalizer 取不到字段，pull 无法触发 → 高，必须 live UAT |
| A2 | lark-oapi SDK 提供 `register_p2_drive_file_edit_v1`（WS 长连路径） | Standard Stack | WS 路径不可用需回退 HTTP webhook → 中，二选一即可 |
| A3 | 按文件 subscribe 端点存在（app 即 owner 可订），可注册/退订 | Runtime State / SYNC-01 | 无法精准订阅 → 退化为纯 TTL 轮询（兜底仍可用）→ 中 |
| A4 | 增量 `update_block`=PATCH `/docx/v1/documents/{id}/blocks/{block_id}`、`delete`=batch_delete children by index | Pitfall 2 / SYNC-02 | 改/删落空 → 高，必须 live UAT |
| A5 | 回拉 blocks 每个 block 有稳定 `block_id`（改文字 id 不变）+ 文档级 `revision_id`（或 `document_revision_id`）可作乐观并发水位 | Pattern 3 / SYNC-03 | 结构化匹配/rebase 失效 → 高，必须 live UAT；注意 `ProjectDoc.last_synced_revision` 是 BigInteger，确认飞书 revision 是整型 |
| A6 | Procrastinate 同 `lock` 值的 job 在 doing 阶段串行执行（per-doc 串行成立） | Pattern 2 | 串行不成立需靠乐观并发兜底（已设计）→ 低 |
| A7 | Django `CACHES` 可配 `OPTIONS.IGNORE_EXCEPTIONS=True` 使 redis 故障静默回退 | Code Examples / SYNC-05 | 需在 settings 显式开启（django_redis 支持）→ 低 |
| A8 | 本期无 LLM 调用、无 RAG 召回，故无需新 `call_source`、无需 `RetrievalTrace` | 观测 | 若 plan 引入 LLM（如冲突摘要）则需补 call_source → 低（设计上不需要） |

## Open Questions

1. **MEMORY 非成员飞书编辑如何兼顾 SYNC-06 fail-soft 与 MEM-02 fail-closed？**（见 Pitfall 4）
   - 已知：`MemoryService` 成员校验 fail-closed；SYNC 要 fail-soft 接受 + 归因。
   - 推荐：独立 sync 受限入口，非成员编辑落 revision/草稿态（归因 system），不进 active；前端贡献仍 fail-closed。**plan-phase 必须裁决并写进 PLAN。**

2. **STATE/MILESTONES/RESEARCH/PREFLIGHT 的 capture-never-clobber 落败方存哪？**（见 Pitfall 5）
   - 推荐：新增 `ProjectDocBlockRevision` 通用段 revision，或飞书评论 + DB 留痕。

3. **编辑感知延迟写的"活跃探测"数据源？**
   - 候选：最近 drive 事件时间戳（DB 记每 doc `last_feishu_edit_at`）或回拉的 last-edit；推荐 DB 记最近事件时间，push 前比对，活跃则 `run_at` 再退避。

4. **subscribe 注册时机与 ProjectDoc 字段扩展**
   - 是否给 `ProjectDoc` 加 `subscribed`(bool) + `last_feishu_edit_at`(datetime)？推荐加（小 migration），承载订阅态与活跃探测。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| 飞书 OpenAPI（docx + drive 事件 + subscribe） | SYNC-01/02 | ✓（凭证经 SystemSetting/项目 IM 配置） | — | 缺凭证 → doc 置 broken，fail-soft |
| Procrastinate + Postgres（durable） | per-doc 串行队列 | ✓（prod Postgres）/ in-process fallback（SQLite/dev） | 已装 | SQLite → in-process（lock 被忽略，靠乐观并发兜底） |
| Redis（缓存 + 可选锁） | SYNC-05 | ✓（USE_REDIS_CHANNEL_LAYER）/ ✗ → LocMem | 已配置 | LocMem 进程内缓存；DB 恒为 canonical |
| apscheduler（TTL 轮询） | SYNC-01 兜底 | ✓ | django-apscheduler 已装 | 单实例 flock 强制 |
| lark-oapi（WS 长连 drive 事件） | SYNC-01（WS 路径） | ✓（已用 im/card） | 已装 | 若不支持 drive p2 → 走 HTTP webhook |

**Missing dependencies with no fallback:** 无（飞书凭证缺失走 broken/fail-soft）。
**Missing dependencies with fallback:** redis（→LocMem）、Postgres（→in-process durable）、WS drive 事件（→HTTP webhook）。

## Validation Architecture

> `.planning/config.json` 未显式关闭 nyquist_validation，按启用处理。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9 + pytest-asyncio + pytest-django；飞书外呼用 `respx`（httpx mock）；网络隔离 `pytest-socket` |
| Config file | `server/pyproject.toml`（`[tool.pytest...]`） |
| Quick run command | `cd server && uv run pytest tests/initiatives/test_doc_sync*.py -x` |
| Full suite command | `cd server && uv run pytest tests/initiatives tests/feishu tests/durable -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SYNC-01 | drive 事件路由 → 投 durable pull（normalizer 取 file_token/operator/event_id；归因 resolve_feishu_user） | unit | `pytest tests/feishu/test_drive_event_route.py -x` | ❌ Wave 0 |
| SYNC-01 | TTL 轮询比对 revision → 变了 defer pull | unit | `pytest tests/initiatives/test_doc_sync_poll.py -x` | ❌ Wave 0 |
| SYNC-02 | push 只发 block 级增量（children/update/delete），永不整篇 replace（respx 断言无全量 PUT） | unit | `pytest tests/initiatives/test_doc_sync_push.py -x` | ❌ Wave 0 |
| SYNC-03 | block_id 匹配：新增/编辑/删除三分支正确映射（纯函数 diff 易测） | unit | `pytest tests/initiatives/test_doc_sync_diff.py -x` | ❌ Wave 0 |
| SYNC-04 | 三方合并不相交自动并；相交 capture（落败存 revision + 不丢）；"用户编辑中系统写入不冲掉" | unit | `pytest tests/initiatives/test_doc_sync_conflict.py -x` | ❌ Wave 0 |
| SYNC-04 | 乐观并发：revision 变了先 rebase 再 push | unit | `pytest tests/initiatives/test_doc_sync_rebase.py -x` | ❌ Wave 0 |
| SYNC-05 | 缓存命中/失效/redis 不可用降级直读 DB | unit | `pytest tests/initiatives/test_doc_sync_cache.py -x` | ❌ Wave 0 |
| SYNC-06 | not-found→broken+一键重建；归档停同步退订；非成员编辑 fail-soft 归因；限流退避 | unit | `pytest tests/initiatives/test_doc_sync_boundaries.py -x` | ❌ Wave 0 |
| INV-6 | 写入只经 MemoryService/ProjectDocService（grep 守护） | guard | `pytest tests/initiatives/test_doc_sync_inv6_guard.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/initiatives/test_doc_sync_diff.py tests/initiatives/test_doc_sync_conflict.py -x`（纯函数核心快）
- **Per wave merge:** `uv run pytest tests/initiatives tests/feishu tests/durable -q`
- **Phase gate:** 上述全绿 + `makemigrations --check`（若扩字段）+ INV-6 守护 before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/initiatives/test_doc_sync_diff.py` — 纯函数 block diff + 三方合并（无 IO，覆盖 SYNC-03/04 核心）
- [ ] `tests/initiatives/conftest.py` — ProjectDoc/BlockMap/ProjectMemory + respx 飞书 mock fixtures
- [ ] `tests/feishu/test_drive_event_route.py` — drive 事件 normalizer + durable defer mock（SYNC-01）
- [ ] `tests/initiatives/test_doc_sync_inv6_guard.py` — grep 守护（仿 `test_memory_inv6_guard`/`test_project_doc_inv6_guard`）
- [ ] live-Feishu UAT 种子：真实订阅+编辑抓 payload（A1/A4/A5 验证，记 `*-UAT.md` deferred 真机项）

## Security Domain

> `security_enforcement` 未显式关闭，按启用处理。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | 飞书 webhook 验签（`FEISHU_ENCRYPT_KEY` + `verify_callback_signature`，已有）；tenant_access_token 外呼 |
| V3 Session Management | no | — |
| V4 Access Control | yes | 写仍仅成员（MEM-02）；非成员飞书编辑 fail-soft 但归因受限（见 OQ-1）；归档项目停同步 |
| V5 Input Validation | yes | 飞书事件 payload 字段防御性取值（`.get` + 缺字段跳过，仿 webhook 既有范式）；block 内容入库脱敏 |
| V6 Cryptography | no（不自造） | 复用 `cryptography` Fernet 凭证加密（既有），不在本期碰 |
| V7 Logging | yes | 飞书正文/异常文本 `redact_secrets_in_text`；webhook 原始 payload `record_inbound_webhook` 脱敏落库；token 绝不入日志 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 伪造 drive 事件触发同步 | Spoofing | 飞书签名校验（生产 `FEISHU_SIGNATURE_REQUIRED`）+ `ProcessedEvent` 幂等 |
| 飞书正文含密钥被记录/留痕 | Information Disclosure | `redact_secrets_in_text` 入日志前脱敏；ledger 走 `redact_for_ledger` |
| 非成员经飞书污染共享记忆 | Tampering/Elevation | 非成员编辑捕获为 revision/草稿（归因 system），不进 active（OQ-1 裁决） |
| 同步风暴/限流耗尽配额 | DoS | per-doc 串行 + debounce + 退避；归档退订释放配额 |
| 同块冲突静默丢用户内容 | Tampering | capture-never-clobber（落败存 revision + 评论，绝不丢） |

## Sources

### Primary (HIGH confidence) — 已 grep/读源码验证
- `server/services/feishu_doc.py` — FeishuDocClient（get_document_content / create_document / create_folder / append_markdown / _write_blocks children+descendant / markdown↔blocks）
- `server/initiatives/models/project_doc.py` — ProjectDoc / ProjectDocBlockMap 字段
- `server/initiatives/services/project_doc_service.py` — ProjectDocService（INV-6 写入收口 + broken + 一键重建 provision）
- `server/initiatives/services/memory_service.py` — MemoryService（append/edit/supersede + revision + 成员校验 + 脱敏）
- `server/feishu/views.py` — 事件 ingress（IMMessageWebhookView/FeishuWebhookView，event_type 多路复用、ProcessedEvent 幂等、_schedule_* 后台投递范式、resolve_feishu_user 归因）
- `server/feishu/websocket_client.py` — lark SDK WS 长连 register_p2_* 事件路由
- `server/durable/service.py`+`tasks.py`+`queues.py`+`concurrency.py` — DurableTaskService.defer（lock/idempotency_key/run_at/initiated_by_user_id）+ 任务注册范式
- `server/resumable/service.py`+`locks.py`+`models.py` — 续跑底座 + 可选 InstanceLock（redis SET NX PX）
- `server/agents/management/commands/runapscheduler.py` + `server/tasks/index_trigger_tasks.py` — apscheduler flock 单实例 + poll_repository_updates 轮询 + 防抖去重范式
- `server/friday/settings.py` — CACHES（django_redis/LocMem 自动回退）+ REDIS_* 配置
- `server/common/logging.py` — redact_secrets_in_text / redact_credentials
- `.cursor/rules/observability-logging.mdc` + `.planning/observability/LOGGING-SPEC.md §4.1` — 观测/脱敏/归因/call_source 强制项（确认本期无 LLM/召回，无需新 call_source/RetrievalTrace）

### Secondary (MEDIUM)
- `.planning/project-workspace/MILESTONE-PROPOSAL.md §4/§9/§10/§14` — 同步引擎详设 + 边界 + 调研结论 + 风险
- `.planning/phases/83-feishu-doc-bi-sync-engine/83-CONTEXT.md` — 锁定决策

### Tertiary (LOW / 需 live 验证)
- 飞书 `drive.file.edit_v1` 事件结构、按文件 subscribe 端点、docx block update/delete 请求体、revision 字段（A1–A5，必须 live-Feishu UAT）

## Metadata

**Confidence breakdown:**
- Standard stack（复用既有模块）: HIGH — 全部 grep/读源码确认
- Architecture（pull/push/三方合并/durable 串行）: MEDIUM-HIGH — 模式成熟、算法清晰，落点明确
- 飞书 API 真实形态: LOW — 事件/订阅/增量写/ revision 需 live UAT（标 ASSUMED）
- Pitfalls: HIGH — 来自真实代码冲突点（MEM-02 vs SYNC-06、in-process lock、缺 revision 落点）

**Research date:** 2026-06-26
**Valid until:** 代码地基约 30 天；飞书 API 形态需 live 验证后才转 VERIFIED（建议 plan-phase 首个 wave 即做）
