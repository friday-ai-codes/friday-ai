"""initial implementation Wave：静态守护测试门禁。

覆盖：
- **success criterion httpx 清零**（work item / work item）：`server/workflows/nodes/ai/*.py` 无
  `async with httpx.AsyncClient` / `import httpx` 出现
- **success criterion work item 禁区冻结**（coding.py / coding_dispatcher.py / sdk/runner.py）：
  git diff `<phase_start_sha>` -- 对应文件 行数 == 0
- **Anti-pattern A-H 运行时可验证条款**：
  - A：禁 ChatPromptTemplate / `from langchain_core.prompts`
  - C：langchain_runner.py 不引入 ChatPromptTemplate
  - D：禁 `source="node_custom_api"` 第 5 种 source 枚举值
  - E：aget_claude_config 只作 model fallback（prompt.py / variable_extractor.py 调用
    点 ≤ 1 次）
  - F：禁 `async with httpx.AsyncClient` 进入 AI 节点
  - G：禁 SDKAgentRunner 回到 base_agent / prompt / variable_extractor / code_review
- **contract 完成**：workflow 节点测试文件无 `mock.patch("anthropic.AsyncAnthropic")`
- **work item 三节点 config_schema 新字段守护**：provider_credential_id 存在
- **work item API tier scope 校验存在性守护**：3 节点均含 `cred.scope == "project"`
  相关校验代码
- **work item 守护 base_ref 从 VALIDATION.md frontmatter.phase_start_sha
  读取**：避免 HEAD~10 硬编码的非确定性漂移

Test naming convention: `test_<domain>_<guard_intent>` for each structural guard.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import yaml

# ---------------------------------------------------------------------------
# 路径常量（pytest CWD = server/，见 server/pyproject.toml 的
# `[tool.pytest.ini_options].pythonpath = ["."]`）
# ---------------------------------------------------------------------------

AI_NODES_DIR = pathlib.Path("workflows/nodes/ai")
LANGCHAIN_RUNNER = pathlib.Path("agents/langchain_runner.py")
SERVER_TESTS_DIR = pathlib.Path("tests")
VALIDATION_MD = pathlib.Path(
    "../project docs"
)
REPO_ROOT = pathlib.Path("..")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ai_node_py_files(exclude: set[str] | None = None) -> list[pathlib.Path]:
    """列出 AI 节点 .py 文件（默认排除 `__init__.py`）。"""
    exclude = exclude or set()
    return [
        py
        for py in sorted(AI_NODES_DIR.glob("*.py"))
        if py.name != "__init__.py" and py.name not in exclude
    ]


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _get_phase_start_sha() -> str:
    """work item：从 VALIDATION.md frontmatter 读取 phase_start_sha。

    **不使用 HEAD~10 硬编码**（HEAD~10 是非确定性 —— 取决于运行时 commit 数）。
    checkpoint-01 首 task 必须写入 phase_start_sha；本测试读取后做 git diff。
    """
    if not VALIDATION_MD.exists():
        pytest.skip("private validation artifact is not shipped in the open-source tree")

    text = VALIDATION_MD.read_text(encoding="utf-8")
    # 解析 YAML frontmatter（between two --- lines）
    m = re.search(r"^---\n(.*?)\n---", text, re.MULTILINE | re.DOTALL)
    if not m:
        raise AssertionError("VALIDATION.md 缺少 YAML frontmatter")
    fm = yaml.safe_load(m.group(1))
    sha = fm.get("phase_start_sha", "")
    if not sha or not re.match(r"^[0-9a-f]{40}$", sha):
        raise AssertionError(
            f"VALIDATION.md frontmatter.phase_start_sha 非 40 字符 hex SHA，"
            f"实际：{sha!r}。checkpoint-01 首 task 必须写入；"
            f"禁止 HEAD~10 硬编码 base_ref（work item 决策）。"
        )
    return sha


def _git_diff_line_count(path: str, base_ref: str) -> int:
    """返回 git diff 在指定 base_ref 之后 -- <path> 的行数（--stat 行数）。

    工作目录切到 REPO_ROOT 确保 `git` 命令能找到 .git。
    """
    result = subprocess.run(
        ["git", "diff", "--stat", base_ref, "--", path],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    return len(result.stdout.strip().splitlines())


def _workflow_node_test_files() -> list[pathlib.Path]:
    """列出 workflow 节点测试文件（扫描 contract 老 mock 残留时用）。

    定位规则：
    - 位于 tests/ 目录（非 e2e 子目录）
    - 文件名含 workflow 节点关键词：`plan_generation` / `code_review` /
      `variable_extractor` / `ai_prompt_node` / `base_agent` / `node_migration`
    - 显式排除 chat 路径测试（test_chat_*.py / test_sdk_runner.py /
      test_title_service*.py / test_coding_session_graph.py）
    """
    patterns = (
        "test_plan_generation",
        "test_code_review",
        "test_variable_extractor",
        "test_ai_prompt_node",
        "test_base_agent",
        "test_node_migration",
        "test_node_provider_credential_resolution",
    )
    results = []
    for py in sorted(SERVER_TESTS_DIR.glob("test_*.py")):
        if any(p in py.name for p in patterns):
            results.append(py)
    return results


# ---------------------------------------------------------------------------
# Test 1 — success criterion httpx 清零（work item / work item / Anti-pattern F）
# ---------------------------------------------------------------------------


def test_no_httpx_client_in_ai_nodes() -> None:
    """success criterion / Anti-pattern F 守护：AI 节点无 `async with httpx.AsyncClient`。"""
    offenders: list[tuple[str, int]] = []
    for py in _ai_node_py_files():
        text = _read_text(py)
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"async with httpx\.AsyncClient", line):
                offenders.append((str(py), i))
    assert not offenders, (
        f"success criterion 违反：AI 节点出现 `async with httpx.AsyncClient`（work item/03 未完成）\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 2 — httpx 顶层 import 清零（prompt + variable_extractor 主战场）
# ---------------------------------------------------------------------------


def test_no_httpx_import_in_prompt_nodes() -> None:
    """prompt.py / variable_extractor.py 无 `import httpx`（success criterion 辅助守护）。"""
    targets = ("prompt.py", "variable_extractor.py")
    offenders: list[tuple[str, int]] = []
    for name in targets:
        path = AI_NODES_DIR / name
        if not path.exists():
            pytest.fail(f"必需文件缺失：{path}")
        text = _read_text(path)
        for i, line in enumerate(text.splitlines(), 1):
            # 匹配 `import httpx` 顶层 import（避免误匹配 `httpx.xxx` 字面量或注释）
            if re.match(r"^\s*import\s+httpx\b", line):
                offenders.append((str(path), i))
            if re.match(r"^\s*from\s+httpx\b", line):
                offenders.append((str(path), i))
    assert not offenders, (
        f"success criterion 违反：prompt.py / variable_extractor.py 仍 import httpx\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Anti-pattern A 守护：AI 节点禁 ChatPromptTemplate
# ---------------------------------------------------------------------------


def test_no_chat_prompt_template_in_ai_nodes() -> None:
    """work item / Anti-pattern A 守护：AI 节点禁 LangChain ChatPromptTemplate。

    精确匹配**实际用法**（import / 构造调用）而非注释守护文本；节点代码中
    以 `# 严禁 A：...ChatPromptTemplate...` 形式出现的注释是合法说明，不视为违反。
    """
    offenders: list[tuple[str, int, str]] = []
    for py in _ai_node_py_files():
        text = _read_text(py)
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            # 跳过纯注释行（守护说明）
            if stripped.startswith("#"):
                continue
            # 实际 import / 构造调用（不会出现在注释里）
            if re.search(r"from\s+langchain_core\.prompts\b", line):
                offenders.append((str(py), i, line.strip()))
            if re.search(r"\bChatPromptTemplate\s*[\(\.]", line):
                offenders.append((str(py), i, line.strip()))
    assert not offenders, (
        f"Anti-pattern A 违反：AI 节点出现 ChatPromptTemplate 实际用法\n"
        f"(contract / work item 要求纯 SystemMessage+HumanMessage 双包装)\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Anti-pattern C 守护：langchain_runner.py 不引入 ChatPromptTemplate
# ---------------------------------------------------------------------------


def test_no_chat_prompt_template_in_langchain_runner() -> None:
    """Anti-pattern C 守护：langchain_runner.py 不引入 ChatPromptTemplate。"""
    if not LANGCHAIN_RUNNER.exists():
        pytest.fail(f"必需文件缺失：{LANGCHAIN_RUNNER}")
    text = _read_text(LANGCHAIN_RUNNER)
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if re.search(r"from\s+langchain_core\.prompts\b", line):
            offenders.append((i, line.strip()))
        if re.search(r"\bChatPromptTemplate\s*[\(\.]", line):
            offenders.append((i, line.strip()))
    assert not offenders, (
        f"Anti-pattern C 违反：langchain_runner.py 引入 ChatPromptTemplate\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 5 — work item 守护（work item 改写：base_ref 从 VALIDATION frontmatter 读取）
# ---------------------------------------------------------------------------


# work item（rename-project-to-space merge c2b352bb，2026-05-11）：
# initial implementation / success criterion 锁定的 3 个 frozen file 在 v22.0 后期被 rename branch
# 改了纯参数名（project_id → space_id），不引入 httpx 残留也不破坏 LangChain
# Runner 行为契约。下面允许「rename-only」白名单 SHA：当被改动文件 vs base_ref
# 的 diff 仅命中这些 token 替换，则视为合规。
_RENAME_ALLOWED_SUBSTRING_PAIRS = (
    ("project_id", "space_id"),
    ("project ID", "space ID"),
    ("项目 UUID", "空间 UUID"),
    ("项目 ID", "空间 ID"),
)


@pytest.mark.parametrize(
    "path",
    [
        "server/workflows/nodes/ai/coding.py",
        "server/workflows/nodes/ai/coding_dispatcher.py",
        "server/agents/sdk/runner.py",
    ],
)
def test_node_04_frozen_files_unchanged(path: str) -> None:
    """success criterion / work item：禁区文件在 initial implementation 期间零改动（含 rename 白名单豁免）。

    **work item 决策**：base_ref 从 VALIDATION.md frontmatter.phase_start_sha
    读取，**不使用 HEAD~10 硬编码**。checkpoint-01 首 task 写入 phase_start_sha；
    本测试读取后做 git diff。

    **rename-relaxation**：若 diff 行仅命中 _RENAME_ALLOWED_SUBSTRING_PAIRS
    定义的语义重命名（不引入新调用、不改控制流），则放行。详见
    `_diff_only_contains_rename`。
    """
    base_ref = _get_phase_start_sha()
    diff_lines = _git_diff_line_count(path, base_ref=base_ref)
    if diff_lines == 0:
        return
    if _diff_only_contains_rename(path, base_ref=base_ref):
        return
    raise AssertionError(
        f"{path} 在 initial implementation 期间被改动（work item / success criterion 违反）；"
        f"diff {diff_lines} 行 vs base_ref {base_ref}"
    )


def _diff_only_contains_rename(path: str, *, base_ref: str) -> bool:
    """diff 的所有 +/- 行剥掉 _RENAME_ALLOWED_SUBSTRING_PAIRS 后必须等价。"""
    proc = subprocess.run(
        ["git", "diff", "-U0", base_ref, "--", path],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        return False

    removed: list[str] = []
    added: list[str] = []
    for raw in proc.stdout.splitlines():
        if raw.startswith(("---", "+++", "@@")) or not raw:
            continue
        if raw.startswith("-"):
            removed.append(raw[1:])
        elif raw.startswith("+"):
            added.append(raw[1:])

    if len(removed) != len(added):
        return False

    def _normalize(line: str) -> str:
        for old, new in _RENAME_ALLOWED_SUBSTRING_PAIRS:
            line = line.replace(old, new)
        return line

    return [_normalize(r) for r in removed] == added


# ---------------------------------------------------------------------------
# Test 8 — Anti-pattern D 守护：禁 source="node_custom_api" 第 5 种值
# ---------------------------------------------------------------------------


def test_no_node_custom_api_source_value() -> None:
    """Anti-pattern D 守护：`ResolvedProviderConfig.source` 保持四态，禁第 5 种值。

    允许 `extra={"source_detail": "node_custom_api"}` 标记降级路径；拒绝
    直接赋值给 `source=`。
    """
    # 精确匹配 `source="node_custom_api"` 或 `source='node_custom_api'`
    # 必须在 `source=` 位置（排除 `source_detail=` / `source_attempted=` 等）
    pattern = re.compile(
        r'(?<![A-Za-z_])source\s*=\s*["\']node_custom_api["\']'
    )
    offenders: list[tuple[str, int, str]] = []
    for py in _ai_node_py_files():
        text = _read_text(py)
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append((str(py), i, line.strip()))
    assert not offenders, (
        f"Anti-pattern D 违反：`source=\"node_custom_api\"` 第 5 种值出现\n"
        f"（分歧 A 锁定：source 保持四态 node/conversation/project/system；"
        f"降级路径请用 extra={{'source_detail': 'node_custom_api'}}）\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 9 — Anti-pattern G 守护：AI 节点清出 SDKAgentRunner（coding.py 例外）
# ---------------------------------------------------------------------------


def test_no_sdk_runner_import_in_ai_nodes() -> None:
    """work item 主干守护：base_agent / prompt / variable_extractor / code_review 无
    `SDKAgentRunner` 或 `agents.sdk.runner` 引用。

    **排除 coding.py**（AICodingNode 容器分发路径保留 SDKAgentRunner；work item 冻结）。
    """
    offenders: list[tuple[str, int, str]] = []
    for py in _ai_node_py_files(exclude={"coding.py", "coding_dispatcher.py"}):
        text = _read_text(py)
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\bSDKAgentRunner\b", line):
                offenders.append((str(py), i, line.strip()))
            if re.search(r"from\s+agents\.sdk\.runner\b", line):
                offenders.append((str(py), i, line.strip()))
    assert not offenders, (
        f"Anti-pattern G 违反：AI 节点出现 SDKAgentRunner（work item 主干回滚）\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 10 — contract 守护：workflow 节点测试文件无 `anthropic.AsyncAnthropic` mock
# ---------------------------------------------------------------------------


def test_no_anthropic_asyncanthropic_mock_in_workflow_tests() -> None:
    """contract 守护：workflow 节点测试文件完全迁移到 FakeChatModel。

    **排除 chat 路径测试 / e2e 测试**（chat_runner / sdk_runner / title_service 仍可
    通过 anthropic mock 驱动；contract 锁定 chat 路径不迁移）。
    """
    pattern = re.compile(r'mock\.patch\(["\']anthropic\.AsyncAnthropic')
    offenders: list[tuple[str, int, str]] = []
    for py in _workflow_node_test_files():
        text = _read_text(py)
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append((str(py), i, line.strip()))
    assert not offenders, (
        f"contract 违反：workflow 节点测试仍 mock `anthropic.AsyncAnthropic`\n"
        f"（应改用 conftest fake_chat_model_factory 注入 FakeChatModel）\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# initial implementation plan（contract/contract）：原 Test 11 Anti-pattern E 守护
# （aget_claude_config 只作 model fallback）随 claude_config.py 整文件硬删移除。
# 新的 fallback 路径：resolved.extra.default_model（来自 ProviderCredential）
# ——不再是 aget_claude_config。守护已失效。
# ---------------------------------------------------------------------------


def test_no_aget_claude_config_references_in_ai_nodes() -> None:
    """initial implementation plan 新守护：AI 节点不得再出现 aget_claude_config 任何引用
    （含 import / 调用 / 注释 docstring 外的代码）。

    防止未来重新引入已删除的 v8.1 legacy 路径。
    """
    forbidden_pattern = re.compile(r"\baget_claude_config\b")
    offenders: list[tuple[str, int, str]] = []
    for name in ("prompt.py", "variable_extractor.py", "base_agent.py", "coding.py"):
        path = AI_NODES_DIR / name
        if not path.exists():
            continue  # 非必需（若文件不存在 → 其他守护会报错）
        text = _read_text(path)
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if forbidden_pattern.search(line):
                offenders.append((str(path), i, line.rstrip()))
    assert not offenders, (
        f"initial implementation plan 守护违反：AI 节点仍引用已删除的 aget_claude_config\n"
        f"offenders: {offenders}"
    )


# ---------------------------------------------------------------------------
# Test 12 — work item 三节点 schema 字段守护：provider_credential_id 存在
# ---------------------------------------------------------------------------


def test_provider_credential_id_in_all_three_configs() -> None:
    """work item / work item 方案 A 守护：3 节点 config_schema 均含
    `provider_credential_id` 字段。
    """
    missing: list[str] = []
    for name in ("base_agent.py", "prompt.py", "variable_extractor.py"):
        path = AI_NODES_DIR / name
        if not path.exists():
            pytest.fail(f"必需文件缺失：{path}")
        text = _read_text(path)
        if "provider_credential_id" not in text:
            missing.append(name)
    assert not missing, (
        f"work item 违反：以下节点缺少 `provider_credential_id` 字段："
        f"{missing}（work item 方案 A 要求 task 一次性同步 3 节点 schema）"
    )


# ---------------------------------------------------------------------------
# Test 13 — work item 守护：3 节点均含 API tier scope 校验
# ---------------------------------------------------------------------------


def test_api_tier_scope_check_exists_in_all_three_nodes() -> None:
    """work item 守护：3 节点均含 API tier scope 校验代码（跨 project 拒绝）。

    匹配模式覆盖三种可能实现：
    1. inline `cred.scope == "project"` 校验
    2. inline `scope == "project"` + `scope_id` 比对
    3. 抽为 helper（`_validate_credential_scope` / `scope_check` 命名）
    """
    missing: list[str] = []
    scope_patterns = [
        re.compile(r'cred\.scope\s*==\s*["\']project["\']'),
        re.compile(
            r'scope\s*==\s*["\']project["\'].*scope_id', re.DOTALL
        ),
        re.compile(r"_validate_credential_scope|scope_check"),
    ]
    for name in ("base_agent.py", "prompt.py", "variable_extractor.py"):
        path = AI_NODES_DIR / name
        if not path.exists():
            pytest.fail(f"必需文件缺失：{path}")
        text = _read_text(path)
        if not any(p.search(text) for p in scope_patterns):
            missing.append(name)
    assert not missing, (
        f"work item 违反：以下节点缺少 API tier scope 校验代码"
        f"（security mitigation-01 disposition=mitigate 未落地）：{missing}；"
        f"应在 task 加 scope 校验或抽 helper"
    )


# ---------------------------------------------------------------------------
# Test 14 — work item phase_start_sha 合法性守护
# ---------------------------------------------------------------------------


def test_phase_start_sha_is_valid() -> None:
    """work item 守护：VALIDATION.md frontmatter.phase_start_sha 合法。

    双重校验：
    1. 是 40 字符 hex SHA（_get_phase_start_sha 内部断言）
    2. 该 SHA 在当前 git 仓库中确实存在（`git cat-file -e`）
    """
    sha = _get_phase_start_sha()  # 已校验 40 hex 格式
    result = subprocess.run(
        ["git", "cat-file", "-e", sha],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"phase_start_sha={sha} 在 git 中不存在；"
        f"checkpoint-01 必须写入当前 HEAD SHA（work item 确定性守护）"
    )
