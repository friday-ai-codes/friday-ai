---
phase: 114-ai
plan: 04
requirements: [CLAR-02, CLAR-03]
provides:
  - "`BlueprintLifecycleService.areanchor_threads(artifact, new_content, *, old_content=None, initiated_by_user_id='system') -> dict` —— 批量重锚定的**唯一写通道**（INV-6）。返回**恒定四键** `{checked, reanchored, orphaned, skipped}`（全 int，下游无需判空分支）。受限面**纯追加**：`git diff … | rg '^-[^-]'` 空输出，删除行 = 0"
  - "`apply_block_ops(content: Any, ops: Any) -> tuple[dict, list[dict]]` 纯函数（无 IO / 无 ORM）：`replace` / `insert` / `delete` 三 op，`deepcopy` 后改（**入参不被原地修改**），**恒不抛**（垃圾入参也返回 `(dict, list)`）"
  - "`async def aapply_block_edit(artifact, ops, *, user=None, initiated_by_user_id='system', session_id='', artifact_service=None, lifecycle_service=None) -> dict` —— 人工编辑 service 收口，恒定六键 `{status, version_id, version_no, rejected, detail, reanchor}`，`status ∈ {applied, unchanged, rejected, invalid}`"
  - "⭐ `async def aapply_thread_answers(artifact, *, threads=None, session=None, initiated_by_user_id='system', section_writer=None, artifact_service=None, lifecycle_service=None) -> dict` —— 澄清答案回灌，恒定七键 `{status, version_id, version_no, thread_ids, conflict_block_ids, thread_id, detail}`，`status ∈ {applied, unchanged, conflict, invalid, noop}`"
  - "⭐ `async def ablock_section_writer(content: dict, answers: list[dict], *, session=None) -> dict` —— B1 生产段落重产，`aapply_thread_answers` 的**默认** writer（`section_writer or ablock_section_writer`，**不是 no-op**）"
  - "⭐ `async def acollect_human_block_ids(artifact) -> list[str]`（只读，升序去重）与 `async def arestore_human_blocks(artifact, *, initiated_by_user_id='system', session=None, artifact_service=None, lifecycle_service=None) -> dict`（恒定六键 `{status, preserved, conflicted, thread_id, version_id, version_no}`，`status ∈ {noop, unchanged, restored, conflict}`）—— B3 人工块保护入口，**本 plan 只交付与单测，接线归 114-03**"
  - "纯函数三件：`build_decision_entries(threads_payload: list[dict]) -> list[dict]` / `merge_decision_log(existing: Any, entries: list[dict]) -> list[Any]`（按 `thread_id` 去重）/ `detect_human_conflicts(*, human_version_content, human_base_content, ai_new_content) -> list[str]`（**全 keyword-only**，返回升序交集）"
  - "`DECISION_LOG_KEYS = ('thread_id', 'question', 'answer', 'decided_at', 'decided_by', 'applied_in_version')` —— 规格门形状的超集，**`answer` 键必保**（`blueprint_spec_gate._collect_prior_answers:587` 读的是 `item.get('answer')`）"
  - "`produced_by_ref` 三前缀常量：`HUMAN_EDIT_PREFIX='human_edit:'` / `AI_REVIEW_REFLOW_PREFIX='ai_review_reflow:'` / `HUMAN_BLOCK_RESTORE_PREFIX='human_block_restore:'`；`RETURN_STAGE_AI_REVIEWING='ai_reviewing'`"
  - "上界常量实测值：`_MAX_REWRITE_BLOCKS=5` / `_MAX_BLOCK_PROMPT_CHARS=4000` / `_MAX_REWRITTEN_TEXT_CHARS=4000` / `_MAX_QA_PROMPT_CHARS=2000` / `_MAX_DETAIL_CHARS=500` / `_MAX_CONFLICT_IDS=20`（reflow）；`_MAX_DETAIL_CHARS=500`（block_edit）"
  - "`rejected[].reason` 全枚举（6 值）：`unknown_op` / `block_not_found` / `missing_block` / `missing_block_id` / `block_id_immutable`（**提示级，不阻断**）/ `apply_failed`"
affects:
  - "⭐ 114-03（ai_review stage adapter）：入口按 `arestore_human_blocks` → `aapply_thread_answers` → 判定 的顺序接线；三个契约的逐字签名与 status 语义见下方「114-03 接线契约」全表。`arestore_human_blocks` 返 `conflict` 时**必须停等**（已开阻塞线程），不可继续跑判定"
  - "114-05（人审端点）：`aapply_block_edit` 供 `edit-blocks` 端点；`threads answer` 端点在 `record_answer` 之后同请求内接 `aapply_thread_answers`；`areanchor_threads` 供任何产新版本的路径复用"
  - "115（查看器）：失锚批注经 `BlueprintThread.objects.filter(anchor_status='orphaned')` 集中查询；`anchor.section_path` 已被重锚定一并刷新，可直接用于定位；回灌产出版本经 `produced_by_ref == f'ai_review_reflow:{thread_id}'` 反查"
  - "114-05 的 `blueprint_quality.human_edit_volume`：用 `produced_by_ref__startswith='human_edit:'` 统计（`ArtifactVersion` **无** `created_by_user_id`）"
