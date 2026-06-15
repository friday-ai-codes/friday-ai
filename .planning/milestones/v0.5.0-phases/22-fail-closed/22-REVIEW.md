---
phase: 22-fail-closed
reviewed: 2026-06-14T10:19:08Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - server/services/exclusion.py
  - server/services/indexer.py
  - server/services/code_parser.py
  - server/services/retrieval/rag_search.py
  - server/services/retrieval/hybrid_search.py
  - server/repositories/index_views.py
  - server/repositories/views.py
  - server/repositories/serializers.py
  - server/mcp_tools/views.py
  - server/agents/tools/chat_tools.py
  - server/agents/tools/space_tools.py
  - server/chat/coding_session_service.py
  - server/workflows/nodes/ai/coding.py
  - task/core/exclusion.py
  - task/git_ops/operations.py
  - task/core/config.py
  - web/src/api/exclusions.ts
findings:
  blocker: 1
  high: 1
  medium: 3
  low: 3
  total: 8
status: clean
resolution:
  resolved: [BL-01, HI-01, ME-01, ME-02, ME-03]
  deferred: [LO-01, LO-02, LO-03]
  note: "BLOCKER/HIGH/MEDIUM 全部修复并补测；LOW 三项按计划暂缓（见末尾 Resolution）。"
  resolved_at: 2026-06-14T00:00:00Z
---

# Phase 22: Code Review Report — 排除配置与统一过滤（fail-closed）

**Reviewed:** 2026-06-14T10:19:08Z
**Depth:** deep（跨文件追踪 chokepoint 调用链 + 匹配语义验证）
**Files Reviewed:** 13 源文件（不含测试 / .planning）
**Status:** issues_found

## Summary

整体 fail-closed 接线**结构正确且一致**：单一匹配器 `services/exclusion.py` 被所有读取面统一调用（RAG chokepoint `rag_search`、图谱邻居 `hybrid_search`、frontend REST `CodeSearchView`、MCP `grep/get_file/list/find_related`、in-process agent 工具、容器 clone 后 prune）。每个挂接点对「匹配器构造失败」和「单项判定异常」都明确 fail-closed（丢弃 / 拒读 / 返回 404），未发现把被排除内容降级返回明文的旁路。路径归一 (`normalize_rel_path`) 正确处理绝对路径、`..` 越界、反斜杠，构造期非法 regex fail-loud、运行期异常 fail-closed 的双失败模式实现到位。审计埋点 `exclusion.blocked` 覆盖各面。

但存在一个**会直接导致明文泄漏的 BLOCKER**：内置全局默认里**无前导通配的 glob 规则只匹配仓库根**，导致最常见的密钥布局（`server/.env`、`web/.env`、子目录 SSH 私钥）根本不被排除——而本项目自身的 `.env` 恰恰位于 `server/.env`（见 CLAUDE.md）。这使「`.env`/私钥对 Friday 不可见」这一头号安全承诺在默认配置下失效。另有一个 ReDoS 可用性风险，以及若干 fail-open 缺口（大小写、分支 overlay 索引未过滤）。

下面按严重度排列。BLOCKER/HIGH 需在发布前处理。

---

## BLOCKER

### BL-01: 内置默认 glob 规则只匹配仓库根，子目录密钥（`server/.env` 等）明文泄漏

**File:** `server/services/exclusion.py:53-74`（`BUILTIN_GLOBAL_DEFAULTS`），匹配语义 `:134` / `:154-156`

**Issue:**
glob 规则编译为 `re.compile(fnmatch.translate(pattern))` 并以 `rx.match(norm)` 对**整条相对路径**匹配（`norm` 形如 `server/.env`）。`fnmatch.translate` 末尾带 `\Z`，故 `.match` 等价 full-string。对**不含前导 `*` 的模式**，这意味着只匹配仓库根级文件：

实测（`fnmatch.translate` + `re.match`）：

```
.env        -> 命中 ".env"           ；server/.env=False  web/.env=False
.env.*      -> 命中 ".env.local"     ；config/.env.production=False
id_rsa      -> 命中 "id_rsa"         ；deploy/id_rsa=False
*.pem       -> a/b/key.pem=True      （带前导 * 才能匹配子目录）
*credentials* -> x/credentials.json=True
```

