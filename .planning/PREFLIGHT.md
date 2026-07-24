# Friday AI · 前置修复 / 风险清单（PREFLIGHT）

> **作用**：把调研中发现的既有 bug / 漂移 / 一致性漏洞单独收口，**不混进里程碑功能描述**。每项标状态（verified / pending verification）与影响面（blocking / should-fix-before-vX / can-fix-in-milestone）。
>
> 进入对应里程碑前，先把 `pending verification` 的项核实清楚；`blocking` 的项必须先修。
>
> *最后更新：2026-06-14*

---

## 图例

- **状态**：`verified`（本会话已读码确认） / `pending`（来自外部 review，未亲自核实，需先验证）
- **影响面**：
  - `blocking` — 不修对应里程碑做不动
  - `should-fix-before-vX` — 该里程碑开工前先修
  - `can-fix-in-milestone` — 可在里程碑内顺带修

---

## 已验证（verified）

| ID | 问题 | 证据 | 影响里程碑 | 影响面 |
|----|------|------|-----------|--------|
| PF-01 | `ai_plan_generation` 调用工具名 `search_code`，注册名实为 `search_repository_code`；`build_langchain_tools` 对未知工具静默 `continue` → **server 端检索工具可能根本没生效** | `server/workflows/nodes/ai/plan_generation.py`、`server/agents/tools/space_tools.py`、`agents/tools/langchain_adapter.py` | v0.7 | should-fix-before-v0.7（方案质量地基） |
| PF-02 | `verify_plan` 校验字段是 `tasks`，schema 实为 `execution_plan` → **校验形同虚设** | `server/agents/tools/verify_plan.py` vs `server/workflows/schemas/technical_plan.py` | v0.7 | should-fix-before-v0.7（PlanValidator 依赖） |
| PF-03 | incremental 索引删除文件**只删 Qdrant，不删 FileIndex/ChunkRegistry** → 一致性漏洞 | `server/services/indexer.py`（incremental 路径 vs git_diff 路径） | v0.5 | should-fix-before-v0.5（排除清理依赖删除一致性） |
| PF-04 | `scan_directory` 注释声称"已应用 .gitignore"，**实际未实现**（仅目录名 + 扩展名白名单） | `server/services/code_parser.py`、`server/services/indexer.py` ~833 | v0.5 | can-fix-in-milestone（认知风险，排除机制开工时修正） |
| PF-05 | `QdrantService.delete_by_file_path` **只删主 collection，不删 branch overlay** | `server/services/qdrant_service.py` | v0.5 | should-fix-before-v0.5（排除需覆盖 overlay） |
| PF-06 | workflow 编码路径 `AICodingNode` **未注入 branch strategy / git token env**（chat 路径有）→ 私有仓 clone 可能失败、分支名落默认 | `server/workflows/nodes/ai/coding.py` vs `server/chat/coding_session_service.py` | v0.8 | should-fix-before-v0.8（多仓 wave 编码依赖） |
| PF-07 | `execution_plan[].dependencies` 仅 schema 声明 + prompt 提示，**下游全并行不读** | `server/workflows/nodes/ai/coding.py`、`technical_plan.py` | v0.8 | can-fix-in-milestone（v0.8 本身就要做 DAG 分层） |
| PF-08 | `CodeChangeArchive` **无 bi-temporal `invalid_at`**，master 演进后旧 `MODIFIES_CHUNK` 边不失效 | `server/knowledge/diff_archive.py`、`server/knowledge/models.py` | v0.6 | can-fix-in-milestone（历史 diff 冻结/失效本就是 v0.6 任务） |
| PF-09 | `get_work_item`/`get_comments` 默认 `work_item_type="story"`；真实 type 开放集（缺陷=`issue`）。不显式传真实 type 会取错/取空 | `server/feishu/client.py`、`server/services/feishu.py` | v0.6 | should-fix-before-v0.6（WorkItem upsert 依赖正确 type） |
| PF-10 | `get_work_item_relations` **实测 JSON 解析错（端点疑似失效）**；且工作项间关系实际在 `work_item_related_multi_select` 字段里（所属项目/迭代/版本），不在该端点 | `server/services/feishu.py:188` | v0.6 | should-fix-before-v0.6（关系建模改走字段派生） |
| PF-11 | `get_comments` **实测 JSON 解析错（端点疑似失效）** | `server/feishu/client.py:232`、`server/services/feishu.py` | v0.6 | should-fix-before-v0.6（评论摄取依赖） |
| PF-12 | `get_work_item` 把 `fields[]` 拍平成 `{field_key: field_value}`，**丢失 `field_name/field_type_key/field_alias`**（mirror 需要这些元数据） | `server/feishu/client.py:164-170`、`server/services/feishu.py` | v0.6 | should-fix-before-v0.6（WorkItem.feishu_fields 需完整对象） |