key-files:
  created:
    - server/delivery/services/blueprint_block_edit.py
    - server/services/process_runtime/blueprint_reflow.py
    - server/tests/delivery/test_blueprint_reanchor_edit.py
    - server/tests/services/process_runtime/test_blueprint_reflow.py
  modified:
    - server/delivery/services/blueprint_lifecycle_service.py
completed: 2026-07-31
---

# Phase 114 Plan 04: 澄清回灌与人工编辑（线程 × 版本闭环）Summary

**一行结论**：补齐「线程 ↔ 版本」的双向闭环 —— 新建 `blueprint_block_edit.py`（359 行）与 `blueprint_reflow.py`（1008 行），在 `blueprint_lifecycle_service.py` 文件尾**纯追加** 169 行的 `areanchor_threads`（删除行 **0**），两个测试文件（545 + 784 行，**39 例**）把四条头号可证伪点锁死：**同一问题不重复问**（复用读侧 `_collect_prior_answers` 断言，且配了会失败的对照）、**AI 不覆盖人工**（回灌侧冲突零版本增长 + 重装侧人工块逐字写回）、**同 content_hash 不翻版本**（回灌与编辑两处各一条）、**失锚线程不删且可集中查询**。`tests/delivery/` **655 passed** + `tests/services/process_runtime/` **573 passed**（合计 **1228** = 114-02 收官的 1189 + 本 plan 39，**零回归**），`makemigrations --check` 退出码 **0**（零 migration），ruff check + format 全通过。

## Accomplishments

- **批量重锚定就位且保住 111 单测立的六条行为契约**。`areanchor_threads` 是 111 交付的单条 `reanchor` 算法的**唯一批量调用方**，`blueprint_anchor.py` **一行未改**（`git diff` 空）。三处关键实现细节：
  - ⭐ **入参不被原地修改**：`reanchor` 的精确命中分支返回的是**同一对象**（111 契约 `new_anchor is anchor`），直接写 `section_path` 会原地污染入参 dict。实现里先 `dict(new_anchor)` 拷贝再写 —— 测试 `test_reanchor_never_mutates_the_anchor_it_receives` 专挡这条回归。
  - ⭐ **`section_path` 一并刷新**：`reanchor` 只改 `block_id`、**不碰 `section_path`**（RESEARCH §4.2 实测的缺口）。批量侧用 `iter_blocks(new_content)` 的 path 补刷；**被 `skipped` 的线程也刷** —— 块内容没变但段落可能被改名/移位，漏刷会让 115 把批注挂在错误的段落标题下。
  - ⭐ **P3 性能防护**：`diff_blueprint_blocks(old_content, new_content)` 预筛出 `added ∪ removed ∪ modified`，只有 anchor 落在变动集合内（或 block_id 为空/已消失）的线程才走准平方级的 `reanchor`。`old_content=None` 退化为全量重锚（正确性优先）。测试 `test_diff_prefilter_skips_untouched_threads_and_matches_full_scan` 同时断言 `skipped >= 9` **和两种模式最终 anchor 结果一致** —— 预筛是纯性能优化，不改变正确性。
- **失锚不删**：`anchor_status="orphaned"` 的线程行原样保留，`anchor` 内容逐字不动，`filter(anchor_status="orphaned")` 可集中查询（CLAR-02 明令批注不得静默消失）。新增段 `rg "\.delete\(\)"` 零命中。
- **一次 `bulk_update` + 显式 `updated_at`**：`bulk_update` / `.update()` **绕过 `auto_now`**，实现里显式带 `updated_at=timezone.now()`（同 `_apply_transition_sync:243-244` 的既有纪律）。测试记录调用前时间戳并断言调用后 DB 重读**严格大于** —— 漏带即红。
- **人工编辑经 service 收口，五步顺序固定**（照 `blueprint_confirm_gate.alock`）：读最新版本作基线 → `apply_block_ops` → **显式 `validate_blueprint`** → `add_version(produced_by_ref="human_edit:{user_id}")` → 重锚定 + `add_reviewer(…, "block_edit")`。三条 fail-closed 分层：结构性硬失败 → `rejected`；语义不合法 → `invalid`（`detail` 是可直接回显的中文错因）；`add_version` 自身的 `ArtifactContentInvalid` → `invalid`。三条**都不落版本**，测试断言 `ArtifactVersion.objects.acount()` 与调用前相等。
- **`rejected` 如实上报，绝不静默跳过**（静默跳过 = 用户以为改了其实没改，是最坏的编辑体验）。`block_id_immutable` 是**提示级**条目：`replace` 时用户试图改 `block_id` 一律以**原 id** 为准（改 id 会把该块上的全部线程 anchor 打散），但不阻断编辑，随成功结果一并回显。
- **⭐ 答案真的落地（B1）**：`section_writer` 缺省即 `ablock_section_writer` 生产实现，不是「默认 None ⇒ 跳过段落重产」。若停在 no-op，答案只进 `decision_log` 而蓝图正文永不更新，「答案回灌产新版本」就只剩一条日志行（T-114-23c）。测试用 monkeypatch 断言**默认 writer 被调用一次且入参含 answers**，再并列断言「writer 原样返回 content 时 `decision_log` 仍被物化、线程仍 resolved」—— 答案不因段落未改写而丢失。
- **⭐ AI 不覆盖人工，两条链路各一个入口**：
  - **回灌侧**（T-114-23）：`detect_human_conflicts` 求「人工改过 ∩ AI 将改写」的交集，非空 ⇒ **不落版本**，改开 `kind=ai_clarification, blocking=True, return_stage="ai_reviewing"` 的阻塞线程询问。测试正反并列：改人工改过的块 → `conflict` 且版本行数不变；改人工没碰过的块 → `applied` 且版本 +1（证明判据非恒真）。
  - **重装侧**（T-114-23b，B3）：`repo_rework`/`remerge` 重装是主要产版本路径，回灌侧的检测**挡不住它**。`arestore_human_blocks` 逐块 canonical JSON 比对，实质冲突则把**人工基准块写回**并开阻塞线程。头号断言：冲突后新版本的 block X 内容与人工版本**逐字相等**。