因此内置默认中 `.env`、`.env.*`、`id_rsa`、`id_dsa`、`id_ed25519` **只在仓库根生效**。任何位于子目录的 `.env` / 私钥都不会被排除：
- 经索引扫描进入 Qdrant → 经 RAG / `CodeSearchView` / MCP `get_file`/`grep` 返回**明文**；
- 经容器 prune 时也不被删除 → 容器内 agent 直接读到密钥文件。

这是直接命中本阶段 INV-4 / DOMAIN §9.1 的安全承诺失败：项目自身布局（CLAUDE.md：`.env` 解析顺序 `server/.env` 优先、前端 `web/.env`）下，开箱默认对 `.env` 完全失效。同一缺陷在容器侧 `task/core/exclusion.py` 复制（同语义），并随 `serialize_rules_for_repo` 下传。

**Fix:** 让内置默认按「任意目录的 basename」语义匹配。两种改法择一：

1. 修正默认模式为可匹配任意深度（推荐，匹配 gitignore 直觉）：

```python
# server/services/exclusion.py — BUILTIN_GLOBAL_DEFAULTS
ExclusionRuleSpec(pattern="**/.env", rule_type="glob", source="global"),
ExclusionRuleSpec(pattern=".env", rule_type="glob", source="global"),
ExclusionRuleSpec(pattern="**/.env.*", rule_type="glob", source="global"),
ExclusionRuleSpec(pattern="**/id_rsa", rule_type="glob", source="global"),
# ... 其余同理补 **/ 变体
```
注意 `fnmatch` 不对 `/` 特殊处理，`**/.env` 实际等价 `*/.env`，仍漏掉根级 `.env`，故需同时保留根级模式或改用方案 2。

2. （更稳）在 `ExclusionMatcher` 对 glob 增加 basename 兜底匹配：在 `is_excluded` 内对 `norm.rsplit("/", 1)[-1]` 也跑一遍 glob 正则，使「无路径分隔符的 glob」按 basename 语义命中任意目录。容器侧 `_ContainerExclusionMatcher.is_excluded` 同步修改，保持两端一致。

建议附测试：断言 `server/.env`、`web/.env`、`a/b/id_rsa` 在默认配置下 `is_excluded == True`，并覆盖容器 prune。

---

## HIGH

### HI-01: 排除 regex 无回溯保护，灾难性 regex 可永久卡死索引/检索（ReDoS）

**File:** `server/services/exclusion.py:137`（编译）、`:157-158`（运行 `re.fullmatch`）；校验 `server/repositories/serializers.py:179-194`

**Issue:**
regex 规则仅在保存时用 `re.compile` 校验语法（fail-loud），并限制 pattern ≤ 500 字符。但**长度上限不能阻止 ReDoS**——短模式如 `(a+)+$`、`(.*a){15}` 即可触发指数级回溯。匹配在以下热路径**同步**执行且**无超时**：

- 索引扫描：`scan_directory` 对**每个文件路径**调用 `is_excluded_rel`（全量索引可达上万次），运行在 `run_in_background` 的常驻 worker loop 中；
- RAG / 图谱 / MCP / agent 工具：对每条结果 `file_path` 调用。

`ExclusionMatcher.is_excluded` 的 `try/except Exception` **捕获不到**灾难性回溯（它不抛异常，只是挂起）。一条恶意/失误的 `ai_suggested` 或 user regex 即可使该仓库每次重索引都卡死，并占住共享后台 worker，影响其它仓库的索引调度。`serializers.py:185` 注释自称长度上限「防 ReDoS 灾难性回溯」属**错误归因**。

注意：触发需创建规则（认证用户 / AI 建议名单），且 `source` 可为 `ai_suggested`（信任度更低）。影响为持久可用性破坏，非数据泄漏，但易触发且难恢复。

**Fix:**
- 用受限的安全匹配执行：对 regex 匹配加超时/字符预算，或改用 `re2`（`google-re2`，线性时间，无回溯）编译排除 regex；
- 退一步，在保存校验时做 ReDoS 静态启发式（如 `regex` 库的 `(?:...)` 复杂度 / 嵌套量词检测）并拒绝可疑模式；
- 修正 `serializers.py` 注释，勿声称长度上限可防回溯。

---

## MEDIUM

