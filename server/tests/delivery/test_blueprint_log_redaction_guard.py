"""蓝图链日志脱敏守卫（114-MN-02 的根治面）。

`.cursor/rules/observability-logging.mdc` 明令：**异常文本与上游响应体必须经脱敏函数**
（`redact_credentials` 自动 processor 只覆盖结构化 kv 里的凭证形态字段，异常正文要显式走
`redact_secrets_in_text`）。114-05 的 Task 0 已为 `blueprint_transition_event_persist_failed`
补过一次，但同一份 diff 里又新写了三处 `error=str(exc)` 裸写 —— **靠人肉复核堵不住这一类**。

本文件把纪律变成断言：AST 遍历蓝图链的日志调用，任何 ``error=`` 实参都必须**经过**
:data:`_REDACTORS` 之一。最值得堵的是 ``blueprint_threads_reanchor_failed``——它兜的是整段
重锚（含 DB 异常与上游内容异常），而 ``anchor.quoted_text`` 是半可信蓝图正文的截取，
完全可能夹带凭证样本（T-114-27）。

⚠️ 扫描面刻意**只含蓝图链模块**：全仓还有大量早于本纪律的同款裸写，一次性收口不在本相位
的风险预算内（登记在 Fix Log）。新增蓝图模块请一并加进 :data:`_SCANNED_MODULES`。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SERVER_DIR = Path(__file__).resolve().parents[2]

# 蓝图链的日志产出面（114 触及 + 其直接依赖的会话 service）
_SCANNED_MODULES = (
    "delivery/api/blueprint_doc_views.py",
    "delivery/api/blueprint_list_views.py",
    "delivery/api/blueprint_review_views.py",
    "delivery/services/blueprint_comment_action.py",
    "delivery/services/blueprint_review_action.py",
    "delivery/services/blueprint_lifecycle_service.py",
    "delivery/services/blueprint_block_edit.py",
    "delivery/services/convergence_session_service.py",
    "services/process_runtime/blueprint_intake.py",
    "services/process_runtime/blueprint_reflow.py",
    "services/process_runtime/blueprint_resume.py",
    "services/process_runtime/blueprint_review.py",
    "services/process_runtime/builtin_processes.py",
    # Phase 116 VIEW-04：蓝图入图 normalizer（半可信正文 + citation 来源进日志的新面）
    "knowledge/sources/blueprint.py",
    # Phase 116 VIEW-05：蓝图 markdown 渲染器（整份半可信正文流经它）
    "services/process_runtime/blueprint_render.py",
)

# 允许的脱敏出口：两个公共脱敏函数 + 各模块内已收口的脱敏 helper（`_detail` 自身走
# `redact_secrets_in_text` 后再截断，`_log` 是 review adapter 的统一埋点入口）
_REDACTORS = ("redact_secrets_in_text", "redact_credentials", "_detail", "redact_for_ledger")

# 只审这些 kwarg：它们承载异常/上游文本，是唯一可能把凭证带进日志的实参位
_TAINTED_KWARGS = ("error",)

_LOG_METHODS = ("debug", "info", "warning", "error", "exception", "critical")


def _log_calls(tree: ast.AST) -> list[ast.Call]:
    """所有 ``logger.<level>(...)`` 形态的调用。"""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _LOG_METHODS
            and isinstance(func.value, ast.Name)
            and func.value.id in ("logger", "log")
        ):
            calls.append(node)
    return calls


def _violations(rel: str) -> list[str]:
    src = (_SERVER_DIR / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: list[str] = []
    for call in _log_calls(tree):
        for keyword in call.keywords:
            if keyword.arg not in _TAINTED_KWARGS:
                continue
            segment = ast.unparse(keyword.value)
            if not any(name in segment for name in _REDACTORS):
                found.append(f"{rel}:{keyword.value.lineno}: {keyword.arg}={segment}")
    return found


@pytest.mark.parametrize("rel", _SCANNED_MODULES)
def test_every_error_kwarg_in_blueprint_logs_is_redacted(rel: str) -> None:
    violations = _violations(rel)
    assert not violations, (
        "日志的 error= 实参必须经脱敏函数（"
        + " / ".join(_REDACTORS)
        + "）：\n  "
        + "\n  ".join(violations)
    )


def test_the_guard_actually_catches_a_bare_exception_text(tmp_path: Path) -> None:
    """守护的守护：规则真的能逮住 ``error=str(exc)``（防扫描形同虚设）。"""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import structlog\n"
        "logger = structlog.get_logger(__name__)\n"
        "def f(exc):\n"
        "    logger.warning('boom', error=str(exc))\n"
        "    logger.info('ok', error=redact_secrets_in_text(str(exc)))\n",
        encoding="utf-8",
    )
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    segments = [
        ast.unparse(keyword.value)
        for call in _log_calls(tree)
        for keyword in call.keywords
        if keyword.arg == "error"
    ]

    assert segments == ["str(exc)", "redact_secrets_in_text(str(exc))"]
    assert not any(name in segments[0] for name in _REDACTORS)  # 裸写被判违规
    assert any(name in segments[1] for name in _REDACTORS)  # 脱敏后放行
