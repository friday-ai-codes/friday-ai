---
phase: 24-sensitive-ai-detect
reviewed: 2026-06-15T01:40:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - server/services/sensitive_detect.py
  - server/services/indexer.py
  - server/repositories/models.py
  - server/repositories/migrations/0034_sensitive_file_suggestion.py
  - server/repositories/views.py
  - server/repositories/serializers.py
  - server/repositories/urls.py
  - web/src/api/sensitiveSuggestions.ts
  - web/src/components/repository/SensitiveSuggestionsPanel.vue
findings:
  blocker: 1
  high: 1
  medium: 3
  low: 4
  total: 9
status: clean
resolution:
  resolved_at: 2026-06-15
  fixed:
    - BL-01  # 检测改由 clone_and_index_repository 在 rmtree(temp_dir) 之前 await 同步触发
    - HI-01  # 增量/git_diff 路径也触发检测，仅扫本次新增+修改文件（_detection_only_paths）
    - ME-01  # 文件名启发式不再受 >1 MiB 限制；内容扫描读有界前缀而非整体跳过
    - ME-02  # _scan_repository 加全局护栏（max files/candidates/time）+ 扩充 _SKIP_DIRS
    - ME-03  # classify_ambiguous_files 接入 detect_sensitive_files 主链路（gated + graceful）
    - LO-02  # LLM 失败日志改记 error_type，不再记 str(exc)
  deferred:
    - LO-01  # _upsert_suggestion TOCTOU（窗口小、无数据损坏）——未改
    - LO-03  # 端点缺 per-repo 授权（与 Phase 22/23 现状一致，非本阶段回归）——路线图跟踪
    - LO-04  # 单行扫描 4096 字节截断（性能/召回权衡）——未改
  commits:
    - f1828699b  # ME-01/ME-02/ME-03/HI-01(detector)/LO-02 检测器加固
    - 84b5eb8cc  # BL-01/HI-01 触发时机：rmtree 前同步触发 + 真实集成守护测试
  notes: >-
    BLOCKER + HIGH + 三个 security-relevant MEDIUM 全部修复并通过测试
    （tests/services/test_sensitive_detect.py、test_sensitive_detect_llm.py、
    tests/repositories/test_sensitive_index_trigger.py 共 21 项绿）。
    旧 guard 测试（stub 路径 + mock 检测函数）已重写为真实交互守护：实际落
    .env/id_rsa 到临时目录 + rmtree-in-finally 时序，并显式复现「目录删除后再扫得 0」
    的竞态失败态。剩余 3 项 LOW 未在本轮处理（见 deferred）。
---

# Phase 24: 敏感文件 AI 识别建议名单（EXCL-03）代码审查

**Reviewed:** 2026-06-15
**Depth:** deep（跨文件调用链追踪）
**Files Reviewed:** 8 源文件（+ 2 前端）
**Status:** issues_found

## Summary

隐私边界（密钥不入 reason/log/DB/LLM）与「绝不静默删除」两条核心不变量在本阶段实现得**很扎实**：`_redact_reason` 是 reason 的唯一构造入口、只接受「类型 + 行号」；内容扫描永不回填命中文本；送 LLM 的仅「文件名 + 最小化布尔特征」并有服务端 `_redact_llm_reason` 兜底脱敏；accept 仅幂等建 `RepoExclusionRule`、永不触发删除；审计日志只含计数/severity。这些方向均未发现泄漏路径。

但是检测器的**触发时机存在一个致命竞态**：检测被 `run_in_background` 派发去遍历 `repo_path`，而该 `repo_path` 正是 `clone_and_index_repository` 在 `finally` 中 `shutil.rmtree` 的临时克隆目录——派发是跨线程立即返回的，rmtree 几乎必然先删掉目录，导致后台检测遍历到空/正被删除的目录 → **静默产出零候选**。这直接命中本阶段第一优先级（漏报真实密钥），且无任何错误暴露。守护测试用 stub 路径 + mock 检测函数，恰好绕开了这条真实交互，给了虚假信心。

此外检测**只在全量索引触发**（增量/webhook 后新增的密钥永不被发现）、**>1 MiB 文件被整体跳过**（含文件名启发式，漏报大型 `.pem`/凭据转储），以及可选 LLM 二分类段 `classify_ambiguous_files` **从未在生产链路被调用**（死代码）。

## BLOCKER

### BL-01: 后台检测与临时克隆目录的 `rmtree` 竞态 → 静默漏报全部密钥

**File:** `server/services/indexer.py:1238-1245`（派发）↔ `server/services/indexer.py:3713-3716`（删除）