### ME-01: 匹配大小写敏感，导致密钥按大小写变体绕过（case-insensitive FS 上 fail-open）

**File:** `server/services/exclusion.py:82`（注释「不强制 lower」）、`:154-159`；同 `task/core/exclusion.py:115-129`

**Issue:**
匹配大小写敏感（设计决策 D-02）。但对**安全默认**而言这是 fail-open：`*.pem` 不命中 `Secret.PEM`，`id_rsa` 不命中 `ID_RSA`，`.env` 不命中 `.ENV`。在大小写不敏感文件系统（macOS 默认、Windows）上，`Config.PEM` 与 `config.pem` 是同一文件且能被 OS 正常读出，但匹配器不认 → 索引并经读取面泄漏明文。即便在大小写敏感 FS 上，用户随手把密钥命名为 `.ENV` 也会绕过保护。

**Fix:** 对**内置安全默认**（密钥/敏感类）采用大小写不敏感匹配（glob 编译时加 `re.IGNORECASE`，dir 前缀比较时统一 `casefold`），用户自定义 regex 仍可遵循既有大小写语义；或为规则增加 `case_sensitive` 标志、默认敏感类不敏感。

### ME-02: 功能分支 overlay 索引（`run_branch_index`）未挂排除过滤

**File:** `server/services/indexer.py`（`run_branch_index`，约 `:1305-1530`；对比已挂接的 `run_full_index :840-841` / `run_incremental_index :2190-2191`）

**Issue:**
`run_full_index` 与 `run_incremental_index` 都通过 `scan_directory(..., is_excluded_rel=exclusion_matcher.is_excluded)` 在扫描源头剔除被排除文件；但 feature 分支 overlay 索引路径基于 git diff 收集变更文件并直接 `_build_points` 入 overlay collection，**未做任何排除判定**。结果：在功能分支上新增/修改的被排除文件（如 `server/.env`）会被写入 overlay Qdrant collection。

读取面在 chokepoint 已统一过滤，故**不构成直接明文泄漏**（且存量清理本就移交 Phase 23）。但它与本阶段「索引扫描面 fail-closed」目标不一致，扩大了 Qdrant 内的残留敏感数据面，并依赖读取面零遗漏作为唯一防线。

**Fix:** 在 `run_branch_index` 对 diff 得到的待索引文件列表同样应用 `build_matcher_for_repo(...).is_excluded(rel_path)` 过滤（与全量/增量同口径），从源头不写入 overlay。

### ME-03: glob 规则保存时不校验，非法 glob 在 server 构造期直接 500

**File:** `server/repositories/serializers.py:188-194`（仅校验 regex）；`server/services/exclusion.py:134`（glob 无 try/except）

**Issue:**
保存校验只对 `rule_type=regex` 跑 `re.compile`。glob 规则不校验，而 `ExclusionMatcher.__init__:134` 对 glob 直接 `re.compile(fnmatch.translate(pattern))` **无 try/except**。`fnmatch.translate` 对绝大多数输入产出合法正则，但仍可能产生异常输入；一旦某仓库存了会令 `fnmatch.translate`/`re.compile` 失败的 glob，后续**该仓库每次 `build_matcher_for_repo` 都抛异常**。各 chokepoint 对构造异常 fail-closed（整仓库读取面不可见）——安全上保守，但表现为该仓库 RAG/检索全部「静默清空」，难以定位。dir/regex 已有兜底，glob 缺。

**Fix:** 在 `ExclusionMatcher` 对 glob 编译加 `try/except re.error`（与容器侧 `task/core/exclusion.py:101-104` 对齐，记录并跳过该条而非整器失败），并在 serializer 对 glob 也做一次 `fnmatch.translate`+`re.compile` 预校验 fail-loud。

---

## LOW

### LO-01: 容器侧匹配器对非法规则静默跳过（fail-open），与 server 不完全对称

**File:** `task/core/exclusion.py:100-109`

**Issue:**
`_ContainerExclusionMatcher` 对无法编译的 glob/regex 仅 `logger.warning` 并跳过该条。若有非法规则下传到容器，其本应保护的文件不会被 prune → 在容器内对 agent 可见。当前由 server 端 regex 保存校验兜底（但 glob 未校验，见 ME-03），故风险有限。属设计权衡，但与「宁可多排不可漏」基调相悖。