- **幂等由稳定 `decided_at` 保证**：`decided_at` 取**最后一条 human 消息的 `created_at`**，不是 `timezone.now()`。回灌是可重放路径，时间戳每次变会改 `content_hash`（`sort_keys=True` 只消除 key 顺序影响、不消除值的影响）⇒ 每次回灌都翻新版本、版本历史被刷成噪声（T-114-25）。测试连续回灌两次断言第二次 `unchanged` 且版本行数不变。
- **`anchor` 不进 `decision_log`**：`build_decision_entries` 的条目带 `anchor` 只为传给段落重产 writer，`merge_decision_log` 按 `DECISION_LOG_KEYS` 投影时把它剔除 —— anchor 随重锚定漂移，写进 content 会让同一决策在不同版本下 hash 不同，同样破坏「同 hash 不翻版本」。
- **观测合规**：本 plan 新增的 **12 条**事件全部带 `category` + `component`，关键生命周期带 `duration_ms`（AST 扫描三文件的 `logger.*` 调用，新增段**零缺漏**）。`caller` 类 9 条（`blueprint_threads_reanchored` / `blueprint_threads_reanchor_failed` / `blueprint_block_edit_applied` / `blueprint_block_edit_invalid_content` / `blueprint_reflow_applied` / `blueprint_reflow_human_conflict_detected` / `blueprint_reflow_invalid_content` / `blueprint_reflow_resolve_thread_failed` / `blueprint_reflow_failed` / `blueprint_reflow_restore_invalid_content` / `blueprint_human_blocks_restored` / `blueprint_reflow_restore_failed`），`sampling` 类 3 条（`blueprint_reflow_section_rewritten` / `blueprint_reflow_section_rewrite_failed` / `blueprint_reflow_collect_human_blocks_failed`）。**anchor 的 `quoted_text`、block 正文、问题与答案一律不进日志**（T-114-27），异常文本走 `redact_secrets_in_text`。
- **零新增 `CallSource` 枚举值**：段落重产复用 111 已注册的 `CallSource.BLUEPRINT_AI_REVIEW`，`git diff server/agents/call_source.py` 为空。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `b9ca4e93` | `areanchor_threads` + `_reanchor_threads_sync`（文件尾纯追加 169 行）+ `apply_block_ops` 三 op 纯函数与 `rejected` 六 reason |
| 2 | `82384067` | `aapply_block_edit` service 收口 + 新建 `blueprint_reflow.py`（回灌三步链 / `decision_log` 物化 / `ablock_section_writer` / B3 人工块保护双入口） |
| 3 | `9500af9b` | `test_blueprint_reanchor_edit.py`「守十件事」16 例 + `test_blueprint_reflow.py`「守九件事」23 例 |

本次续跑（收官）未发现需要修复的缺陷，**无 `fix(114-04)` 提交**。

## Files

- `server/delivery/services/blueprint_lifecycle_service.py`（**受限面纯追加** +169 / −0）
- `server/delivery/services/blueprint_block_edit.py`（新建，359 行）
- `server/services/process_runtime/blueprint_reflow.py`（新建，1008 行）
- `server/tests/delivery/test_blueprint_reanchor_edit.py`（新建，545 行 / 16 个 `def test_`）
- `server/tests/services/process_runtime/test_blueprint_reflow.py`（新建，784 行 / 23 个 `def test_`）

合计 **+2865 / −0**（`git diff --stat 8320f5c6..HEAD`）。

## 114-03 接线契约（下游按此逐字消费）

### 入口顺序（`ai_review` stage 进入时）

```
arestore_human_blocks(artifact, …)   # ① 先保护人工块（重装可能已抹掉它们）
        ↓ status == "conflict" ⇒ 停等（已开阻塞线程），不要继续跑判定
aapply_thread_answers(artifact, …)   # ② 再消费已作答线程（答案 → 新版本）
        ↓ status == "conflict" ⇒ 同样停等
run_mechanical_rules(...) / agoal_backward_review(...)   # ③ 最后才跑 114-02 的判定内核
```

`areanchor_threads` **无需 114-03 显式调用**：①②内部落新版本后已各自调用它。仅当 114-03 自己产新版本（如打回改写）时才需要显式接。

### ① `acollect_human_block_ids` / `arestore_human_blocks`（人工块保护，B3）

