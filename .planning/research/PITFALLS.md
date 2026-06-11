# Pitfalls Research

**Domain:** 交付知识图谱（需求/缺陷 ↔ 技术方案 ↔ 代码 diff 的 GraphRAG 关联）— brownfield 集成到 Friday AI（Django 5.1 / Python 3.14 异步栈 + Postgres + Qdrant）
**Researched:** 2026-06-11
**Confidence:** HIGH（Qdrant 行为有官方文档 + GitHub issue 佐证；bi-temporal 模型有 Graphiti/Zep 论文佐证；摄取/异步坑直接来自本仓库代码与历史事故注释）

> 编号约定：P1–P7 对应里程碑提出的七大风险点；P8–P10 为调研中额外发现的本仓库特有风险。
> "Phase to address" 使用功能域名称（数据模型 / 摄取管线 / 检索 / 多入口暴露），由 roadmap 映射到具体 phase 编号。

## Critical Pitfalls

### Pitfall P1: 把"删除旧向量"当成版本下线的唯一手段（漏删 = 旧方案被检索到）

**What goes wrong:**
方案 v2 重摄取时先 delete-by-filter 删 v1 向量、再 upsert v2。任何一步失败/竞态都会导致：(a) 旧向量残留，检索命中已废弃方案——这是用户明确的核心诉求风险；(b) 删除误伤刚写入的新向量。Qdrant 官方确认：默认 write ordering 为 `weak`，delete 与并发 upsert 可被重排，**刚 upsert 的新点可能被前一个 delete-by-filter 误删**（qdrant/qdrant#6556，官方建议 `wait=True` + `ordering=strong`）。此外本仓库 `QdrantService.upsert_vectors` 的设计哲学是"网络层异常 catch 后返回 False 不重抛"（`server/services/qdrant_service.py:870-878`），如果版本下线路径沿用这个语义，**删除失败会被静默吞掉**，没有任何机制发现旧向量残留。

**Why it happens:**
代码索引场景里漏删一个旧 chunk 只是噪音；知识图谱场景里漏删旧方案是**正确性错误**（AI 会按过时方案写代码）。开发者把 indexer 的"尽力而为"容错语义直接搬过来，没有意识到两者对一致性的要求量级不同。

**How to avoid:**
1. **检索侧兜底是第一道防线，删除只是优化**：每个 point 的 payload 带 `version` / `is_latest`（或 `expired_at`）字段，**所有检索查询强制带 `is_latest=true` filter**（建 keyword payload index）。这样即使删除失败，旧向量也不可见。
2. 写入顺序：先 upsert v2（payload `is_latest=true`）→ 再把 v1 的 point 用 `set_payload` 打 `is_latest=false`（tombstone）→ 异步物理删除 v1。tombstone 用 `batch_set_payload`（已有现成 API，`qdrant_service.py:1318`）。
3. Postgres 是 source of truth：每个知识实体版本在 DB 记录其 Qdrant point_id 列表（沿用 `ChunkRegistry` 的 chunk_id ↔ point_id 1:1 对齐模式）。物理删除按 **point id 列表**删（从 DB 取），不要按业务 filter 删——既避免 filter 误伤，又可重放。
4. 删除/打标操作必须 `wait=True`；失败要**响亮**（structlog error + 重试队列/对账任务），不允许沿用 `return False` 静默语义。
5. 提供 reconcile 管理命令：对账 DB 中 `is_latest` 状态与 Qdrant payload，修复漂移（仓库已有先例：孤儿 ChunkEdge 由 reconcile 命令兜底）。

**Warning signs:**
- 检索结果出现同一需求的两个版本方案；
- DB 中实体 version 数与 Qdrant 中该实体 point 数对不上；
- 日志出现 `delete_*_failed` 但任务状态仍是 success。

**Phase to address:** 数据模型 + 摄取管线 phase（payload schema、tombstone 协议、reconcile 命令）；检索 phase 验证"强制 is_latest filter"不可绕过。

---

### Pitfall P2: bi-temporal 边建模的三连坑——naive datetime、忘加有效性过滤、失效不级联

