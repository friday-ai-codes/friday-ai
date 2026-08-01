# Phase 111: 蓝图底座 - Pattern Map

**Mapped:** 2026-07-29
**Files analyzed:** 9 类新建文件（约 12+ 个具体文件）
**Analogs found:** 9 / 9（全部命中强 analog）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `server/services/process_runtime/blueprint_schema.py` | schema/validator | transform | `server/workflows/schemas/technical_plan.py` + `merged_plan.py` | exact |
| `server/services/process_runtime/blueprint_execution.py` | 纯函数派生器 | transform | `server/services/process_runtime/wave_layering.py` | exact |
| `server/services/process_runtime/blueprint_quality.py` | 纯函数指标 | batch/metrics | `wave_layering.py`（形态）+ `measure_extractor_precision.py`（指标口径） | role-match |
| `server/delivery/models/blueprint_thread.py`（Thread + Message + Reviewer） | model | CRUD | `server/delivery/models/research_task.py` | exact |
| `delivery.Artifact.blueprint_status` 新字段 | model field | CRUD | `server/delivery/models/artifact.py`（宿主本体） | exact |
| `server/delivery/services/blueprint_lifecycle_service.py` | service 单点收口 | request-response | `server/delivery/services/convergence_session_service.py` | exact |
| `server/delivery/services/blueprint_anchor.py` | 纯函数算法 | transform | `wave_layering.py`（纯函数范式） | role-match |
| `repositories` `RepoCharter` model + migration | model + migration | CRUD | `server/repositories/models.py` 的 `GitCredential`/`SensitiveFileSuggestion` + `migrations/0037_graphfileindex.py` | exact |
| charter REST 端点（views/serializers/urls） | view 三件套 | request-response | `server/repositories/route_views.py` + `urls.py` + `serializers.py` | exact |
| `repositories/services/charter_service.py` | LLM 单调用 service | request-response | `server/services/process_runtime/decompose_segments.py` | exact |
| `evaluate_blueprint_golden` command | management command | batch | `server/codegraph/management/commands/measure_extractor_precision.py` | exact |
| `server/tests/delivery/test_blueprint_*.py` | test | — | `test_sdd_spec_transitions.py` + `test_sdd_spec_inv6_guard.py` + `conftest.py` | exact |

---

## Pattern Assignments

### 1. jsonschema 校验模块 → `blueprint_schema.py`

**Analog:** `server/workflows/schemas/technical_plan.py`（279 行）+ `server/services/process_runtime/merged_plan.py`（59 行，process_runtime 侧包装范式）

**结构要点：**
- 模块级 schema 常量：`TECHNICAL_PLAN_JSON_SCHEMA: dict[str, Any] = {...}`，draft 2020-12（`"$schema": "https://json-schema.org/draft/2020-12/schema"`），每个 property 带 `description`（同时服务 LLM prompting 与校验）
- 校验函数统一签名 `def validate_xxx(data) -> tuple[bool, str | None]`：`jsonschema.validate(...)` 包 try/except，`ValidationError` 时返回 `(False, str(e.message))`，绝不外抛（见 `technical_plan.py:207-222`）
- `merged_plan.py` 是「process_runtime 侧 schema 模块」的直接样板：模块 docstring 写清形状清单与职责边界、`from __future__ import annotations`、显式 `__all__`、顶层非 dict 防御性返回 `(False, "...")`（`merged_plan.py:54-55`）、复用下游校验器不重复造轮子（`merged_plan.py:26` 直接 import `validate_technical_plan`）
- jsonschema 默认 `additionalProperties` 允许——额外字段不会被拒，这是 v0 pass-through 兼容的既有依据（`merged_plan.py:17`）

**沿用：** dict 常量 + `validate_*` tuple 返回约定；`merged_plan.py` 的 docstring 契约化写法（字段清单 + 必填性 + 边界声明）；引用完整性等 jsonschema 表达不了的检查放校验函数内做手写检查（返回同一 tuple 形状）。
**避免：** 不要模仿 `dict_to_technical_plan`——其 `technical_plan.py:272` 有 `spaces=data.get("projects", ...)` 字段错位残留（dataclass 字段名是 `projects`），新模块无需 dataclass 转换层，schema dict + 校验函数即可；不引入 pydantic（CONTEXT 明确）；**绝不修改 `merged_plan.py`**（§13.2 冻结）。