```python
async def acollect_human_block_ids(artifact: Any) -> list[str]
async def arestore_human_blocks(
    artifact: Any, *, initiated_by_user_id: str = "system", session: Any = None,
    artifact_service: Any = None, lifecycle_service: Any = None,
) -> dict
```

- **`acollect_human_block_ids` 返回**：升序去重的 `block_id` 列表（确定性）。保护集 = 版本链中 `produced_by_ref__startswith="human_edit:"` 的版本，各自与其 `supersedes` 做 `diff_blueprint_blocks` 取 **`added ∪ modified`** 的并集。
  - `removed` **不进**保护集 —— 人工删掉的块无内容可保护，硬塞回去等于替用户撤销他自己的删除。
  - `supersedes is None`（首版即人工编辑）⇒ 基线取 `{}` ⇒ 全文入保护集（保守优先）。
  - **只读**（`select_related("supersedes")` 防 async 裸 lazy-FK），整体 `try/except` → `[]`（保护集读失败不该阻断审查）。
  - 判据依据：`ArtifactVersion` **无 `created_by_user_id` 字段**，`produced_by_ref` 前缀是全仓唯一的人工归属通道。

- **`arestore_human_blocks` 恒定六键**：`{status, preserved: list[str], conflicted: list[str], thread_id: str, version_id: str, version_no: int}`

  | status | 语义 | 版本 | 线程 |
  | ------ | ---- | ---- | ---- |
  | `noop` | 无 `human_edit:` 版本 / 无版本 / 整体异常 | 不变 | 无 |
  | `unchanged` | 保护集里的人工内容**仍逐字在位** | 不变 | 无 |
  | `restored` | 有块写回但无冲突需裁决（当前实现下不出现，保留给未来「等价归一」场景） | +1 | 无 |
  | `conflict` | 有块实质冲突 ⇒ **人工块已写回新版本** + **已开阻塞线程**等裁决 | +1（若有块可写回） | 有 |

- **「AI 不得覆盖人工内容；冲突开线程」的操作语义**（逐块判定）：
  1. 取**最新**版本作当前态、最近一条 `human_edit:` 版本作人工基准（⛔ **不读 `session.current_artifact_version`**）。
  2. 对每个 `block_id ∈ protected`，用 **canonical JSON**（`json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`，与 `artifact_service._content_hash` 的 hash 口径**同源**）比对当前态块与人工基准块。用 canonical 串而非 dict `==`：`==` 对键顺序不敏感但对数值类型敏感（`1` vs `1.0`），JSON 往返后类型可能变。
  3. **相等** ⇒ 人工内容仍在，无事。
  4. **不等** ⇒ 实质冲突：把**人工基准块 `deepcopy` 写回**当前 content（`current_block.clear()` + `update()`，保持原 dict 身份以维持它在 content 树中的落位），记进 `conflicted` **和** `preserved`。
  5. **当前态块整体缺失** ⇒ 记 `conflicted` 但**不写回**（没有落位可写，**绝不猜落位**），只开线程请人裁决。
  6. `conflicted` 非空 ⇒ `open_thread(kind=ThreadKind.AI_CLARIFICATION, blocking=True, question=<只列 block_id + 裁决提示>, anchor={"block_id": conflicted[0]}, created_on_version=<当前最新版本>, return_stage="ai_reviewing")`。
  7. 有块写回才 `add_version(produced_by_ref=f"human_block_restore:{base.version_no}")`；`ArtifactContentInvalid` → warning + `noop`（**不落半合法版本**）；同 hash 复用 current → `unchanged`。落新版本后调 `areanchor_threads`。
  8. 整体 `try/except` → `noop` + warning，**绝不上抛**（保护失败不该把 stage 打成异常；114-03 据 `status` 决定是否停等）。

### ② `areanchor_threads`（批量重锚定）

```python
async def areanchor_threads(
    self, artifact: Artifact, new_content: dict, *,
    old_content: dict | None = None, initiated_by_user_id: str = "system",
) -> dict
```

- **恒定四键**：`{"checked": int, "reanchored": int, "orphaned": int, "skipped": int}`。
- **触发时机**：任何**产出新版本**之后（人工编辑 / 澄清回灌 / 人工块保护写回 / 114-03 自己的打回改写）。同 hash 未翻版本时**不必调**（块序列逐字未变）。
- **`old_content` 语义**：给了就走 `diff_blueprint_blocks` 预筛（只重锚受影响线程，`skipped` 计其余）；给 `None` 退化为**全量重锚**（正确性优先）。两种模式最终 anchor 结果**等价**（已由测试断言）。
- **失锚线程的去向**：`anchor_status` 置 `"orphaned"`，**线程行保留、`anchor` 内容逐字保留**、**绝不删除或隐藏**。经 `BlueprintThread.objects.filter(anchor_status="orphaned")` 集中查询（115 展示「失锚评论」）。
- **写回**：一次 `bulk_update(["anchor", "anchor_status", "updated_at"])`，显式带 `updated_at=timezone.now()`。
- **best-effort**：任何异常 → warning + 返回全零四键，**绝不上抛**（重锚定失败不该让「编辑已成功」变成 5xx；版本已落库，下次编辑会再试）。
- `new_content` 非 dict ⇒ 直接返回全零四键。