**Issue:**
`run_full_index` 在 FINALIZING 末尾派发检测：

```315:343:server/services/sensitive_detect.py
async def detect_sensitive_files(repository_id: str, repo_path: str) -> int:
    ...
    for abs_path, rel_path in _walk_candidate_files(repo_path):
```

```1238:1245:server/services/indexer.py
            try:
                from services.background_runner import run_in_background
                from services.sensitive_detect import detect_sensitive_files

                run_in_background(
                    lambda: detect_sensitive_files(self.repository_id, repo_path),
                    name=f"sensitive-detect:{self.repository_id}",
                )
```

`repo_path` 就是上层 `clone_and_index_repository` 的临时克隆目录 `temp_dir`：

```3713:3716:server/services/indexer.py
    finally:
        # Clean up temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
```

`run_in_background` 通过 `loop.call_soon_threadsafe(...)` 把协程调度到**另一个 worker 线程**的事件循环后**立即返回**（`server/services/background_runner.py:179-185`），不被 await。因此 `run_full_index` 返回后，调用线程继续往下走直到 `finally` 执行 `shutil.rmtree(temp_dir)`——此时后台检测协程通常**还没开始 `os.walk`**。竞态结果：

- rmtree 先完成：`os.walk(repo_path)` 对已删除目录产出空序列 → `candidates=[]` → 零建议入库 → **彻底漏报，且无报错**（`os.walk` 默认 `onerror=None` 静默忽略）。
- rmtree 与 walk 并发：文件遍历中途消失，`os.path.getsize` 抛 `OSError` 被逐文件 `except OSError: continue` 吞掉 → **部分/非确定性漏报**。

这违背本阶段第一优先级「漏报真实密钥是最坏结果」，且整条失败链路**完全静默**（无日志、无 DB 痕迹）。守护测试 `test_sensitive_index_trigger.py` 用固定字符串 `repo_path="/tmp/repo-abc"` + mock `detect_sensitive_files`，从不实际遍历文件系统、也不经过 `clone_and_index_repository` 的 finally，故无法发现此竞态。

**Fix:** 让检测在临时目录被删除之前可靠地读到内容。任选其一：

1. 在 `clone_and_index_repository` 层面持有检测 Future，并在 `finally` 删除 `temp_dir` **之前**等待其完成（检测仍可后台跑，但删除目录必须 join）：

```python
# run_full_index 不再自行派发；改由 clone_and_index_repository 编排
detect_future = run_in_background(
    lambda: detect_sensitive_files(repository_id, temp_dir),
    name=f"sensitive-detect:{repository_id}",
)
...
finally:
    if detect_future is not None:
        try:
            detect_future.result(timeout=DETECT_TIMEOUT)  # 删目录前必须收敛
        except Exception:
            logger.warning("sensitive_detect_wait_failed", repository_id=repository_id)
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
```

2. 或在 `run_full_index` 内**同步内联**遍历阶段（只读、已被 1 MiB/二进制上限约束），仅把 DB upsert 后台化；遍历必须发生在目录仍存在时。
3. 切勿依赖「检测比 rmtree 跑得快」的隐式时序。修复后补一个**真实**集成测试：建临时目录 + 落一个 `.env`/`id_rsa`，跑完整 `clone_and_index_repository`（或最小复刻删除时序），断言建议确实入库。

## HIGH

### HI-01: 检测仅在全量索引触发，增量/webhook 后新增的密钥永不被发现

**File:** `server/services/indexer.py:1234-1245`

**Issue:** 检测派发只存在于 `run_full_index` 的 FINALIZING 段；`run_incremental_index` / `run_git_diff_index` / `run_branch_index` 均不触发（全文件仅此一处 `detect_sensitive_files`）。仓库首轮全量索引后，绝大多数后续索引走增量/webhook 路径——此后任何被 `git commit` 进来的 `.env`/私钥/token 在下一次**手动全量重建之前都不会被检测**。对于「持续运行的仓库」，这是一个长期、静默的漏报窗口，仍属本阶段最关心的 false-negative 类别。

**Fix:** 在增量/diff 路径完成后也 best-effort 触发检测。最划算的做法是只对**本次变更涉及的文件**（`diffs` 中 ADD/UPDATE 的 `file_path`）跑检测，避免每次增量全仓重扫；检测器可加一个 `only_paths: set[str] | None` 形参，`_walk_candidate_files` 据此过滤。仍沿用 best-effort + try/except，且修复 BL-01 后的目录生命周期同样适用。