---

### 2. process_runtime 纯函数模块 → `blueprint_execution.py` / `blueprint_anchor.py`

**Analog:** `server/services/process_runtime/wave_layering.py`（114 行）

**结构要点：**
- 模块头三件套：中文 docstring（写明「**纯函数**（无 IO / 无 ORM / 无 LLM）」+ phase/需求 ID + 零回归命门）、`from __future__ import annotations`、显式 `__all__`（`wave_layering.py:1-21`）
- 半可信输入逐字段 `.get` 防御：`t.get("dependencies") or []`、`t.get("repository_id", "")`、缺 `id` 跳过、无效引用过滤、fail-safe 绝不抛（`wave_layering.py:49-59`）
- 复用权威校验不重写：环检测直接调 `plan_validator.validate_plan` 前置 fail-fast（`wave_layering.py:40-46`），函数内 lazy import 避免模块级依赖
- 拓扑用标准库 `graphlib.TopologicalSorter` Kahn 分层，`CycleError` 再兜底 catch（`wave_layering.py:61-75`）；失败返回结构化 `(结果, {"reason": ..., "detail": [...]})` 而非抛异常
- 返回值稳定有序（`sorted(deps)`，`wave_layering.py:114`），保证确定性输出

**沿用：** `blueprint_execution.py` 的 repo 聚合 + `depends_on`/wave 拓扑可直接搬 `build_repo_waves`/`build_repo_dep_edges` 的算法骨架；派生输出末尾必须过 `validate_technical_plan`（对齐 `merged_plan.py` 复用范式）。`blueprint_anchor.py` 沿用同一纯函数模块形态（difflib 相似度匹配为新算法，阈值 0.85 做模块常量）。
**避免：** 纯函数模块内禁止 import ORM/models、禁止 structlog INFO 刷屏（高频循环）；不要把校验逻辑复制进派生器（复用 `validate_plan`/`validate_technical_plan`）。

---

### 3. delivery 新模型（TextChoices/JSONField/UUID PK）→ `BlueprintThread` / `BlueprintThreadMessage` / `BlueprintReviewer`

**Analog:** `server/delivery/models/research_task.py`（118 行，最规范的近期双模型文件）；辅证 `artifact.py`（`blueprint_status` 宿主）、`convergence_session_event.py`（事件表复用对象）

**结构要点：**
- 文件级模块 docstring 写设计契约：模型职责、状态机枚举来源（DESIGN §）、INV-6 声明「状态变更/落库只经 XxxService，本模型层不写任何 create/save/业务方法」（`research_task.py:14-17`）
- 枚举模块级 `class XxxStatus(models.TextChoices)`：英文 snake_case 存库值 + 中文 label（`research_task.py:25-32`）；status 字段 `models.CharField(max_length=16, choices=..., default=...)`
- 骨架固定：`id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`；跨 app FK 用字符串前向引用防 import 环（`"delivery.ConvergenceSession"`、`"repositories.Repository"`），不污染反查用 `related_name="+"`（`research_task.py:41-52`）
- 结构化负载用 `models.JSONField(default=dict, blank=True)`（`error`/`content`），行内注释写明形状归属哪个 schema、校验归 service（`research_task.py:98-101`）
- `class Meta`：显式 `db_table = "delivery_xxx"` + 中文 `verbose_name` + 查询驱动的 `indexes`（`research_task.py:76-83`）；`__str__` 返回 `Xxx(id, status)`；类型注解 `objects: "models.Manager[Xxx]"`（见 `artifact.py:48`）