### ③ `aapply_thread_answers`（澄清答案回灌）

```python
async def aapply_thread_answers(
    artifact: Any, *, threads: Any = None, session: Any = None,
    initiated_by_user_id: str = "system", section_writer: Any = None,
    artifact_service: Any = None, lifecycle_service: Any = None,
) -> dict
```

- **恒定七键**：`{status, version_id: str, version_no: int, thread_ids: list[str], conflict_block_ids: list[str], thread_id: str, detail: str}`

  | status | 语义 |
  | ------ | ---- |
  | `applied` | 已落新版本 + 线程 `resolved` + 已重锚定 |
  | `unchanged` | 同 `content_hash` 复用 current ⇒ **不翻版本**、不重复 resolve、不重复重锚（重放安全） |
  | `conflict` | AI 将改写的块与人工编辑冲突 ⇒ **不落版本**，已开阻塞线程，`conflict_block_ids` / `thread_id` 可回显 |
  | `invalid` | 改写后 content 不过校验 ⇒ **不落版本、不落半合法版本、不落 failed**；或整体异常（`detail == "reflow_failed"`） |
  | `noop` | 无版本 / 无待消费线程 / 无有效答案 |

- **三步反流链（顺序固定，先落版本再转状态）**：
  1. **改 content**：读**最新**版本作基线（⛔ 不读 `session.current_artifact_version`）→ `copy.deepcopy(base.content)` → 段落重产（`writer = section_writer or ablock_section_writer`）→ 冲突检测 → `content["decision_log"] = merge_decision_log(content.get("decision_log"), entries)`。
  2. **`add_version`**：`produced_by_ref=f"ai_review_reflow:{primary_thread_id}"`（`primary_thread_id` = 条目列表第一条的 `thread_id`）。`ArtifactContentInvalid` → `invalid`。
  3. **收尾**：逐条 `resolve_thread(row, resolution=f"答案已回灌，产出版本 v{version_no}。")`（单条失败只 warning、不牵连整轮）→ `areanchor_threads(artifact, content, old_content=base.content)`。
  > 顺序不可颠倒：状态已 `drafting` 而内容未更新的窗口里，AI 会拿旧内容重跑。

- **`decision_log` 物化键（`DECISION_LOG_KEYS`，6 键）与取值来源**：

  | 键 | 取值来源 |
  | -- | -------- |
  | `thread_id` | 线程 id（**去重键**） |
  | `question` | **首条** `author_type == "ai"` 消息的 body |
  | `answer` | **全部** `author_type == "human"` 消息 body 的 `"；".join`（⚠️ **此键必保**） |
  | `decided_at` | **最后一条 human 消息的 `created_at.isoformat()`** |
  | `decided_by` | 默认 `"human"`；有 `author_id` 取 `str(author_id)`；AI 侧由调用方传 `decided_by="ai"` |
  | `applied_in_version` | **基线版本 id**（`str(base.id)`），见下 |

  `answer` 为空的线程整条丢弃（无答案不成决策）。`anchor` 只随内存条目传给 writer，**不进 `decision_log`**。

- **⚠️ 幂等规则（`decided_at` 取答案消息时间戳）**：`decided_at` **绝不用 `timezone.now()`**。回灌是可重放路径，时间戳每次变 ⇒ `content_hash` 变 ⇒ 每次都翻新版本，破坏「同 hash 不翻版本」。取作答消息的 `created_at` 后，重放时 `merge_decision_log` 按 `thread_id` 去重、条目值逐字不变 ⇒ hash 不变 ⇒ 返回 `unchanged`。

- **`applied_in_version` 的落地口径与反查**：取**基线版本 id**（「答案是在哪一版之上被应用的」），**不是产出版本 id** —— 产出版本 id 由 `add_version` 在写库时生成、**写入前不可知**；为填自身 id 而二次 `add_version` 会额外翻一版并破坏幂等。
  **产出版本反查**（115 消费面依赖）：`ArtifactVersion.objects.filter(artifact=…, produced_by_ref=f"ai_review_reflow:{thread_id}")`，或沿 `supersedes` 链取 base 的后继。（`BlueprintThreadMessage` 无「结论」字段，结构化留痕只能进 `decision_log`。）

- **冲突判据**：`base.produced_by_ref` 以 `human_edit:` 开头则 base 即人工版本，否则沿版本链取最近一条人工版本；`human_base = human_version.supersedes.content`（为 None 取 `{}`）；`detect_human_conflicts` 返回 `human_changed ∩ ai_changed` 的升序列表。

- 整函数 `try/except` → `{"status": "invalid", "detail": "reflow_failed"}`，**绝不上抛**（回灌失败不该把会话打成 FAILED）。

### ④ `ablock_section_writer`（默认段落重产，B1）

```python
async def ablock_section_writer(content: dict, answers: list[dict], *, session: Any = None) -> dict
```