**What goes wrong:**
1. **时区**：项目 `TIME_ZONE = "Asia/Shanghai"` + `USE_TZ = True`（`server/friday/settings.py:238-240`）。飞书 webhook 给的是毫秒时间戳/本地时间字符串，Git 平台给 ISO8601 带 offset，chat 入口用服务器时间。任何一处用 naive datetime 写入 `valid_at`，比较时即出现 ±8h 漂移——边的失效判断（"v2 的 valid_at 是否晚于 v1"）直接错。
2. **查询忘加有效性过滤**：bi-temporal 有 4 个时间字段（`valid_at`/`invalid_at` 业务时间线 + `created_at`/`expired_at` 系统时间线，Graphiti/Zep 模型）。每条图查询（递归 CTE 图扩散尤其）都必须带 `invalid_at IS NULL AND expired_at IS NULL`（"当前有效"语义）。漏一处 = 过时边参与图扩散 = 旧方案沿边泄漏回检索结果——P1 的图谱版变体。
3. **失效不级联**：需求 v2 替代 v1 时，只把"需求→方案"边失效，但 v1 方案的"方案→diff"边还活着；图扩散 2 跳后仍能从新需求走到旧 diff。反向也成立：实体失效但其边未失效，产生"幽灵边"。

**Why it happens:**
bi-temporal 是 Graphiti 借鉴来的新模式，仓库内没有先例；4 个时间字段语义相近极易混用（Graphiti 文档专门强调两条时间线的区分）。失效级联是图模型固有复杂度，单元测试只测一跳很难暴露。

**How to avoid:**
1. 模型层 `CheckConstraint`：`valid_at < invalid_at`、`created_at < expired_at`（仓库已有 weight 双重校验先例，`ChunkEdge`）；写入口统一走一个 service 函数强制 `timezone.now()` / aware datetime，拒绝 naive（已有先例：`rebuild_chunk_edges --since` 拒绝 naive datetime，`code_relations/management/commands/rebuild_chunk_edges.py:106`）。
2. **不让调用方手写有效性过滤**：GraphStore 接口的查询方法默认只返回当前有效边，历史查询走显式 `as_of(timestamp)` 参数。把过滤埋进接口而不是约定。
3. 失效级联做成显式事务操作：`invalidate_entity_version(entity, ts)` 一次性失效实体 + 出入边，并在同一 DB 事务内完成；写专门的级联测试（2–3 跳路径上验证旧版本不可达）。
4. 监控数据质量不变量：`valid_at > invalid_at` 或 `invalid_at < valid_at` 的行数应恒为 0（业界 temporal KG 实践明确建议对此告警）。

**Warning signs:**
- 测试在 UTC CI 上过、本地（Asia/Shanghai）挂，或反之；
- 图扩散结果里出现 `expired_at` 非空的边；
- 同一实体对之间同 type 边存在两条 `invalid_at IS NULL` 的记录（应唯一）。

**Phase to address:** 数据模型 phase（约束 + GraphStore 接口语义）；检索 phase（图扩散查询审计）。

---

### Pitfall P3: 摄取 hook 阻塞请求路径 + 回调重试导致重复摄取

**What goes wrong:**
1. **同步阻塞**：摄取 = embedding API 调用（外网，秒级）+ Qdrant upsert + 图写入。挂在飞书 webhook / chat 请求 / workflow 节点的同步路径上，会把请求拖到超时。飞书 webhook 要求快速返回，超时即重试 → 触发第 2 条。
2. **重试重复摄取**：飞书事件重试、runner HTTP 回调重试（`go-retryablehttp`）、workflow 节点重试（引擎自带 retry 机制）都会把同一事件投递 ≥2 次。摄取不幂等 = 重复实体 + 重复向量。
3. **事务与后台任务边界**：在 DB 事务内启动后台摄取任务，任务跑起来时事务还没 commit，读不到刚写的方案记录（或读到后事务回滚，产生孤儿向量）。
4. **sync_to_async 误用**：本仓库有明确历史事故——在 ASGI 请求事件循环里 `asyncio.create_task` 启动长任务，请求一返回 asgiref 的 `CurrentThreadExecutor` 被关闭，后续 ORM 调用抛 `RuntimeError: CurrentThreadExecutor already quit or is broken`（`server/services/background_runner.py:1-24` 整个模块就是为此而生）。

**Why it happens:**
摄取入口分散在四个子系统（feishu/chat/workflow/MCP），每个入口的开发者各自决定怎么触发摄取；异步陷阱（executor 生命周期、contextvars 泄漏）不踩一次不知道。