**沿用：** `Artifact.blueprint_status` 加字段直接模仿 `artifact.py:65-69` 的 status 字段写法（`max_length` 按 11 态最长值 `needs_clarification`=19 放宽到 32）；`BlueprintReviewer` 的 `unique_together`/`UniqueConstraint` 模仿 `ArtifactVersion.Meta`（`artifact.py:138`）；anchor 可空 JSONField（`null=True, blank=True` = 全局线程）模仿 `models.py` 的 `ai_summary_tree` 口径。事件复用只往 `event_taxonomy` 加 `blueprint_*` 常量，`ConvergenceSessionEvent` 模型零改动。
**避免：** 模型层写任何业务方法/校验（INV-6）；给 `Repository` 等基础模型加反查 `related_name`（用 `"+"`）；改 `ConvergenceSessionEvent` 既有字段/类型（§13.2）。

---

### 4. delivery service 单点收口 → `blueprint_lifecycle_service.py`

**Analog:** `server/delivery/services/convergence_session_service.py`（335 行，INV-6 权威样板）

**结构要点：**
- 模块结构：docstring 声明「XXX 状态变更唯一写入入口（INV-6）」+ 转移规则表；`logger = structlog.get_logger(__name__)`；`__all__` 导出 service 类与专用异常（`convergence_session_service.py:37-42`）
- 非法转移 fail-loud：查转移表拿不到 target 即 `raise ValueError(f"非法状态转移：... 合法 event={...}")`（`:157-162`）；并发冲突有专用异常类 `ConcurrentTransitionError(RuntimeError)`（`:45-51`）
- CAS 防 TOCTOU：写库用 `Model.objects.filter(id=..., current_stage=from_stage).update(**values)`，`updated != 1` 即拒绝并抛异常，成功后同步内存对象字段（`:219-237`）——blueprint 11 态守卫应逐字复刻此条件更新范式
- async 外壳 + `@sync_to_async` 私有 `_xxx_sync` 内核的分层（`:97-124`）；终态幂等 no-op、并发被拒后 `_refresh_status_sync` 重读同步内存态（`:239-273`）
- 事件 best-effort：`_emit_event` 先打 structlog（`category="sampling", component=...`）、`_persist_event` 包 try/except，「事件持久化失败绝不阻断转移」（`:304-335`）

**沿用：** 整体骨架照搬——blueprint 版本把「stage graph 查表」换成 11 态转移字典常量；`needs_clarification` 的 `return_status` 与 `pending_review → confirmed` 的 open+blocking 线程检查放在 transition 前置守卫；状态转移日志按 CONTEXT 记 `category="caller"` + `initiated_by_user_id`（比 analog 的 sampling 级别更高，因是用户可归因动作）；确认类动作 upsert `BlueprintReviewer` 与转移同事务。
**避免：** 先 `get` 再 `save` 的读改写（必须条件 `update` CAS）；事件失败向上抛；在 service 之外任何地方写 `blueprint_status`（配 INV-6 守护测试，见第 9 类）。

---

### 5. repositories app 模型 + migration → `RepoCharter`

**Analog:** `server/repositories/models.py` 的 `GitCredential`（`:654-682`，`OneToOneField(Repository)` 直接样板）与 `SensitiveFileSuggestion`（`:1005-1087`，最近期、含嵌套 TextChoices/约束/索引全套）；migration analog `migrations/0037_graphfileindex.py`

**结构要点：**
- repositories 是单文件 `models.py`（非分包），新模型追加到文件尾部（对齐 `SensitiveFileSuggestion` 的位置惯例）
- `OneToOneField` 一仓一份：`repository = models.OneToOneField(Repository, on_delete=models.CASCADE, related_name="credential")`（`:658-662`）→ RepoCharter 用 `related_name="charter"`
- 闭集枚举可作**类内嵌套** TextChoices（`SensitiveFileSuggestion.Severity/Detector/Status`，`:1016-1035`）——repositories 两种风格并存，嵌套式更近期；`source` 字段（ai_draft/human_confirmed）适用
- `Meta` 用 `constraints=[models.UniqueConstraint(..., name="uq_...")]` + `indexes=[models.Index(..., name="idx_...")]` 显式命名（`:1069-1084`）；`db_table` 用 `repo_` 前缀复数（如 `repo_charters`）
- migration 为标准 `makemigrations` 产物：`CreateModel` 单操作 + `dependencies` 指向最新一条（当前 `0039_repository_git_instance_credential`），加字段与建表可拆两条 migration（`0037` 是纯 CreateModel 样板）