- **默认注入方式**：`aapply_thread_answers` 内 `writer = section_writer or ablock_section_writer` —— `section_writer=None` **不等于跳过段落重产**。测试要 no-op 时**显式注入桩**，不靠默认值。
- 入参 `content` **不被原地修改**（内部先 `deepcopy`），返回新 content dict。
- 逐条按 `entry["anchor"]["block_id"]` 用 `iter_blocks` 定位块；**找不到就跳过**（warning，**不新建块** —— 凭 LLM 猜落位是把答案写到错误段落的最快路径）。
- 单块单次 LLM 改写：`with use_call_source(CallSource.BLUEPRINT_AI_REVIEW)`，重依赖全在函数内 lazy import；期望响应 `{"text": str}`。
- **`block_id` / `type` 逐字不变**（改 id 会把该块上的全部线程 anchor 打散）。table 型（`rows`）**不交给 LLM 改写**（行列语义易被打乱成不可对齐的表格）。
- 上界：一轮最多改写 `_MAX_REWRITE_BLOCKS = 5` 块，超出的答案**只进 `decision_log`** 并记 warning。
- **块级降级语义**：LLM 不可得（无 `default_model`）/ 响应不可解析 / 块找不到 / 整体异常 ⇒ **该块（或全部块）正文原样保留**，而 `decision_log` 物化与线程收尾**照常**由 `aapply_thread_answers` 完成 ⇒ **答案永不丢失**。

### ⑤ `aapply_block_edit` / `apply_block_ops`（人工编辑，供 114-05）

```python
def apply_block_ops(content: Any, ops: Any) -> tuple[dict, list[dict]]
async def aapply_block_edit(
    artifact: Any, ops: Any, *, user: Any = None, initiated_by_user_id: str = "system",
    session_id: str = "", artifact_service: Any = None, lifecycle_service: Any = None,
) -> dict
```

- **op 形状**：`{"op": "replace"|"insert"|"delete", "block_id": str, "block": dict | None, "position": "before"|"after"}`（`insert` 用 `block_id` 作锚点 + `position`，缺省 `after`；新 block 必须自带非空 `block_id`）。
- **`rejected[].reason` 全枚举**：`unknown_op` / `block_not_found` / `missing_block` / `missing_block_id` 为**硬失败**（返回 `rejected` 且不落版本）；`block_id_immutable` 为**提示级**（不阻断，随成功结果回显）；`apply_failed` 为整体兜底。
- **`aapply_block_edit` 恒定六键**：`{status, version_id, version_no, rejected, detail, reanchor}`，`status ∈ {applied, unchanged, rejected, invalid}`。
- `produced_by_ref = f"human_edit:{user_id}"`（`user_id` 取 `getattr(user, "id", "")`，回落 `initiated_by_user_id`，再回落 `"system"`；字段 `max_length=255`，uuid 长度安全）。
- 成功落新版本后：`areanchor_threads(…, old_content=base.content)` → `add_reviewer(artifact, user, "block_edit")`（`user is None` 时跳过；`aget_or_create`，已在名单则 `first_action` **不覆盖**）。

## Decisions

- **`arestore_human_blocks` 的「当前态块整体缺失」不写回，只开线程**：块被重装移除后没有可靠落位可插（父容器与索引都已不存在），凭猜落位写回等于把人工内容塞进错误段落。记 `conflicted` 但不记 `preserved`，交人裁决。这也是 `status="restored"` 在当前实现下不出现的原因 —— 只要有块被写回就必然同时有冲突。
- **`preserved` 与 `conflicted` 的关系是包含而非互斥**：`preserved` = 「实际写回了的块」，是 `conflicted` 的子集（差集 = 缺失落位无法写回的块）。114-03 判「是否需要停等」一律看 `status == "conflict"` 或 `conflicted` 非空，**不要看 `preserved`**。
- **canonical JSON 而非 dict `==` 作人工块比对判据**：与 `artifact_service._content_hash` 的口径同源，保证「块是否变了」与「版本是否翻」两处判断不会各说各话。dict `==` 对 `1` / `1.0` 敏感而 JSON 往返后类型可能变，会产生假冲突。
- **`acollect_human_block_ids` 的 `removed` 不进保护集**：人工删掉的块无内容可保护，把它塞回去是替用户撤销他自己的删除 —— 比 AI 覆盖人工更糟（用户明确表达过的意图被反转）。
- **`skipped` 的线程仍刷 `section_path`**：预筛只是跳过昂贵的相似度扫描，不是跳过这条线程。块内容没变但它所在的段落可能被改名或移位，漏刷会让 115 定位到错误标题下。因此「刷 path」本身也算一次写、进 `to_update`。
- **`decision_log` 只存 6 个投影键，`anchor` 被剔除**：anchor 随重锚定漂移，写进 content 会让同一决策在不同版本下产生不同 hash，与 `decided_at` 用 `timezone.now()` 是同一类幂等破坏。
- **回灌的 `produced_by_ref` 只带 `primary_thread_id`（首条）而非全部线程 id**：`produced_by_ref` `max_length=255`，批量回灌时拼全部 uuid 会溢出。全量 `thread_ids` 从返回值取，或从新版本 content 的 `decision_log` 反查（后者是持久的）。

## Deviations from Plan

共 2 处，均为**验收命令字面 vs 意图**的判读，无功能性偏离，无需改码。

**1. [Rule 3 - PLAN 验收字面与 action 要求自相矛盾] 四条 `rg … 零命中` 的验收项在 docstring 上命中，按「代码层零使用」判读**

