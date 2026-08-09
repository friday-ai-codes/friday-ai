# Phase 127: Semgrep 门禁 + LSP 基准 - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 28
**Analogs found:** 28 / 28

> **Hard locks (planner must obey):** ⛔ 不改 `server/codegraph/services/repo_router_v2.py`；⛔ 不改 `mcp/` submodule。Semgrep = 独立 CLI（subprocess），永不 `import semgrep`。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/Dockerfile` | config | file-I/O | `server/Dockerfile` (runtime stage before `USER friday`) | exact |
| `server/friday/settings.py` | config | request-response | `settings.py` `VOLAR_*` / `GOPLS_*` / `EXTRACTOR_BACKENDS` | exact |
| `server/system/models.py` (`SettingKeys.SEMGREP_*`) | model | CRUD | `SettingKeys.FEISHU_APP_SECRET` + `CONCURRENCY_*` | exact |
| `server/codegraph/models.py` (`SecurityFinding`) | model | CRUD | `SymbolCommunity` / `ProcessTrace`（软引用） | exact |
| `server/codegraph/migrations/*_securityfinding.py` | migration | CRUD | recent codegraph soft-ref migrations (125/126) | role-match |
| `server/services/code_graph/semgrep_scan.py` | service | batch / request-response | `repo_mirror._run_cmd` + `indexer._get_merge_base`（subprocess CLI） | exact |
| `server/services/code_graph/security_scan_report.py` | utility | transform | `services/code_graph/impact_report.py` | exact |
| `server/services/code_graph/semgrep_enqueue.py` | utility | event-driven | `repositories/charter_enqueue.py` / `services/process_enqueue.py` | exact |
| `server/services/repo_mirror.py`（公开 worktree 包装） | service | file-I/O | `_ensure_worktree` / `ensure_mirror_sha` | exact |
| `server/durable/queues.py` (`QUEUE_SCAN`) | config | event-driven | `QUEUE_CHARTER` / `ALL_QUEUES` | exact |
| `server/durable/concurrency.py` (`scan_slot_*`) | utility | event-driven | `charter_slot_lock` / `feature_parse_slot_lock` | exact |
| `server/durable/tasks.py` (`durable_semgrep_scan`) | route | event-driven | `durable_charter_draft` / `durable_community_rebuild` | exact |
| `server/durable/tasks_impl.py` (`run_semgrep_scan`) | service | batch | `run_community_rebuild`（bind_task_context + started/completed/failed） | exact |
| `server/workflows/nodes/ai/coding.py` | controller | request-response | 既有 `append_impact_report` 挂点 | exact |
| `server/workflows/services/mr_service.py` | service | request-response | 既有 `append_impact_report` 挂点 | exact |
| `server/mcp_tools/merge_request_service.py` | service | request-response | 既有 `append_impact_report` 挂点 | exact |
| MR body async patch（回填） | service | request-response | `workflows/services/pr_cross_reference.py` | exact |
| `server/codegraph/lsp/node_check.py` | utility | request-response | 自身（复用，勿重造） | exact |
| `server/codegraph/lsp/go_check.py` | utility | request-response | 自身（复用/微调） | exact |
| `server/codegraph/lsp/orphan_reap.py` | utility | batch | `supervisor.stop` + `psutil`（依赖已有，无现成 orphan 模块） | role-match |
| `server/codegraph/lsp/supervisor.py` | service | event-driven | 自身 `stop` / `_stop_client_silently` | exact |
| `server/codegraph/management/commands/measure_lsp_baseline.py` | utility | batch | `measure_gopls_init_time.py` | exact |
| `server/codegraph/management/commands/revisit_impact03_samples.py` | utility | batch | `measure_*` + `test_cross_repo_hop` 诚实退出 | role-match |
| `server/tests/services/code_graph/test_security_scan_report.py` | test | request-response | `test_impact_report.py` | exact |
| `server/tests/services/code_graph/test_semgrep_scan.py` | test | batch | mock-subprocess 测（对齐 indexer/repo_mirror 测姿） | role-match |
| `server/tests/services/code_graph/test_semgrep_enqueue.py` | test | event-driven | `test_process_enqueue.py` | exact |
| `server/tests/codegraph/test_security_finding_model.py` | test | CRUD | SymbolCommunity/ProcessTrace 模型测 | role-match |
| `server/codegraph/lsp/tests/test_orphan_reap.py` | test | batch | `codegraph/lsp/tests/test_*_check.py` | role-match |

## Pattern Assignments

### `server/services/code_graph/security_scan_report.py` (utility, transform)

**Analog:** `server/services/code_graph/impact_report.py` — **clone paradigm for `## 安全扫描`**

**Imports / marker / idempotent append** (lines 12–63):
```python
from __future__ import annotations
import structlog
from django.conf import settings
from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)
IMPACT_SECTION_MARKER: Final[str] = "## 影响面"  # → SECURITY_SECTION_MARKER = "## 安全扫描"

def append_impact_report(description: str, section: str) -> str:
    if not section:
        return description or ""
    if IMPACT_SECTION_MARKER in (description or ""):
        return description
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section
```

**Stub + sanitize** (lines 72–97):
```python
def _map_error_code(raw: str | None) -> str:
    code = (raw or "").strip() or "unavailable"
    if len(code) > 64 or "/" in code or "\\" in code or " " in code:
        return "unavailable"
    return code

def _sanitize_error_text(text: str) -> str:
    cleaned = redact_secrets_in_text(text or "")
    if "Traceback" in cleaned:
        cleaned = cleaned.split("Traceback", 1)[0].rstrip()
    cleaned = _ABS_PATH_RE.sub("[path]", cleaned)
    return cleaned[:500]

def _stub_section(error_code: str) -> str:
    safe = _map_error_code(error_code)
    return (
        f"{IMPACT_SECTION_MARKER}\n\n"
        f"_影响面报告未能生成（`{safe}`）。MR 已照常创建，请人工复核变更影响。_\n"
    )
```

**Fail-open build + observability** (lines 343–435):
```python
async def build_impact_report_section(...) -> str:
    # 永不 raise 阻断建 MR；TimeoutError → stub("timeout")；Exception → stub("unavailable")
    try:
        logger.info("impact_report_started", component="code_graph", category="caller", ...)
    except Exception:
        pass
    try:
        envelope = await asyncio.wait_for(..., timeout=timeout)
    except TimeoutError:
        return _safe_stub("timeout", error="wait_for_timeout")
    except Exception as exc:
        return _safe_stub("unavailable", error=_sanitize_error_text(str(exc)))
```

**Copy for Phase 127:** rename marker → `## 安全扫描`；stub 文案 →「安全扫描未能生成」；加 CE disclaimer / severity 列表；**不得**覆盖 `## 影响面`。

---

### Dual-link MR hang points (controller/service, request-response)

**Analogs (already wire `append_impact_report`):**

1. `server/workflows/nodes/ai/coding.py` (~2227–2252)
2. `server/workflows/services/mr_service.py` (~183–210)
3. `server/mcp_tools/merge_request_service.py` (~152–172)

**Core hang-point pattern** (`coding.py`):
```python
try:
    from services.code_graph.impact_report import (
        append_impact_report,
        build_impact_report_section,
    )
    section = await build_impact_report_section(
        repository=repository, user=user,
        compare=branch_name, base_ref=resolved_target,
    )
    body = append_impact_report(body, section)
except Exception as exc:  # noqa: BLE001 — 最后兜底；helper 内应已吞
    try:
        logger.warning(
            "impact_report_shell_failed",
            component="workflows", category="caller",
            repository_id=str(getattr(repository, "id", "") or ""),
            error=str(exc)[:200],
        )
    except Exception:
        pass
```

**Copy for Phase 127:** 同缝再挂 `append_security_scan` / stub-or-enqueue；外壳 `except` 事件名可对称 `security_scan_shell_failed`；逻辑必须在 helper 内，禁止三壳分叉。首版：创建时 stub + fire-and-forget enqueue（D-04）。

---

### `server/services/code_graph/semgrep_scan.py` (service, batch)

**Analog A — subprocess wrapper:** `server/services/repo_mirror.py` `_run_cmd` (lines 109–128)

```python
async def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode or 0, stdout, stderr
```

**Analog B — merge-base:** `server/services/indexer.py` `_get_merge_base` (lines 548–562)

```python
async def _get_merge_base(repo_path: str, base_ref: str, feature_ref: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "merge-base", base_ref, feature_ref,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    if proc.returncode != 0:
        raise GitDiffError(f"git merge-base failed: {stderr.decode()}")
    return stdout.decode().strip()
```

**CLI argv contract (from RESEARCH, implement via settings `SEMGREP_BIN`):**
```text
[SEMGREP_BIN, "scan",
 "--baseline-commit", <merge-base>,
 "--json", "--quiet",
 "--timeout", <SEMGREP_RULE_TIMEOUT>,
 "--config", "p/python", ...   # CSV from SEMGREP_CONFIGS
 # optional: "--include", path...
]
```
⛔ 用 `semgrep scan` 非 `semgrep ci`；argv 列表传递；永不 `import semgrep`。

**Token inject analog:** `server/services/feishu_im.py` (lines 1010–1021)

```python
app_secret_setting = await SystemSetting.objects.filter(
    key=SettingKeys.FEISHU_APP_SECRET
).afirst()
if app_id_setting and app_secret_setting and ...:
    app_secret = (
        decrypt_value(app_secret_setting.value)
        if app_secret_setting.is_encrypted
        else app_secret_setting.value
    )
```

**Copy:** 仅当 token 非空时 `env["SEMGREP_APP_TOKEN"] = token`；**永不** log/MR/ledger 明文。

---

### `server/services/repo_mirror.py` public worktree wrapper (service, file-I/O)

**Analog:** private `_ensure_worktree` (lines 466–496) + `ensure_mirror_sha`

```python
def _worktree_root(repository_id: str) -> Path:
    return Path(settings.REPO_CLONE_DIR) / f"{repository_id}.worktrees"

async def _ensure_worktree(snapshot: MirrorSnapshot) -> Path:
    root = _worktree_root(snapshot.repository_id)
    target = root / snapshot.commit_sha[:12]
    if (target / ".git").exists():
        return target
    async with _lock_for(f"worktree:{snapshot.repository_id}"):
        # prune stale → worktree add --detach --force
        ...
```

**Copy:** 新增薄公共 API（如 `ensure_worktree_for_scan`）包装上述私有路径；业务层禁止长期依赖 `_ensure_worktree`。扫描前 `ensure_mirror_sha` 两端 SHA + merge-base；失败 → fail-open stub `unavailable`。

---

### `server/services/code_graph/semgrep_enqueue.py` (utility, event-driven)

**Analog:** `server/repositories/charter_enqueue.py` (lines 17–69) — best-effort defer + slot lock

```python
async def enqueue_charter_draft(
    repository_id: str, *, initiated_by_user_id: str | None = None,
) -> str | None:
    from durable.concurrency import acharacter_lock
    from durable.queues import QUEUE_CHARTER
    from durable.service import DurableTaskService

    started = time.monotonic()
    try:
        lock = await acharacter_lock(str(repository_id))
        job_id = await DurableTaskService.defer(
            "durable_charter_draft",
            {"repository_id": str(repository_id)},
            queue=QUEUE_CHARTER,
            idempotency_key=f"charter:{repository_id}",
            lock=lock,
            initiated_by_user_id=initiated_by_user_id,
        )
        logger.info("enqueue_charter_draft_completed", category="caller", ...)
        return job_id
    except Exception as exc:
        logger.warning(
            "enqueue_charter_draft_failed",
            error=redact_secrets_in_text(str(exc)), ...
        )
        return None  # 不抛
```

**Also copy:** `server/services/process_enqueue.py`（同形、无 claim 事务，更接近扫描入队）。

**Phase 127 mapping:**
- task name: `durable_semgrep_scan`
- queue: `QUEUE_SCAN`
- `idempotency_key=f"semgrep:{repo_id}:{mr_key}"`
- `lock=scan-slot-{stable_hash(repo)%N}`，N=2

---

### `server/durable/queues.py` + `concurrency.py` (config/utility, event-driven)

**Queue analog** (`queues.py` lines 33–49):
```python
QUEUE_CHARTER = "charter"
ALL_QUEUES: tuple[str, ...] = (
    QUEUE_INDEX, QUEUE_GRAPH, ..., QUEUE_CHARTER,
)
```
**Add:** `QUEUE_SCAN = "scan"` 并加入 `ALL_QUEUES`（`run_worker` 默认消费全集）。

**ConcurrencyWindow / slot analog** (`concurrency.py` lines 27–78, 161–181):
```python
DEFAULT_CHARTER_CONCURRENCY = 4
_CHARTER_SLOT_PREFIX = "charter-slot-"

def charter_slot_lock(repo_id: str, n: int) -> str:
    return f"{_CHARTER_SLOT_PREFIX}{_stable_slot(repo_id, n)}"

async def acharacter_lock(repo_id: str) -> str:
    return charter_slot_lock(repo_id, await aget_charter_concurrency())
```

**Copy:** `DEFAULT_SCAN_CONCURRENCY = 2`；`scan_slot_lock` / `ascan_lock`；`SettingKeys.CONCURRENCY_SCAN_MAX`。

---

### `server/durable/tasks.py` + `tasks_impl.py` (route/service, event-driven)

**Task shell analog** (`tasks.py` lines 268–285):
```python
@app.task(name="durable_charter_draft", queue=QUEUE_CHARTER)
async def durable_charter_draft(
    *, repository_id: str, initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    from durable.tasks_impl import run_charter_draft
    return await run_charter_draft(
        repository_id=repository_id,
        initiated_by_user_id=initiated_by_user_id,
    )
```

**Task body analog** (`tasks_impl.py` lines 747–826):
```python
actor = initiated_by_user_id or "system"
logger.info("community_rebuild_job_started", category="caller", component="code_graph", ...)
with bind_task_context(user_id=actor, source="durable", component="code_graph"):
    try:
        result = await rebuild_communities(...)
    except Exception as exc:
        logger.warning(
            "community_rebuild_job_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=...,
        )
        raise
    logger.info("community_rebuild_job_completed", duration_ms=..., ...)
    return result
```

**Copy for `run_semgrep_scan`:** bind context；墙钟内跑 CLI；超时/CLI 失败 → 写 stub 段回填 MR（**勿** re-raise 阻断建 MR 路径——扫描任务自身可记 failed 但业务语义 fail-open）；完成后 persist `SecurityFinding` + patch MR body。

---

### Async MR description backfill (service, request-response)

**Analog:** `server/workflows/services/pr_cross_reference.py` (lines 167–180)

```python
if hasattr(client, "_get_repo"):
    repo_obj = client._get_repo()
    pr = await asyncio.to_thread(repo_obj.get_pull, int(mr_id))
    await asyncio.to_thread(pr.edit, body=new_body)
elif hasattr(client, "_get_project"):
    project = client._get_project()
    mr_obj = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
    mr_obj.description = new_body
    await asyncio.to_thread(mr_obj.save)
```

**Copy:** 用 `aresolve_git_token` + `get_git_platform_client`；替换/填充 `## 安全扫描` 段（stub→完整结果）；逐平台 try/except fail-soft。

---

### `server/codegraph/models.py` — `SecurityFinding` (model, CRUD)

**Analog:** `SymbolCommunity` / `ProcessTrace` (lines 341–440) — soft refs, no Symbol FK

```python
class SymbolCommunity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        "repositories.Repository", on_delete=models.CASCADE,
        related_name="symbol_communities",
    )
    branch_name = models.CharField(max_length=200, default="", blank=True)
    # members JSON 软引用 Symbol.id — ⛔ 不给 Symbol 加 FK
    members = models.JSONField(default=list)
    built_at_sha = models.CharField(max_length=64, blank=True, default="")
```

**SecurityFinding fields (from RESEARCH):** repository FK、branch_name、mr_key、rule_id、severity、file_path、line、message（预脱敏）、fingerprint、scan_sha、status=`open`；⛔ 不对 Symbol FK。

---

### `server/system/models.py` + settings — Semgrep + kill-switch (config/model)

**Encrypted SettingKeys analog** (`system/models.py` lines 63–65, 118–128):
```python
FEISHU_APP_SECRET = "feishu_app_secret"
CONCURRENCY_CHARTER_MAX = "concurrency_charter_max"  # 默认 4
```

**Add:** `SEMGREP_APP_TOKEN`（`is_encrypted=True` 写入路径）、`CONCURRENCY_SCAN_MAX`。

**Kill-switch — do NOT flip defaults** (`friday/settings.py` lines 1021–1034):
```python
VOLAR_BACKEND_ENABLED: bool = env.bool("VOLAR_BACKEND_ENABLED", default=False)
GOPLS_BACKEND_ENABLED: bool = env.bool("GOPLS_BACKEND_ENABLED", default=False)
```

**Add Semgrep settings only:** `SEMGREP_BIN`, `SEMGREP_TIMEOUT`, task wall-clock, `SEMGREP_CONFIGS` CSV；kill-switch 默认保持 False（D-12/D-16）。

---

### `server/Dockerfile` (config, file-I/O)

**Analog:** runtime stage lines 47–97 — install **before** `USER friday`

```dockerfile
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git openssh-client ripgrep ...
# ← INSERT: Semgrep /opt/semgrep + Node 22 + vue-language-server/typescript + Go/gopls
RUN groupadd -r friday && useradd -r -g friday ...
USER friday
```

**Copy discipline:** `ENV PATH` 对所有用户生效；装 `/opt/...` 或 `/usr/local`；构建末探针 `su friday -c 'semgrep --version && node -v && gopls version'`。⛔ 不改 `pyproject.toml` / `uv.lock`。

---

### LSP probes + supervisor lifecycle (utility/service)

**node_check analog** (`node_check.py` lines 66–125, 128–169): `subprocess.run` + process cache；失败 `available=False` 不 raise。

**go_check analog** (`go_check.py` lines 66–128, 131–179): `gopls version` / `go version`；同构 fail-soft。

**Supervisor stop** (`supervisor.py` lines 255–272, 324–339):
```python
async def stop(self) -> None:
    if self._status == LspSupervisorStatus.STOPPED:
        return
    await self._transition(LspSupervisorStatus.STOPPING, reason="explicit_stop")
    # cancel health/idle tasks
    await self._stop_client_silently()
    await self._transition(LspSupervisorStatus.STOPPED, reason="stopped")

async def _stop_client_silently(self) -> None:
    if self._client is None:
        return
    try:
        await self._client.stop(timeout=...)
    except Exception as exc:
        logger.warning("lsp_stop_client_silently_error", ...)
    self._client = None
```

**orphan_reap NEW:** 无现成 orphan 模块 → 用 `psutil`（已在 pyproject）+ cmdline 匹配 `gopls` / `vue-language-server`；排除 supervisor live-set；事件 `lsp_process_reaped`（`category=sampling`, `component=codegraph.lsp`）；best-effort `except: pass`。索引路径 `finally: await supervisor.stop()` + reap。

---

### `measure_lsp_baseline.py` / `revisit_impact03_samples.py` (utility, batch)

**Analog:** `server/codegraph/management/commands/measure_gopls_init_time.py` (lines 44–96)

```python
class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--repo-root", required=True)
        parser.add_argument("--output-json", default="...")
        parser.add_argument("--skip-on-missing-binary", action="store_true", default=True)

    def handle(self, *args, **options):
        if shutil.which("gopls") is None:
            if options.get("skip_on_missing_binary", True):
                self.stdout.write("...跳过测量（advisory）。")
                return
            raise SystemExit(1)
        report = self._measure(...)
        output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
```

**Copy:** before/after 计数 + 耗时 JSON 落 `.planning/phases/127-semgrep-lsp/`；缺二进制 skip exit 0。IMPACT-03：`CrossRepoApiCall` count==0 → 写诚实延期段落；>0 → 抽四分支（勿宣称合成测 = 真实验证）。

---

### Tests

**Analog:** `server/tests/services/code_graph/test_impact_report.py` — idempotent append + stub omits secrets (lines 337–368)

```python
def test_append_impact_report_idempotent() -> None:
    section = "## 影响面\n\n_stub_"
    base = "hello\n\n## 影响面\n\nold"
    assert append_impact_report(base, section) == base
    assert out.count("## 影响面") == 1

async def test_stub_omits_stack_and_secrets() -> None:
    # patch 抛含 token/绝对路径/Traceback → section/日志无明文
```

**Enqueue analog:** `server/tests/services/code_graph/test_process_enqueue.py` — assert task/queue/idempotency_key；defer 失败返回 None。

## Shared Patterns

### Authentication / initiator binding
**Source:** `durable/tasks_impl.py` `bind_task_context` + enqueue `initiated_by_user_id`
**Apply to:** all durable scan jobs + MR helpers
```python
with bind_task_context(user_id=initiated_by_user_id or "system", source="durable", component="..."):
    ...
```

### Error handling / fail-open
**Source:** `impact_report.build_impact_report_section` + hang-point outer `except`
**Apply to:** security scan section, enqueue, MR patch, LSP orphan reap
- Helper 永不 raise 阻断建 MR
- 稳定短码：`timeout` / `unavailable` / …
- stub 禁堆栈 / 绝对路径 / 凭证

### Validation / subprocess safety
**Source:** `repo_mirror._run_cmd` + settings absolute `SEMGREP_BIN`
**Apply to:** semgrep_scan
- argv list only；timeout bound；parse `--json`；finding 非零条数 ≠ CLI 失败

### Logging / redaction
**Source:** observability rules + `redact_secrets_in_text` in impact_report / enqueue
**Apply to:** all new modules
- events: `*_started` / `*_completed` / `*_failed` + `duration_ms`
- `category` + `component`；finding 循环用 sampling/debug
- `SEMGREP_APP_TOKEN` 永不进日志

### Soft-reference models
**Source:** `SymbolCommunity` / `ProcessTrace`
**Apply to:** `SecurityFinding`
- Repository FK OK；Symbol/Endpoint 禁 FK；message 入库前脱敏

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `server/codegraph/lsp/orphan_reap.py` | utility | batch | 无现成 orphan 收割模块；合成 `supervisor.stop` + `psutil.process_iter`（RESEARCH 草图） |

（其余文件均有 exact 或 role-match 模拟。）

## Frozen / Do-Not-Touch

| Path | Reason |
|------|--------|
| `server/codegraph/services/repo_router_v2.py` | D-18 冻结 |
| `mcp/` submodule | D-18 / 122 D-27 |
| `server/pyproject.toml` / `uv.lock`（Semgrep 依赖） | D-01 禁止 |
| Concurrent WIP outside phase intent | D-18 staging discipline |

## Metadata

**Analog search scope:** `server/services/code_graph/`, `server/durable/`, `server/codegraph/lsp/`, `server/repositories/*enqueue*`, `server/workflows/`, `server/mcp_tools/`, `server/Dockerfile`, `server/friday/settings.py`, `server/system/models.py`, `server/codegraph/management/commands/measure_*`
**Files scanned:** ~45
**Pattern extraction date:** 2026-08-10
**Strong analogs used (top 5):**
1. `impact_report.py` — MR section paradigm
2. `charter_enqueue.py` + `concurrency.py` — durable QUEUE + slot lock
3. `node_check.py` / `go_check.py` / `supervisor.py` — LSP probe + lifecycle
4. `repo_mirror._run_cmd` + `indexer._get_merge_base` — subprocess CLI（非 Python import）
5. `SymbolCommunity` / `FEISHU_APP_SECRET` — soft model + encrypted settings