**沿用：** `confirmed_by` 用 `models.ForeignKey(settings.AUTH_USER_MODEL 或 "accounts.User", null=True, on_delete=models.SET_NULL, related_name="+")`；结构化 JSONField（positioning/owned_domains/...）逐字段注释形状出处（DESIGN §5.7），校验归 service；敏感注释纪律学 `GitInstanceCredential`（`:686-695`，「绝不存明文、绝不进日志」类契约写进 docstring/help_text）。
**避免：** 手写 migration（跑 `makemigrations` 生成）；在模型上写 confirm/draft 业务方法（归 `charter_service`）；delivery 侧的 `models/` 分包风格搬过来（repositories 惯例是单文件）。

---

### 6. REST 端点（adrf 异步 DRF）→ charter 读取 / 草案生成 / confirm

**Analog:** `server/repositories/route_views.py`（59 行，完整三件套微样板）+ `urls.py:147-186` 接线 + `serializers.py:272-297`（`SensitiveFileSuggestionSerializer`）

**结构要点：**
- repositories 惯例是**按功能拆小 view 文件**（`route_views.py`/`sync_status_views.py`/`refresh_remote_head_views.py`...），新建 `charter_views.py` 平级文件，而非塞进 1987 行的 `views.py`
- 视图骨架：`from adrf.views import APIView` + `permission_classes = [IsAuthenticated]` + `async def post(self, request) -> Response`（`route_views.py:25-30`）；重依赖在方法内 lazy import（`:37`）
- 请求校验用视图文件内联 `serializers.Serializer`：字段带防御上限（`max_length=1000`、`min_value/max_value` 防 DoS），`serializer.is_valid(raise_exception=True)`（`route_views.py:14-32`）
- 模型回显用 `ModelSerializer` 放 `serializers.py`：只读资源全字段 `read_only_fields = fields`，状态只经专用 action 变更不许裸 PATCH（`serializers.py:272-297` 的注释即此契约）
- urls 接线：`urls.py` 顶部 `from .charter_views import ...`，urlpatterns 里 `path("<uuid:repository_id>/charter/", CharterView.as_view(), name="repository-charter")`（对齐 `:149-186` 的 `<uuid:repository_id>/xxx/` 资源子路径 + kebab-case name 风格）

**沿用：** 三个端点一个文件：GET 读取（404 语义给无章程仓）、POST `charter/draft/`（触发 AI 草案）、POST `charter/confirm/`；写操作全部委托 `charter_service`，视图不碰 ORM 写。
**避免：** 同步 `rest_framework.views.APIView`（必须 adrf async）；在视图里直接 `RepoCharter.objects.create/update`（收口 service）；往 `views.py` 巨石文件里加代码。

---

### 7. management command → `evaluate_blueprint_golden`

**Analog:** `server/codegraph/management/commands/measure_extractor_precision.py`（359 行，评估/指标型 command 权威样板）

**结构要点：**
- 结构：模块 docstring（写清硬门槛阈值 + CLI 用例）→ 模块级事件名常量 → `@dataclass(frozen=True)` 的 ground-truth 条目 → `class Command(BaseCommand)` 带中文 `help`（`:39-65`）
- `add_arguments` 全部带 default 与 `help`；fixture 路径默认值用 `Path(__file__)` 相对定位（`:95-101`）——blueprint 版指向 `server/tests/fixtures/blueprint_golden/`
- 前置条件缺失走 advisory 跳过（log + `self.stdout.write` + return，exit 0，CI 友好）vs 硬错误 `self.stderr.write` + `raise SystemExit(2)` 分层（`:116-134`）
- 指标产出：`_measure()` 返回结构化 dict（各命中数/总数/耗时/`per_xxx` 分桶），`handle` 里算通过位、写 `--output-json`、structlog 记 `xxx_measured` 事件、`self.stdout.write(json.dumps(report, ...))`；未过门槛 `raise SystemExit(1)`（`:143-180`）
- fixture 加载独立函数容错（跳过非法行，`:295-315`）；断言机制级匹配放 `_match_*` 纯函数（`:328-359`）