- **Found during:** 收官验证（Task 2 acceptance）
- **Issue:** PLAN 的 `<action>` 明确要求把四条禁令逐字写进 docstring（「⛔ 绝不用 `record_answer`」「⛔ 绝不读 `session.current_artifact_version`」「`decided_at` 取作答消息 `created_at` 而非 `timezone.now()`」「`ArtifactVersion` 无 `created_by_user_id`」），而 `<acceptance_criteria>` 又要求这四个 token `rg` **零命中**。两者不可能同时满足 —— 按字面执行验收就必须删掉 PLAN 亲自指定的纠偏文案。同款矛盾 114-02 已遇到并按相同方式判读（见 114-02-SUMMARY 偏离 1）。
- **Fix:** 按验收意图（「代码不使用这些东西」）判读为**执行代码层零使用**，并用 **AST 剥离 docstring 后**逐条实测坐实，而非靠 grep 上下文目测：`ast.parse` → 去掉 module/class/function 的首个字符串常量表达式 → `ast.unparse` 后搜四个 token，`blueprint_block_edit.py` 与 `blueprint_reflow.py` **均为 0 命中**。纠偏文案保留 —— 那正是防将来有人「优化」掉这些纪律的唯一书面依据。
- **Files modified:** 无（判读差异，非代码改动）
- **Commit:** —

**2. [Rule 3 - 环境] `pytest … | tail -30` 的汇总行被 teardown 警告刷掉，改按套件分别取数**

- **Found during:** 收官验证
- **Issue:** `tests/delivery/` 的临时 git 仓 fixture 在 teardown 时产生 ~30 行 `rm_rf` / `PermissionError` 警告（macOS 沙箱对 `.git` 目录的 `scandir` 限制），把 `N passed` 汇总行挤出 `tail -30` 窗口。纯环境现象，与本 plan 无关（退出码 0）。
- **Fix:** 改为分套件各跑一次并 `rg "passed|failed"` 取数，得到确切计数（见下）。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

### 测试计数（与 114-02 收官基线逐条比对）

| 套件 | 114-02 收官基线 | 本 plan 后 | 增量 |
| ---- | --------------- | ---------- | ---- |
| `tests/delivery/` | 639 passed | **655 passed** | +16 |
| `tests/services/process_runtime/` | 550 passed | **573 passed** | +23 |
| **合计** | **1189** | **1228 passed** | **+39** |

**零 failed / 零 error / 零回归**，增量与两个新测试文件的 `def test_` 数（16 + 23 = 39）**逐一对应**。`tests/delivery/ tests/services/process_runtime/` 合并跑退出码 **0**。

### 门禁