**How to avoid:**
1. **统一摄取入口**：所有入口只做一件事——写一条摄取请求记录（含 source + natural key + payload 摘要），然后 `run_in_background(...)` 提交真正的摄取 coroutine（复用 `services/background_runner.py`，它已解决 executor/contextvars 问题）。请求路径耗时 = 一次 DB insert。
2. 幂等键：摄取请求表带 `(source_system, source_event_id, content_hash)` 唯一约束；飞书侧复用 `ProcessedEvent` 模式（`server/feishu/models.py:165`，"DB 唯一约束替代内存 set，多进程/重启后幂等不丢"）。重复投递命中唯一约束 → 静默跳过并打 log。
3. 事务边界：摄取任务的触发用 `transaction.on_commit(lambda: run_in_background(...))`，保证后台任务只在数据可见后启动。
4. 重摄取同一实体的并发保护：per-entity 锁或 `select_for_update` 版本行，避免两个版本的摄取交错写 Qdrant（与 P1 的 ordering 问题叠加放大）。

**Warning signs:**
- 飞书 webhook 响应时间 > 1s 或飞书后台显示事件重推；
- 日志出现 `CurrentThreadExecutor already quit`；
- 同一工作项对应多条相同 content_hash 的实体版本。

**Phase to address:** 摄取管线 phase（统一入口 + 幂等表 + on_commit）；多入口暴露 phase 只接线、不各写各的触发逻辑。

---

### Pitfall P4: 同一需求多入口进入产生重复实体（飞书 vs chat 双路）

**What goes wrong:**
PM 在飞书建了工作项，开发又在 chat 里把同一需求贴给 AI 跑方案。两路各自摄取 → 图中两个"需求"实体、两套方案边，检索召回时两份相似内容互相挤占 top-k，迭代轨迹断成两截（飞书那条有 v1，chat 那条有 v2，谁也看不到完整历史）。

**Why it happens:**
项目决策"实体来自结构化业务数据、不做 LLM 自由文本实体抽取"对飞书/MR 成立（自带稳定 ID），但 chat 自然语言需求**没有稳定 ID**——这是去重策略的真空地带，最容易被各入口实现者用"new entity 兜底"糊过去。

**How to avoid:**
1. 实体主键 = `(source_system, source_id)` 派生的 uuid5（沿用 ChunkRegistry 的"uuid5 同源稳定 PK"模式）。飞书工作项、MR、diff 天然去重。
2. chat 入口分两种情况：(a) 会话上下文里能解析出飞书链接/工作项 ID → 直接归并到既有实体；(b) 纯自然语言 → 创建实体前先做一次向量相似度候选查询（阈值 + 同 project 过滤），高相似时**建 `relates_to`/`duplicate_of` 边而不是自动合并**——自动合并错了无法撤销，关联边错了可删。
3. 把"合并/确认重复"做成显式 API（人工或 agent 确认），而非摄取时静默决策。
4. 验收测试明确覆盖：同一工作项先后从飞书 webhook 和 chat 进入，断言图中实体数为 1（或 1 实体 + 1 关联边）。

**Warning signs:**
- 检索 top-10 中出现两条文本近似、source 不同的需求实体；
- "查看迭代轨迹"显示的版本链中断。

**Phase to address:** 数据模型 phase 定 natural key 规则；摄取管线 phase 实现归并策略；多入口暴露 phase 的验收必须含双路摄取场景。

---

### Pitfall P5: 异构语料混在一个 collection 的召回偏置 + 时间衰减/跨语言无评测盲调

**What goes wrong:**
1. **召回偏置**：中文需求文本、结构化方案文档、英文代码 diff 是三种分布完全不同的语料。混在一个 collection 做 hybrid 检索时：diff 的 sparse 向量（代码 token、标识符）在 BM25 类打分上天然高命中；中文需求 query 对 diff chunk 的 dense 相似度系统性偏低 → top-k 被单一类型刷屏，或反之。
2. **时间衰减盲调**：衰减权重（半衰期、与相似度的混合比例）没有评测集就只能拍脑袋，调过头 = 三个月前的高相关方案排不进 top-k，调不动 = 过时方案压住新方案。
3. **跨语言**：部署用 doubao-embedding-text（2560 维，多语言），中文 query ↔ 英文代码注释/diff 的跨语言对齐质量**未经本项目验证**；且 Embedding 模型可由系统配置切换，换成单语模型后跨语言检索静默劣化。

**Why it happens:**
"一个 collection 省事"是默认直觉；时间衰减和跨语言效果不写评测就永远停留在"感觉还行"。