**沿用：** golden case JSON 逐个加载 → 调 `blueprint_quality.py` 纯函数算引用覆盖率/目标仓命中率 → 汇总 report + 阈值判定 + exit code。指标计算逻辑放 `blueprint_quality.py`（可测纯函数），command 只做 IO 与编排。
**避免：** 在 command 里内联指标算法（不可单测）；失败静默 exit 0（未过门槛必须非零退出）；与 v0.19.0 路由 golden set 共用 fixture 目录/文件。

---

### 8. LLM 单调用 service → `charter_service.py`（章程蒸馏）

**Analog:** `server/services/process_runtime/decompose_segments.py`（212 行，只读参考，标准 LLM 单调用五步骨架）

**结构要点：**
- 调用骨架五步（`:150-183`）：try 内 lazy import → `resolved = await ProviderConfigService.aresolve()` → `model_name = (resolved.extra or {}).get("default_model", "")`（无 model 降级返回 None）→ `model = build_chat_model(resolved, model_name, streaming=False)` → `with use_call_source(CallSource.XXX): response = await model.ainvoke(messages)`
- JSON 输出三层防御：`_content_to_text`（兼容 reasoning 模型 content_blocks 列表，`:35-52`）→ `_parse_segments_json`（` ```json` 代码块 + 裸 JSON 双路提取，非法返回 `[]` 不抛，`:55-71`）→ `normalize_*`（逐字段强转/白名单/截断，独立可测纯函数，`:74-105`）
- prompt 拆两个私有函数：`_system_prompt()` 写死输出 JSON 形状约定，`_build_prompt()` 拼 `## 段落` 结构化上下文（`:108-131`）
- 全程 best-effort：外层 `except Exception` 捕获，`redact_secrets_in_text(str(exc))` 脱敏后 warning，返回 `None` 绝不阻断（`:204-212`）
- 观测三事件：`xxx_started/completed/failed` 带 `category="sampling"`、`component`、`duration_ms=round((time.monotonic() - started) * 1000, 2)`（`:157-201`）

**沿用：** 新 `CallSource` 枚举值（本相位加 7 值）经 `use_call_source` 标注；charter 蒸馏输入拼装（ai_summary/facets + MR 历史 + RepoAssociation）走 `_build_prompt` 的分节风格；`normalize_charter_draft` 独立纯函数校验 §5.7 形状。区别于 analog：charter_service 还负责**落库**（source=ai_draft 草案、confirm 置 human_confirmed、人工确认后只新增修订草案版本绝不覆盖）——写路径收口本 service，LLM 失败时不落任何行。
**避免：** 修改 `decompose_segments.py`（只读参考）；LLM 异常裸文本进日志（必须 `redact_secrets_in_text`）；`component` 乱写（repositories 侧可用 `charter_service`，call_source 按 LOGGING-SPEC §4.1 登记）。

---

### 9. pytest 测试文件 → `server/tests/delivery/test_blueprint_*.py`

**Analog:** `server/tests/delivery/test_sdd_spec_transitions.py`（145 行，状态机 service 测试样板）+ `test_sdd_spec_inv6_guard.py`（127 行，INV-6 旁路写守护样板）+ `conftest.py`（共享 seam）