---

## 待验证（pending verification）

> 来自外部 review，**本会话未亲自核实**。进入相关里程碑前先验证真伪，再决定是否升级为 verified。
> 注：session 起始 `git status` 显示 `server/workflows/models/trigger.py`、`server/workflows/nodes/triggers/feishu_event.py`、`server/workflows/api/views.py` 有未提交改动，可能与下列项相关。

| ID | 待验证问题 | 涉及位置（待查） | 影响里程碑 | 影响面（暂定） |
|----|-----------|----------------|-----------|---------------|
| PF-P1 | 飞书 webhook URL 不一致 | `server/feishu/urls.py` / views | v0.6（飞书摄取） | pending → 待验证后定 |
| PF-P2 | `trigger_log.workflow_execution` 字段疑似不存在（写入会报错？） | `server/feishu/models.py` `TriggerLog` / 写入处 | v0.6 | pending → 待验证后定 |

---

## 详细条目（根因 / 复现 / 修复方向 / 验证）

### PF-01 · `search_code` 工具名漂移
- **根因**：`plan_generation.py` 的 system prompt 让 Agent 调 `search_code`，但工具注册名是 `search_repository_code`（`agents/tools/space_tools.py`）；`build_langchain_tools`（`agents/tools/langchain_adapter.py`）对未知工具名 `continue` 跳过 → Agent 调用静默失败，**server 端方案生成可能从未真正检索过代码**。
- **复现**：跑 `ai_plan_generation`，看 Agent 是否真的调用了检索工具（trace 里应有 tool_use，但实际无）。
- **修复方向**：统一工具名（prompt 改 `search_repository_code` 或给工具加别名）；`langchain_adapter` 对未知工具改为 **fail-loud**（记 error 而非静默跳过）。
- **验证**：单测断言 prompt 引用的每个工具名都在注册表；集成测试断言方案生成过程产生检索 tool_use。

### PF-02 · `verify_plan` schema 漂移
- **根因**：`verify_plan.py` 校验 `tasks` 字段，但 `technical_plan.py` schema 用 `execution_plan` → 校验恒不命中关键字段，形同虚设。
- **修复方向**：对齐到 `execution_plan`；作为 v0.7 `PlanValidator` 的基础并扩展（契约/依赖/迁移校验，DOMAIN §7）。
- **验证**：构造缺字段/坏依赖的方案，断言 validator 报错。

### PF-03 · incremental 删除一致性漏洞
- **根因**：`run_incremental_index` 删文件只调 `qdrant_delete_by_file_path`，不删 `FileIndex`/`ChunkRegistry`（对比 git_diff 路径会删 FileIndex）。→ 残留孤儿行 + 排除清理不彻底。
- **修复方向**：抽统一 `purge_file(repo_id, path)`（Qdrant 主+overlay + FileIndex + ChunkRegistry + codegraph），三条索引路径与排除清理共用。
- **验证**：删/排除一个文件后断言四个数据面无残留。

### PF-04 · `scan_directory` 注释谎称 .gitignore
- **根因**：`indexer.py` ~833 注释称"已应用 .gitignore"，实际 `scan_directory` 仅按目录名 + 扩展名白名单。
- **修复方向**：修正注释；排除机制落地时在此挂统一过滤函数。
- **验证**：放一个 .gitignore 命中文件，断言当前会被索引（暴露现状）→ 加排除后不被索引。