**How to avoid:**
1. **按语料类型分 named field 或分 collection**（需求/方案 vs diff），检索时分路召回再融合（RRF 已是仓库现成模式，`hybrid_search` 用 `Fusion.RRF`），每路独立 top-k 配额，避免单类型刷屏。payload 必带 `entity_type` keyword index，至少保住"检索时可按类型过滤"的逃生门。
2. 时间衰减不要做进向量打分，**做成检索后 re-rank 的显式一项**（score = α·sim + β·recency + 过时标记直接降权/排除），参数集中一处可配；上线前构造 20–50 条带标注的评测 query（历史真实需求 + 期望命中的方案/diff），调参看指标不看感觉。
3. 跨语言：摄取 diff 时生成一段中文摘要一并嵌入（摘要向量 + 原文向量双路），用摘要向量服务中文 query 召回、原文向量服务代码相似召回；评测集中明确包含"中文 query 召回英文 diff"用例。
4. Embedding 模型切换时（系统配置变更）必须触发知识 collection 重嵌入流程或至少响亮告警——维度不同会直接写不进（见 P9）。

**Warning signs:**
- 检索结果 top-10 里 ≥8 条是同一 entity_type；
- 中文 query 对明确相关的 diff 召回 score 显著低于英文 query；
- 调时间衰减参数后没有任何量化指标变化记录。

**Phase to address:** 检索 phase（分路召回 + re-rank + 评测集）；评测集构造应在摄取管线 phase 末期就开始积累真实数据。

---

### Pitfall P6: 知识库检索越权——跨 project/space 泄漏与 PAT 工具入口不 fail-closed

**What goes wrong:**
知识图谱聚合了需求、方案、diff——比单仓代码检索的泄漏面更大（一次检索可横跨多个仓库/项目的交付历史）。两类具体风险：
1. 检索 API 接受调用方传入的 project/repository 范围参数但不校验权限——本仓库有**现成前科**：compat 路径 `prepare_messages` 把调用方给的 `repository_ids` 直传检索服务，无 `PermissionService` 校验（`server/compat/request_handler.py:120` 有显式 `TODO(security mitigation)`，CONCERNS.md 列为 IDOR）。新检索入口若照抄该模式，等于把 IDOR 复制到更敏感的数据上。
2. MCP/chat tools/workflow 节点四个暴露入口各自实现鉴权，漏一个就是无认证检索端点；compat 层还有"AllowAny 当默认"的前科（`OPENAI_COMPAT_API_KEYS` 为空即放行）。

**How to avoid:**
1. 权限过滤下沉到检索 service 内部：检索函数签名强制接收 `user`，内部据其 RBAC 解析可见 project/repo 集合并作为 Qdrant payload filter + DB 查询 filter，**调用方传的范围参数只能收窄不能放宽**。payload 里必须存 `project_id`/`repository_id` 并建 keyword index——事后补字段要全量回填。
2. 四个暴露入口全部复用 v0.2.0 的认证基建：MCP 入口走 PAT fail-closed（`McpToolView` 模式），chat tools 继承会话 owner，workflow 节点继承执行者身份。**禁止任何入口出现"未配置即放行"的默认**。
3. 安全测试显式覆盖：用户 A 的 PAT 检索用户 B 无权限项目的需求 → 必须 0 结果（不是 403 泄漏存在性，沿用"越权 404/空"惯例）。

**Warning signs:**
- 检索 service 函数签名没有 user/principal 参数；
- 新增 HTTP 入口的 permission_classes 是 AllowAny 或缺省；
- Qdrant payload 没有 project_id 字段。

**Phase to address:** 数据模型 phase（payload 含权限维度字段）；多入口暴露 phase（每入口鉴权 + 越权测试）。不要留到"安全加固 phase"事后补——回填成本高。

---

### Pitfall P7: 万行级大 diff 的 chunking、embedding 上限与 Qdrant 写入超时

**What goes wrong:**
全量 diff 归档遇到生成型 MR（lockfile、自动格式化、代码生成）轻松上万行：
1. 整 diff 一条嵌入 → 超 embedding API token 上限，请求被截断或拒绝；
2. 切太碎 → 单 MR 产生数千 points，批量 upsert payload 巨大。本仓库有**直接历史事故**：大 batch upsert 超 qdrant-client 默认 5s timeout → `index_status=FAILED`（`qdrant_service.py:141-146` 注释记录"灾难性后果"，为此把 timeout 提到 60s 并禁用 keepalive 复用）；
3. 检索侧把整个大 diff 塞进 LLM 上下文 → 吃光 token 预算，挤掉其他召回结果。