**结构要点：**
- 状态机测试：模块 docstring 列覆盖矩阵；`pytestmark = pytest.mark.django_db(transaction=True)`（async + `sync_to_async` 跨线程写库必须 transaction）；裸 async test 函数（无 class）（`test_sdd_spec_transitions.py:25-56`）
- 工厂用私有 helper 而非 fixture：`async def _make_spec(status=...)` 内 `await Model.objects.acreate(...)`，uuid 后缀防唯一冲突（`:28-42`）；断言经 `aget` 重读 DB（`_status` helper，`:45-47`）
- 用例分区注释组织：`# ---- 合法流转逐条 ----` / `# ---- 非法流转 fail-loud ----` / `# ---- 幂等 / 防双推进 ----` / `# ---- 原子性 ----`；非法转移断言 `pytest.raises(XxxTransitionError)` 后再断言状态未变（`:101-113`）
- INV-6 守护测试：纯本地源码扫描（无 DB），`SERVER_DIR = Path(__file__).resolve().parents[2]`，三正则（`.objects.<write>` / 直接实例化带负向前瞻排除更长符号 / 链式 `.save(`），排除 tests/migrations/models/writer 自身，命中列 `文件:行`；配套「writer 确实在写」的防形同虚设反向断言（`test_sdd_spec_inv6_guard.py:39-127`）
- 纯函数测试（schema/execution/anchor/quality）无需 django_db 标记——参照 `test_sdd_spec_transitions` 文件组织但去掉 DB 依赖；conftest 里的 seam 只在需要 Qdrant/embedding 时引用（blueprint 测试基本用不到）

**沿用：** 按对象拆文件：`test_blueprint_schema.py`（纯函数）、`test_blueprint_execution.py`（派生 + `validate_technical_plan` 通过性）、`test_blueprint_lifecycle.py`（11 态矩阵 + CAS 幂等）、`test_blueprint_thread_models.py`、`test_blueprint_inv6_guard.py`（守卫 `blueprint_status` 与新模型旁路写）、`test_blueprint_anchor.py`；command 测试走 `call_command`（既有惯例）。
**避免：** class 风格 TestCase（本目录全是模块级函数）；忘记 `transaction=True`（async service 测试会挂）；INV-6 正则不带负向前瞻（会误伤 `BlueprintThreadStatus(` 等长符号）。

---

## Shared Patterns（跨文件通用）

### structlog 观测事件（所有新 service/command/LLM 调用）
**Source:** `decompose_segments.py:157-211` + `convergence_session_service.py:308-315`

```python
logger = structlog.get_logger(__name__)
logger.info("blueprint_stage_completed", category="sampling", component="process_runtime",
            duration_ms=round((time.monotonic() - started) * 1000, 2), ...)
```
生命周期 started/completed/failed 三件套；用户可归因动作（lifecycle 转移）用 `category="caller"` + `initiated_by_user_id`；高频内部步骤用 `sampling`；异常文本过 `redact_secrets_in_text`。

### INV-6 单一写入 + 守护测试
**Source:** `convergence_session_service.py`（CAS 条件更新）+ `test_sdd_spec_inv6_guard.py`（grep 守护）
新模型 docstring 声明唯一 writer → service 用 `filter(...).update(...)` CAS → 守护测试锁死旁路写。三者成套交付，缺一即为不完整。

### 模型骨架
**Source:** `research_task.py` / `artifact.py`
UUID PK（`default=uuid.uuid4, editable=False`）+ TextChoices（英文值/中文 label）+ `JSONField(default=dict, blank=True)` + 显式 `db_table`/`verbose_name`/`indexes` + 跨 app 字符串 FK + `related_name="+"` 防反查污染。

### best-effort 观测不反噬业务
**Source:** `convergence_session_service.py:316-324`
事件落库/指标上报一律 try/except 吞掉 + warning，绝不打断主流程。

## No Analog Found

| 内容 | 说明 |
|---|---|
| `blueprint_anchor.py` 的 difflib 模糊匹配算法本体 | 代码库无 difflib 先例，算法自写（标准库 `difflib.SequenceMatcher.ratio()`，阈值 0.85 常量化）；模块**形态**仍沿用 `wave_layering.py` 纯函数范式 |
| golden set fixture 目录组织 | 近似参考：`server/tests/fixtures/hybrid_graph_capable_golden/`（含 README 说明构造口径）；blueprint 独立建 `server/tests/fixtures/blueprint_golden/`，不与既有 golden 共文件 |

## Metadata

**Analog search scope:** `server/workflows/schemas/`、`server/services/process_runtime/`、`server/delivery/{models,services}/`、`server/repositories/`、`server/**/management/commands/`、`server/tests/delivery/`
**Files scanned:** 约 240 个候选路径，精读 16 个 analog 文件/切片
**Pattern extraction date:** 2026-07-29