**Fix:** 至少对「下传规则里出现无法编译项」整体视为异常并使该仓库 prune 走更保守路径（或令 setup 失败），而非逐条放行。

### LO-02: 匹配器缓存仅按 TTL 覆盖，过期项不主动淘汰，按 repository_id 无界增长

**File:** `server/services/exclusion.py:34`、`:266-276`

**Issue:**
`_matcher_cache` 仅在再次访问同 repo 时用新值覆盖过期项；从未访问的过期项永久驻留，键随仓库数线性增长。属轻微内存问题（非安全、非正确性）。并发上 dict 读写受 GIL 保护、无损坏；TTL 窗口内规则变更已由 `invalidate_matcher_cache` 在写路径即时失效（POST/DELETE 均调用，无遗漏的 update 路径）。

**Fix:**（可选）惰性清理过期键，或加最大容量 LRU。

### LO-03: 排除规则写接口为 `IsAuthenticated`，安全配置建议提权或按空间授权

**File:** `server/repositories/views.py:1015`、`:1091`

**Issue:**
新增/删除 per-repo 排除规则用 `IsAuthenticated`，与本 app 既有约定一致（`RepositoryViewSet` 等仓库写操作均 `IsAuthenticated`）。但排除规则是**安全敏感配置**：任一认证用户可删除某条保护密钥的 per-repo 规则，再经 RAG/检索读出该密钥（内置默认不可删，删除 override 行只会重新启用默认，安全；风险集中在 user 自定义规则被删）。本文件内已 import 并在别处使用 `IsSuperUser`，存在按更高权限收口的先例。

**Fix:**（依信任模型决定）对排除规则的写操作改用 `IsSuperUser` 或按空间成员/角色授权；若维持「全部认证用户皆受信运维」模型，则至少在文档中明确该信任假设。

---

_Reviewed: 2026-06-14T10:19:08Z_
_Reviewer: gsd-code-reviewer (adversarial)_
_Depth: deep_

---

## Resolution（2026-06-14）

BLOCKER / HIGH / 全部 MEDIUM 已修复，每条原子提交并补充测试；LOW 三项按指示暂缓。

| 编号 | 严重度 | 处理 | 关键改动 |
|------|--------|------|----------|
| BL-01 | BLOCKER | 已修复 | `ExclusionMatcher` / 容器侧对**无路径分隔符的 glob 增加 basename 兜底匹配**，使 `.env`/`id_rsa` 命中任意子目录（`server/.env`、`web/.env`、`config/id_rsa`）。补 server + 容器 prune 测试。 |
| HI-01 | HIGH | 已修复 | 新增 `is_redos_risky()` 嵌套量词静态启发式：matcher 构造期 fail-loud、serializer 保存 400 拒绝、容器侧跳过；修正 serializer「长度上限防 ReDoS」的错误注释（诚实标注为缓解非根除）。 |
| ME-01 | MEDIUM | 已修复 | `source="global"` 安全默认大小写不敏感匹配（glob `re.IGNORECASE`、dir `casefold`）；用户自定义规则保持原大小写语义。`serialize_rules_for_repo` 携带 `source` 使容器侧同步。 |
| ME-02 | MEDIUM | 已修复 | `run_branch_index` 对 diff 文件列表套用 `build_matcher_for_repo(...).is_excluded()`，与全量/增量同口径，从源头不写入 overlay collection。 |
| ME-03 | MEDIUM | 已修复 | serializer 对 glob 也做 `fnmatch.translate`+`re.compile` 预校验 fail-loud；`ExclusionMatcher` glob 编译加 `try/except` 记录并跳过非法条目（不再整器失败导致读取面静默清空）。 |
| LO-01 | LOW | 暂缓 | 容器侧非法规则逐条放行（fail-open）；现 glob 已加保存校验，风险进一步收窄。 |
| LO-02 | LOW | 暂缓 | matcher 缓存按 TTL 覆盖、不主动淘汰，轻微内存问题。 |
| LO-03 | LOW | 暂缓 | 排除规则写接口为 `IsAuthenticated`，依信任模型再定夺是否提权。 |

测试：`server` 91 项排除相关用例 + `task` 12 项 prune 用例全绿；改动文件 `ruff format`/`ruff check` 干净。