**Why it happens:**
用"正常 MR 几百行"的样本开发，生成型 MR 在真实数据里才出现；diff 与源码不同——hunk 边界、文件边界天然存在但容易被按固定行数切分的偷懒实现忽略。

**How to avoid:**
1. 按 **文件 → hunk** 层级切分，单 chunk 上限按 embedding 模型 token 限制留 20% 余量；纯生成文件（lockfile、dist、迁移产物）按 glob 规则跳过向量化、只归档原文。
2. 大 MR 设 points 上限（如单 MR 最多 N 个 diff chunk，超出部分只嵌入文件级摘要），上限可配。
3. upsert 必须分 batch（沿用 indexer 的 batch 模式），且复用 `QdrantService` 现成的 timeout/retry/可观测基建——不要绕开它直接拿 client。
4. 检索返回 diff 时走 token 预算裁剪：直接复用 `services/retrieval/token_budget.py` 的 `trim_to_budget`/`split_budget`，给 diff 类结果单独配额。
5. 测试夹具必须包含一个 ≥10k 行的真实 diff（lockfile 更新 + 多文件重构混合）。

**Warning signs:**
- 摄取日志出现 embedding API 4xx（payload too large）；
- `upsert_vectors_call_start` 日志的 `total_bytes` 单次超数十 MB；
- 某次检索响应里单条 diff 占用 > 50% token 预算。

**Phase to address:** 摄取管线 phase（分层 chunking + 跳过规则 + batch）；检索 phase（diff 配额与裁剪）。

---

### Pitfall P8: 复用 `create_collection` 的"维度不匹配即删库重建"语义，知识库被静默清空

**What goes wrong:**
现有 `QdrantService.create_collection` 检测到 vector_size 或 hybrid 模式与现存 collection 不一致时**直接 delete_collection + 重建**（`qdrant_service.py:435-446`）。对代码索引这无所谓（可从 git 重建）；但知识 collection 若沿用此语义，管理员切换 embedding 模型（2560 维 → 1024 维）后第一次摄取就会**静默删光全部历史知识向量**。虽然 PG 仍有原文可重嵌入，但在重嵌入完成前检索完全失效，且没人收到通知。

**How to avoid:**
- 知识 collection 的 ensure 函数检测到配置不匹配时**拒绝并响亮报错**（提示需要显式运行重嵌入命令），绝不自动删除；
- 提供 `reembed_knowledge` 管理命令：新建带版本后缀的 collection → 从 PG 全量重嵌入 → 原子切换别名/配置 → 删旧 collection；
- collection 元信息（embedding 模型名 + 维度）写入 SystemSetting 或 collection 级记录，摄取前校验。

**Warning signs:** 日志出现知识 collection 的 `collection_deleted_for_recreate`；切换 embedding 配置后检索突然 0 结果。

**Phase to address:** 数据模型 phase（collection 生命周期管理与 indexer 路径显式分离）。

---

### Pitfall P9: GraphStore 接口形同虚设——递归 CTE 细节泄漏到调用方

**What goes wrong:**
项目决策"图访问收敛 GraphStore 接口，留换引擎逃生门"。实际开发中最容易发生：检索/工作流节点为了"快"直接写 `ChunkEdge.objects.raw(...)` 或自己拼递归 CTE，三个月后接口外散落十几处裸 SQL，逃生门焊死；同时每处裸查询都要各自记得 bi-temporal 过滤（回到 P2）。另一个变体：递归 CTE 不设深度上限/不防环，bi-temporal 边多版本共存时遍历空间膨胀，单查询拖垮 DB。

**How to avoid:**
- GraphStore 是唯一图查询入口，接口方法内置：有效性过滤（P2）、最大跳数（默认 ≤3，与基准调研一致）、环检测（CTE 路径数组判重）、权限维度参数；
- code review checklist：知识图谱相关 PR 中出现 `WITH RECURSIVE` 或对边表的 raw SQL 即打回；
- 性能基准测试随接口落地：1–3 跳查询在预期数据量（数千实体/数万边）下的延迟断言。

**Warning signs:** GraphStore 之外出现边表 import；图查询无 LIMIT/深度参数。

**Phase to address:** 数据模型 phase（接口先行，第一个调用方就走接口）。