### PF-05 · `delete_by_file_path` 不删 overlay
- **根因**：`QdrantService.delete_by_file_path` 只作用主 collection，分支 overlay collection 残留。
- **修复方向**：扩展到 overlay（遍历该 repo 的 overlay collections）。
- **验证**：在有 overlay 的 repo 上排除文件，断言 overlay 也无该 file_path 的 point。

### PF-06 · workflow 编码路径 env 不一致
- **根因**：`AICodingNode` 未注入 `env_FRIDAY_TASK_BRANCH_STRATEGY`/git token（chat 路径 `coding_session_service` 有）→ 私有仓 clone 可能失败、分支名落默认 `friday/task-{id}`。
- **修复方向**：workflow 编码派发对齐 chat 路径的 env 注入。
- **验证**：workflow 编码私有仓任务能 clone + 用正确目标分支。

### PF-07 · `dependencies` 声明未被消费
- **根因**：`execution_plan[].dependencies` 仅 schema + prompt，`coding.py` 只按 repo 全并行。
- **修复方向**：v0.8 本就要做 DAG 拓扑分层 + wave（DOMAIN §6 `RepoCodingTask.depends_on`）。
- **验证**：构造跨仓依赖方案，断言 wave 顺序正确、产物注入下游。

### PF-08 · `CodeChangeArchive` 无 bi-temporal 失效
- **根因**：archive 按 commit 追加，无 `invalid_at`；master 演进后旧 `MODIFIES_CHUNK` 边不失效。
- **修复方向**：v0.6 历史 diff 冻结策略——commit 锚定 + 重索引时对账置 `invalid_at`（DOMAIN/ROADMAP v0.6）。
- **验证**：模拟 chunk 变更后重索引，断言旧边被置 invalid、查询按 as_of 区分。

### PF-09 · `work_item_type` 默认 story 取错
- **根因**：`get_work_item`/`get_comments` 默认 `work_item_type="story"`；真实开放集（缺陷=`issue`）。**实测** type=`project` 查容器型返回 `WorkItem Not Found(30005)`。
- **修复方向**：调用方强制传真实 type；`WorkItemService.upsert` 从 identity 取 type，不用默认。
- **验证**：对 issue/story 分别按正确 type 拉取成功（已实测）。

### PF-10 · `get_work_item_relations` 失效 + 关系实际在字段里
- **根因**：**实测**该端点返回非预期内容（`Extra data: line 1 column 5` JSON 解析错）。且工作项间关系实际经 `work_item_related_multi_select` 字段表达（`所属项目 field_000008`、`planning_sprint`、`planning_version`）。
- **修复方向**：`WorkItemRelation` 改为**从关联字段派生**（DOMAIN §12.3）；独立 relation 端点降级为可选/废弃，或核实正确端点路径。
- **验证**：从 story 1000000002 的 `field_000008=[1000000004]` 正确派生 belongs_to_project 关系。

### PF-11 · `get_comments` 失效
- **根因**：**实测** JSON 解析错（端点路径/格式疑似变化）。
- **修复方向**：核实飞书项目评论正确端点（可能 `comment/list` 路径或鉴权头有变），修复后再做评论事件流摄取。
- **验证**：拉取缺陷 1000000006 的评论列表成功并解析。

### PF-12 · `get_work_item` 拍平字段丢元数据
- **根因**：解析时 `fields_dict[field_key]=field_value`，丢弃 `field_name/field_type_key/field_alias`。而 mirror 需要这些（人类标签、别名 prd_url/小组、类型判断）。
- **修复方向**：`WorkItem.feishu_fields` 存**完整 `fields[]` 对象数组**；派生逻辑按 alias/type 提取。
- **验证**：断言能从 feishu_fields 取到 `prd_url` 别名字段、`小组` select 的 label。

- 每个里程碑 `/gsd-new-milestone` 前，先扫本清单中 `影响里程碑 = 该里程碑` 且 `影响面 ∈ {blocking, should-fix-before}` 的项，作为该里程碑的"前置修复" phase 或独立 quick fix。
- `pending` 项先 `/gsd-debug` 或读码核实，确认后移入"已验证"并定影响面；证伪则删除并记录。
- 本清单不替代里程碑需求；它是**风险/债务台账**，与功能需求分轨。