## MEDIUM

### ME-01: >1 MiB 文件在遍历期被整体丢弃，连文件名启发式都不跑 → 漏报大型密钥文件

**File:** `server/services/sensitive_detect.py:218-219`

**Issue:**

```218:224:server/services/sensitive_detect.py
            if size > _MAX_FILE_BYTES:
                continue
            rel = os.path.relpath(abs_path, repo_path)
```

`_MAX_FILE_BYTES = 1 MiB` 的过滤发生在 `_walk_candidate_files`，即在 `_classify_file` 之前。这意味着超过 1 MiB 的文件**连最便宜、最可靠的文件名启发式（`id_rsa` / `*.pem` / `.env`）都不会执行**。证书链 bundle、含凭据的大型 JSON/SQL 转储、被追加日志撑大的 `.env` 等都可能 > 1 MiB，从而被静默放过。内容扫描有 1 MiB 上限是合理的资源权衡，但**文件名命中不应受文件大小限制**。

**Fix:** 将大小上限的语义从「跳过候选」改为「跳过内容扫描」。对所有文件先跑 `_filename_severity`；仅当文件 ≤ `_MAX_FILE_BYTES` 时再读取并 `_scan_content`。例如让 `_walk_candidate_files` 始终产出候选并附带 `size`，由 `_classify_file` 决定是否读内容。

### ME-02: 自走遍历无全局上限（文件数 / 时间 / 候选数）

**File:** `server/services/sensitive_detect.py:199-225`, `315-343`

**Issue:** `_walk_candidate_files` 仅有逐文件的 1 MiB / 二进制上限，**没有**对「候选总数」「累计扫描文件数」「时间预算」的任何全局约束。在超大 monorepo（百万级文件）上，后台检测会逐个 `open`+`read`（每个最多 1 MiB）并把候选累积进内存列表，随后对每个候选发一条独立的 `aupdate_or_create`（N 次串行 await，见 `detect_sensitive_files:331-332`）。虽然检测是后台、best-effort、不阻断索引，但仍可能长时间占用 IO/CPU/内存与 DB 连接。题述的「runaway resource use on the self-walk」正是此项。

**Fix:** 加全局护栏：最大扫描文件数 / 最大候选数 / 软时间预算（超限即停止并 `logger.warning` 记一次「截断」可观测事件）；候选 upsert 改批量（`abulk_create` + 冲突更新，或分批）。`.git` / `node_modules` 已跳过，但 `dist`/`build`/`vendor`/`.venv` 等大目录建议一并纳入结构性跳过集（注意保留 `secrets/`、`.ssh/` 等目标目录）。

### ME-03: 可选 LLM 二分类段 `classify_ambiguous_files` 从未在生产链路被调用（死代码）

**File:** `server/services/sensitive_detect.py:415-497`

**Issue:** 全仓搜索 `classify_ambiguous_files` 只出现在 `sensitive_detect.py` 定义处与测试/规划文档中；`indexer.py` 的触发仅调用 `detect_sensitive_files`，**从不**构造 `AmbiguousCandidate` 或调用 `classify_ambiguous_files`。Plan 24-02 宣称的「可选 LLM 增强」因此在生产中**零作用**——它被实现、被测试，却从未接入检测管道。这既是检出能力缺口（模糊配置/文档文件本应由 LLM 补判），也是维护负担（一整段含 provider 解析/网络调用的代码无人触达）。

**Fix:** 要么在 `detect_sensitive_files` 完成确定性段后，把「启发式未命中但可疑」的子集组装为 `AmbiguousCandidate` 并 best-effort 调用 `classify_ambiguous_files`（同样 fail-safe，且需满足 BL-01 的目录生命周期约束——LLM 仅用文件名+布尔特征，不读目录，但仍需先在目录存活时采样 `sample_text`）；要么若本里程碑暂不启用 LLM，则将该段标注为未接线/移出主模块，避免「已实现」的错觉。

## LOW

### LO-01: `_upsert_suggestion` 先读后写，可能把用户刚 dismiss 的建议重置回 pending

**File:** `server/services/sensitive_detect.py:284-312`

**Issue:** `_upsert_suggestion` 先 `afirst()` 读现状再算 `status` 再 `aupdate_or_create`，非原子。若后台检测读到某行为 `pending`、与此同时用户调 dismiss、随后检测的 `aupdate_or_create` 落库，会把 `dismissed` 覆写回 `pending`，对用户再次打扰。窗口小、无数据损坏，故 LOW。