---

### Pitfall P10: 多版本共存下"迭代轨迹"展示与检索的语义分裂

**What goes wrong:**
检索默认"只命中最新版"（P1 的 is_latest filter），但核心卖点之一是"召回相似历史需求及其**完整迭代轨迹**"。如果检索层把旧版本全部过滤掉，轨迹查询就无数据可用；如果为了轨迹放开过滤，又回到旧方案泄漏。两个需求共用一套查询路径时必然顾此失彼。

**How to avoid:**
- 显式区分两个查询面：**召回面**（向量检索，只查 `is_latest=true`）与**轨迹面**（按实体 natural key 走 DB 版本链 + bi-temporal 边历史，不走向量）；
- 检索结果返回实体 natural key，轨迹按 key 二次查询——向量库永远不需要存历史版本的可检索向量（旧版本向量物理删除是安全的，因为轨迹不依赖它）；
- 这个决策反过来简化 P1：旧向量"下线"= 删除即可，无需在 Qdrant 里保历史。

**Warning signs:** 需求评审中出现"检索时按时间参数返回旧版本向量"的设计；轨迹接口实现里出现 Qdrant 调用。

**Phase to address:** 数据模型 phase 定查询面边界；检索 phase 分别实现。

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 只靠 delete 下线旧向量、不加 is_latest 检索过滤 | 少一个 payload 字段和 filter | 漏删即正确性事故（P1），且无法事后发现 | Never |
| 各入口自己写摄取触发逻辑 | 入口开发互不阻塞 | 幂等/事务/异步坑每入口踩一遍（P3） | Never |
| chat 自然语言需求一律新建实体 | 跳过去重难题 | 图谱碎片化、轨迹断裂（P4） | MVP 可接受"新建 + 相似候选打 relates_to 边"，不可接受裸新建 |
| 需求/方案/diff 混一个 collection | 少管理一个 collection | 召回偏置难修，分库需全量迁移（P5） | 仅当上线前评测证明偏置可接受 |
| 时间衰减参数硬编码先上线 | 快 | 没有评测集时调参是盲调，参数永远"暂定" | MVP 可接受，但评测集必须同期开始积累 |
| 权限过滤留给调用方 | 检索 service 更"通用" | IDOR（本仓库已有同款前科），回填 payload 权限字段需全量重写 | Never |
| 绕开 QdrantService 直接用 qdrant client | 省接口适配 | 失去 timeout/keepalive/retry/可观测全部历史修复（P7） | Never |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Qdrant 删除/写入 | delete-by-filter 与 upsert 并发、默认 weak ordering，新点被误删（qdrant#6556） | `wait=True` 必加；版本切换走 set_payload tombstone + 按 point id 物理删；每个 filter 字段建 payload index |
| Qdrant collection | 沿用 create_collection 的"不匹配即删重建" | 知识 collection 拒绝自动重建，走显式重嵌入命令（P8） |
| 飞书 webhook | 同步做摄取，超时触发飞书重推 → 重复实体 | 复用 ProcessedEvent 幂等表 + run_in_background；webhook 路径只写摄取请求记录 |
| EmbeddingService | 假设模型/维度恒定 | 摄取前校验 collection 维度与当前配置一致；不一致报错不写入 |
| Django 异步 ORM | 请求循环里 asyncio.create_task 跑摄取（CurrentThreadExecutor 事故） | 一律 `run_in_background` + `transaction.on_commit` 触发 |
| ChunkRegistry/ChunkEdge 打通 | 给 chunk 加 FK 强约束，或假设 diff 引用的 chunk 一定已索引 | 沿用既有"柔性引用 + reconcile 兜底"模式（ChunkEdge 不做 FK 的先例） |
| workflow 节点 | 摄取失败 raise 穿透引擎 | 返回 `NodeResult(status="failed", error=...)`，遵循节点错误契约 |
| MCP/PAT 入口 | 复制 compat 层 AllowAny/直传 repository_ids 模式 | 复用 v0.2.0 McpToolView fail-closed + 权限下沉检索 service（P6） |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 单条大 batch upsert（2560 维 × 数千 points） | `upsert_vectors_*_failed` timeout 日志；摄取任务整体 FAILED | 分 batch ≤100 points；复用 QdrantService 60s timeout 基建 | 单 MR diff chunk 数 > 数百时（万行 diff 必现） |
| delete-by-filter 无 payload index | 删除耗时随 collection 增长线性上升，期间写放大 | 物理删除按 point id；filter 字段全部建 keyword index | collection 达数十万 points |
| 递归 CTE 无深度限制/防环 | 个别图查询秒级 → 分钟级；DB CPU 尖刺 | GraphStore 内置 max_hops≤3 + 路径判重（P9） | 边数过万且存在稠密互连实体 |
| 检索时实时计算时间衰减于全量候选 | 检索延迟随候选数线性增长 | 衰减只对 top-N（如 100）候选 re-rank | 候选池 > 数千 |
| 失效边不归档、主表无限膨胀 | 边表行数 = 活跃边 × 平均版本数；查询计划劣化 | `expired_at` 建索引 + 部分索引 `WHERE invalid_at IS NULL`；超阈值归档策略后置即可 | 版本迭代频繁的长期部署（一年以上） |
| 每条 chunk 单独调 embedding API | 摄取一个 MR 打数百次外网请求 | embedding 批量接口 + 并发上限 | diff chunk 数 > 50 |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| 检索 service 信任调用方传入的 project/repo 范围 | 跨项目读取需求/方案/diff（IDOR，本仓库 compat 层有同款前科） | 权限解析下沉 service 内部，调用方参数只能收窄（P6） |
| 新增 MCP/HTTP 入口默认 AllowAny | 未配置的部署对外裸奔知识库 | fail-closed 默认；复用 PAT 认证基建 |
| Qdrant payload 不存权限维度字段 | 想做权限过滤时无字段可滤，需全量回填 | 第一天起 payload 必含 project_id/repository_id + keyword index |
| diff 原文含密钥/token 被向量化并可检索 | 把 git 历史里的 secret 二次放大成可语义检索的泄漏面 | 摄取前过 secret 扫描规则（仓库 CI 已有 secret scanning 可借鉴），命中即脱敏后归档 |
| 越权检索返回 403/404 不一致 | 泄漏资源存在性 | 沿用 v0.2.0 惯例：越权返回空结果/404，不泄漏存在性 |
| 飞书 webhook 摄取路径跳过签名校验 | 伪造事件污染知识图谱 | 复用既有飞书签名校验中间件，摄取入口不开旁路 |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 检索命中旧版本方案但无任何版本标识 | 用户/agent 按过时方案行动，信任崩塌 | 结果必带 version + 时间 + 是否最新标记；过时命中显式标注 |
| 摄取是后台异步但 UI 无状态反馈 | 用户不知道需求有没有进图谱，重复触发 | 摄取请求记录暴露状态（pending/done/failed）可查 |
| 轨迹视图把系统时间当业务时间展示 | "方案创建于凌晨 3 点"之类错乱（实际是重摄取时间） | 展示 valid_at（业务时间），系统时间仅 debug 可见 |
| 去重自动合并不可见 | 用户发现两个需求"莫名"变一个，无法追溯 | 合并产生显式边 + 操作记录，可撤销 |