- `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**（**零 migration**；全相位唯一的 `BlueprintThread.last_reminded_at` 由 114-05 承载）。
- `uv run ruff check`（5 个文件，含 `blueprint_lifecycle_service.py`）→ **All checks passed!**
- `uv run ruff format --check`（**只对 4 个新建文件**，受限面 `blueprint_lifecycle_service.py` 按纪律不跑 format）→ **4 files already formatted**。

### 受限面 / 冻结面自检（`git diff 8320f5c6..HEAD`）

- **改动文件恰为 PLAN 声明的 5 个**，`--stat` 为 **+2865 / −0**（全文件零删除行）。
- ⭐ **受限面纯追加证据**：`git diff … -- server/delivery/services/blueprint_lifecycle_service.py | rg "^-[^-]"` → **空输出**（退出码 1，删除行 = 0）。diff hunk 仅一处：`@@ -1239,6 +1239,175 @@`（文件尾追加）。
- **冻结面 14 个文件 `git diff` 均为 0 行**：`blueprint_review.py` / `blueprint_merge.py` / `blueprint_schema.py` / `builtin_processes.py` / `blueprint_resume.py` / `artifact_service.py` / `agents/call_source.py` / `codegraph/services/repo_router_v2.py` / 六个冻结 legacy technical_plan process 文件（`decompose_segments` / `research_adapter` / `architect_merge_adapter` / `merged_plan` / `clarify_adapter` / `render`）。
- `git diff … -- server/delivery/services/blueprint_anchor.py` → **0 行**（111 算法本体一行未改）；`rg "quick_ratio"` 零命中。
- `ConvergenceSessionEvent` 既有事件类型零修改（`event_taxonomy.py` 不在改动清单内）。

### 契约与纪律断言（实跑）

- `apply_block_ops OK` —— 垃圾入参（`None` / `{}` / `'x'` / `123`）恒返回 `(dict, list)` 不抛；未知 op 产 `reason == "unknown_op"`。
- `B3 entry signatures OK` —— `arestore_human_blocks` / `acollect_human_block_ids` 均为协程函数；前者首参 `artifact` 为位置参数、**其余全 keyword-only**。
- **INV-6 零 ORM 写**：`rg "BlueprintThread.objects.(create|acreate|update|bulk_update)|ArtifactVersion.objects.(create|acreate|update)"` 在两个新模块**零命中**；线程行写入唯一通道是 `_reanchor_threads_sync` 内的 `bulk_update`（在 lifecycle service 内）。测试 `test_modules_have_no_orm_writes_and_no_record_answer` 用源码扫描同款断言。
- ⛔ **`record_answer` 未被用作留痕通道**：AST 剥离 docstring 后两个新模块**零命中**（唯一的文本命中是模块 docstring 里「⛔ 绝不用 `record_answer`」这句禁令本身）。finding / gate 类留痕一律 `open_thread` + `append_note`。
- **观测合规扫描**：AST 遍历三个文件的全部 `logger.*` 调用，本 plan 新增的 12 条事件**全部**带 `category` + `component`（见下方 Deferred Issues 说明唯一的历史遗留项）。

## Deferred Issues

**`blueprint_lifecycle_service.py:358` 的 `blueprint_transition_event_persist_failed` 缺 `category` / `component`** —— AST 扫描发现的唯一观测缺口。经 `git log -L 352,362` 定位，该行由 **111-02（commit `251697a7`）** 引入，**早于本 plan**，且落在本 plan 的追加点（第 1239 行）之前。本 plan 对该文件的改动配额是「**只允许文件尾纯追加、删除行 = 0**」（PLAN prohibitions 第 8 条，114-01 已用掉前 1065 行的唯一改动配额），修它会产生删除行、直接违反硬约束并使受限面自检失败。

**处置**：登记待办，留给下一个正当修改该文件的 plan（114-05 会碰 lifecycle 相关面）顺带补齐。影响有界 —— 该事件是 best-effort 的事件持久化失败 warning，不进指标聚合口径，缺 `category` 只影响日志分类检索。

## Self-Check: PASSED

- **文件存在**：5 个声明文件全部在磁盘上（`blueprint_block_edit.py` 359 行 / `blueprint_reflow.py` 1008 行 / 两个测试 545 + 784 行 / `blueprint_lifecycle_service.py` 含追加段）✓
- **commit 存在**：`b9ca4e93` / `82384067` / `9500af9b` 均在 `git log`（`milestone/v0.20.0-blueprint`）✓
- **artifacts `contains` 断言**：`async def areanchor_threads` ∈ lifecycle（`:1246`）✓；`def apply_block_ops` ∈ block_edit（`:127`）✓；`ablock_section_writer` ∈ reflow（`:372`）✓；`orphaned` ∈ 重锚测试（9 处）✓；`arestore_human_blocks` ∈ reflow 测试（4 处）✓
- **key_links 断言**：`reanchor` ∈ lifecycle 追加段（lazy import）✓；`add_version` ∈ block_edit ✓；`diff_blueprint_blocks` ∈ reflow（7 处）✓
- **must_haves truths 逐条**：四键恒定返回 ✓ / diff 预筛且与全量等价 ✓ / `section_path` 刷新 ✓ / 失锚不删可集中查询 ✓ / 一次 `bulk_update` 带显式 `updated_at` ✓ / `apply_block_ops` 三 op 且入参不被改、恒不抛 ✓ / 不合法拒绝且不落版本 ✓ / `human_edit:` 归属 + reviewer upsert ✓ / 同 hash 不翻版本（两处）✓ / 回灌三步顺序固定 ✓ / `decision_log` 6 键保 `answer` ✓ / 同一问题不重复问（复用 `_collect_prior_answers` 且有失败对照）✓ / 线程收尾记 `applied_in_version` 基线 id ✓ / AI 不覆盖人工（回灌侧 + 重装侧）✓ / `ablock_section_writer` 为默认 writer 且降级不丢答案 ✓ / `human_block_restore:` 第三前缀 ✓
- **受限面**：删除行 = 0（`rg "^-[^-]"` 空输出）✓
- **门禁**：1228 passed / 0 failed ✓；`makemigrations --check` 退出码 0 ✓；ruff check + format 通过 ✓

## Next Phase Readiness

- **114-03 可直接接线四个契约**，全部为 best-effort async、**无 migration、无新 stage、无新 `CallSource` 枚举值、无新事件常量**：`arestore_human_blocks(artifact, …)` → `aapply_thread_answers(artifact, …)` → 判定内核 → 需要时 `areanchor_threads(artifact, new_content, old_content=…)`。**入口顺序与「见 `conflict` 即停等」的纪律见上方接线契约节。**
- **114-05 可直接消费**：`aapply_block_edit(artifact, ops, user=…)`（`edit-blocks` 端点）、`aapply_thread_answers`（`threads answer` 端点在 `record_answer` 之后同请求内接）、`areanchor_threads`（任何产版本路径）。
- **`produced_by_ref` 三前缀约定**（115 的版本溯源与 114-05 的 `human_edit_volume` 统计都依赖）：`human_edit:{user_id}` / `ai_review_reflow:{thread_id}` / `human_block_restore:{base_version_no}`。
- **给后续 writer 的纪律**：① 任何产新版本的路径**必须**跟一次 `areanchor_threads`，否则旧批注会错位；② 基线**一律** `order_by("-version_no").afirst()`，**绝不**读 `session.current_artifact_version`；③ 写进 content 的任何时间戳都必须来自**可重放的既有数据**（消息 `created_at` 等），用 `timezone.now()` 会破坏「同 hash 不翻版本」；④ AI 侧留痕一律 `open_thread` + `append_note`，`record_answer` 只属于**人类回答澄清线程**的路径（114-05）；⑤ 线程行写入只有 `areanchor_threads` 一条新通道，adapter / view / 纯函数层**只读**。