**Fix:** 复扰/状态合并逻辑下沉为基于唯一约束的单条 `update_or_create`/条件更新，或对该 path 行加 `select_for_update`（异步等价）以缩小 TOCTOU 窗口。

### LO-02: LLM 失败日志记录 `error=str(exc)`，理论上可能带回响应片段

**File:** `server/services/sensitive_detect.py:465-466`

**Issue:** `except Exception as exc: logger.warning("sensitive_llm_classify_failed", error=str(exc))`。`_parse_llm_verdicts` 抛出的 `json.JSONDecodeError` 文本可能包含被解析文档的位置/片段。送入 LLM 的内容不含密钥、且 prompt 要求模型不回显密钥，故风险很低（且 ME-03 下该段当前未被调用）；但作为纵深防御，异常文本入日志前宜限制为异常类型/长度截断，避免未来 prompt 变更引入回显。

**Fix:** 记录 `error_type=type(exc).__name__` 或对 `str(exc)` 截断/脱敏后再入日志。

### LO-03: 敏感建议端点仅校验 `IsAuthenticated`，无 per-repo/空间归属校验

**File:** `server/repositories/views.py:1137`, `1180`

**Issue:** `RepositorySensitiveSuggestionsView` / `RepositorySensitiveSuggestionActionView` 仅 `IsAuthenticated`，任何登录用户都能列出/accept/dismiss 任意仓库的敏感建议（仅校验仓库存在）。跨仓 `suggestion_id` 经 `(id, repository_id)` 复合过滤 → 404，已正确防越仓引用（T-24-09）。但缺少「该用户是否有权访问此仓库」的授权——这与既有 Phase 22/23 的 exclusions/reconcile 端点一致（项目层面仓库未按用户/空间隔离），故非本阶段引入的回归，记为 LOW/告知。

**Fix:** 若产品需要仓库级访问控制，应在所有仓库子资源端点统一引入空间成员校验；本阶段保持与现状一致即可，但建议在路线图中跟踪。

### LO-04: 单行扫描截断 4096 字节，超长行（minified）尾部的密钥会漏

**File:** `server/services/sensitive_detect.py:178`

**Issue:** `line = raw_line[:_MAX_SCAN_LINE_BYTES]`（4096）用于防极长单行拖垮正则，合理；但落在第 4096 字节之后的密钥会被漏扫。属性能与召回的权衡，影响面小，记 LOW。

**Fix:** 可对超长行做「分窗滑动扫描」（带重叠窗口）而非简单截断，或仅对高熵/赋值类模式放宽窗口；非必须。

---

## 正向确认（核对通过的不变量）

- **密钥不入 reason/DB:** `_redact_reason`（`sensitive_detect.py:124-130`）是 reason 唯一构造入口，只接「类型 + 行号」；`_scan_content` 永不回填 `group(0)`；`SensitiveFileSuggestionSerializer` 全字段 `read_only`，`reason` 仅脱敏文本。✓
- **密钥不入日志:** `sensitive.detected` 仅计数/severity；`sensitive.classify_failed` 仅 `repository_id`。✓
- **密钥不外送 LLM:** `_build_llm_feature` 仅送 `path/ext/has_sensitive_keyword` 布尔；`real_secret` 显式排除出候选（`classify_ambiguous_files:430`）；`_redact_llm_reason` 服务端兜底脱敏。✓
- **绝不静默删除:** 检测器只 upsert 建议；accept 仅 `aget_or_create(RepoExclusionRule, source=ai_suggested)` 并标 `accepted`，无任何删除调用；响应 `cleanup_available` 仅作引导；删除仍由 Phase 23 reconcile/cleanup 用户显式发起。✓
- **检测失败不阻断索引:** 派发段整体 try/except（`indexer.py:1238-1248`），且 `run_in_background` 不被 await；后台 `_wrapper` 吞并记录异常。索引 success 终态不依赖检测结果。✓（注意：此「不阻断」恰是 BL-01 竞态得以静默的原因之一）
- **dismissed 复扰策略:** 仅当从非 real_secret 升级为 real_secret 才重置 pending，否则保留 dismissed/accepted（`_upsert_suggestion:290-301`）。✓
- **accept 幂等:** `aget_or_create` + 唯一约束 `(repository, rule_type, pattern, source)`，重复 accept 不报错。✓
- **migration 0034:** 纯 CreateModel，`unique(repository, path)` upsert 锚点 + `(repository, status)` 索引，与模型一致，不回填历史。✓

---

_Reviewed: 2026-06-15_
_Reviewer: gsd-code-reviewer (Claude)_
_Depth: deep_