## "Looks Done But Isn't" Checklist

- [ ] **版本下线**：demo 里"重摄取后检索到新版"通过 ≠ 完成——验证**删除失败被注入时**检索仍只返回新版（is_latest filter 兜底生效），且 reconcile 命令能修复漂移
- [ ] **bi-temporal 查询**：单跳查询过滤正确 ≠ 完成——验证 2–3 跳图扩散路径上每一跳都过滤失效边；CI 在 UTC 时区下全绿
- [ ] **摄取幂等**：单次摄取成功 ≠ 完成——同一事件连发 3 次（模拟飞书重推），实体/向量数不变
- [ ] **多入口一致**：每个入口单独可用 ≠ 完成——同一需求飞书 + chat 双路进入，图中不产生孤立重复实体
- [ ] **大 diff**：常规 MR 通过 ≠ 完成——10k+ 行 lockfile 混合 diff 夹具下摄取成功且不超时、检索时 diff 不吃光 token 预算
- [ ] **权限**：功能测试通过 ≠ 完成——A 用户 PAT 检索 B 项目知识返回空；四个暴露入口逐一做越权用例
- [ ] **embedding 切换**：当前模型可用 ≠ 完成——切换维度不同的模型后摄取被拒绝并提示重嵌入，而非删库或静默失败
- [ ] **检索质量**："看起来相关" ≠ 完成——评测集（含中文 query → 英文 diff 用例）有量化基线，时间衰减参数变更有指标对比

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| 旧向量残留被检索到（P1） | LOW（若有 is_latest filter + DB registry）/ HIGH（若无） | 跑 reconcile 命令对账 DB ↔ Qdrant；无 registry 则只能全量重嵌入 |
| naive datetime 已入库（P2） | MEDIUM | 数据迁移按写入入口推断时区批量修正；之后约束拒绝 naive |
| 重复实体已产生（P3/P4） | MEDIUM | 写合并命令：按 natural key/相似度找重复对 → 保留主实体 → 边迁移 → 旧实体标失效；向量按 registry 删 |
| collection 被误删重建（P8） | MEDIUM | PG 原文是 source of truth，跑 reembed 命令全量重建；期间检索降级公告 |
| 混合 collection 召回偏置（P5） | HIGH | 分库需新建 collection + 全量重嵌入 + 检索层改造；尽量在设计期避免 |
| payload 缺权限字段（P6） | HIGH | 全量 scroll + batch_set_payload 回填，期间权限过滤不可用——必须第一天就做对 |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1 版本化向量漏删/竞态 | 数据模型 + 摄取管线 | 注入删除失败的混沌测试：检索仍只命中最新版；reconcile 修复漂移 |
| P2 bi-temporal 三连坑 | 数据模型（约束/接口）、检索（图扩散审计） | UTC CI 全绿；多跳路径失效边不可达测试；时间不变量监控为 0 |
| P3 摄取阻塞/重复 | 摄取管线 | webhook P95 < 500ms；同事件 3 连发幂等测试 |
| P4 多入口重复实体 | 摄取管线（含数据模型 natural key） | 飞书 + chat 双路摄取实体数断言 |
| P5 召回偏置/衰减盲调/跨语言 | 检索 | 评测集指标基线 + 类型分布断言（top-10 不被单类型刷屏） |
| P6 检索越权 | 数据模型（payload 字段）+ 多入口暴露（鉴权） | 四入口越权用例全部返回空；service 签名强制 user |
| P7 大 diff | 摄取管线 + 检索 | 10k 行 diff 夹具端到端通过；token 预算断言 |
| P8 collection 误删重建 | 数据模型 | 切换 embedding 配置后摄取报错而非删库的测试 |
| P9 GraphStore 泄漏 | 数据模型 | grep 审计：边表 raw SQL 仅存在于 GraphStore 实现内 |
| P10 召回面/轨迹面分裂 | 数据模型（边界决策）+ 检索（分别实现） | 轨迹接口不依赖 Qdrant；删除全部旧版本向量后轨迹仍完整 |

## Sources

- Qdrant 官方文档 Points / 一致性（delete-by-filter、update_mode、wait 语义）：https://qdrant.tech/documentation/manage-data/points/ — HIGH
- qdrant/qdrant#6556 "Delete request deletes vectorless points upserted right after it"（delete/upsert 竞态，官方回复 wait=True + strong ordering）：https://github.com/qdrant/qdrant/issues/6556 — HIGH
- Qdrant Low-Latency Search（indexed_only "blinking points"、更新 = delete+insert 语义）：https://qdrant.tech/documentation/search/low-latency-search/ — HIGH
- Zep/Graphiti bi-temporal 边模型（valid_at/invalid_at vs created_at/expired_at 双时间线、失效按 valid_at 排序）：https://blog.getzep.com/beyond-static-knowledge-graphs/ 与 arXiv:2501.13956 — HIGH
- OpenAI Cookbook "Temporal Agents with Knowledge Graphs"（失效级联与 invalidated_by 链接实践）：https://developers.openai.com/cookbook/examples/partners/temporal_agents_with_knowledge_graphs/temporal_agents — MEDIUM
- 本仓库代码与历史事故注释：`server/services/qdrant_service.py`（timeout/keepalive/health-check reset 三起事故）、`server/services/background_runner.py`（CurrentThreadExecutor 事故）、`server/feishu/models.py` ProcessedEvent、`server/compat/request_handler.py` IDOR TODO、`server/code_relations/models.py` 柔性引用/uuid5 模式、`.planning/codebase/CONCERNS.md` — HIGH
- 跨语言检索（中文 query ↔ 英文 diff）效果依赖 doubao-embedding-text 的多语言对齐，未经本项目实测 — LOW（已在 P5 标注需评测集验证）

---
*Pitfalls research for: 交付知识图谱（GraphRAG）on Friday AI brownfield*
*Researched: 2026-06-11*
