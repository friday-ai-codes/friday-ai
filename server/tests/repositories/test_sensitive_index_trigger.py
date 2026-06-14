"""Phase 24 Plan 02 Task 1 — run_full_index 后台触发敏感检测 guard 测试（EXCL-03）。

覆盖 FINALIZING 末尾的检测派发（D-03 触发 + D-04 fail-safe）：

- **Section A 白盒源码断言**：``run_full_index`` 源码必须在 ``return success`` 前经
  ``run_in_background`` 派发 ``detect_sensitive_files``，且整段包 try/except。
- **Section B 功能集成断言**：模块内 ``_finalize_with_detection`` helper **字面复刻**
  indexer.py FINALIZING 末尾的派发模板（含 ``return success``），mock
  ``detect_sensitive_files`` 后验证：
    1. 索引完成后 stub 收到 ``(repository_id, repo_path)``（经后台 runner 收敛）。
    2. stub 抛异常时 helper 仍返回 ``status=="success"``（检测失败不阻断索引，T-24-05）。
- **Section C 漂移 guard**：indexer.py 源码必须含派发模板关键 token。

测试用 ``background_runner._reset_for_tests`` / ``wait_for_pending`` 控制后台任务收敛。
"""

from __future__ import annotations

import inspect

import pytest
import structlog

from services import background_runner
from services.background_runner import run_in_background, wait_for_pending
from services.indexer import IndexerService

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Section B helper：字面复刻 indexer.py run_full_index FINALIZING 末尾派发模板。
# 与 indexer.py 内联模板保持一致——任一处改动需双向同步（Section C token guard 兜底）。
# ---------------------------------------------------------------------------


def _finalize_with_detection(repository_id: str, repo_path: str) -> dict:
    """复刻 run_full_index 末尾：best-effort 派发检测 + return success。"""
    try:
        from services.background_runner import run_in_background
        from services.sensitive_detect import detect_sensitive_files

        run_in_background(
            lambda: detect_sensitive_files(repository_id, repo_path),
            name=f"sensitive-detect:{repository_id}",
        )
    except Exception:
        logger.warning(
            "sensitive_detect_dispatch_failed",
            repository_id=repository_id,
            exc_info=True,
        )

    return {
        "status": "success",
        "files_processed": 0,
        "chunks_indexed": 0,
        "added": 0,
    }


@pytest.fixture(autouse=True)
def _reset_background_runner():
    """每例前后重置后台 runner，避免跨用例的 Future 串扰。"""
    background_runner._reset_for_tests()
    yield
    background_runner._reset_for_tests()


# ---------------------------------------------------------------------------
# Section A：run_full_index 白盒源码结构断言
# ---------------------------------------------------------------------------


def test_run_full_index_dispatches_detection_before_return() -> None:
    """``run_full_index`` 必须在 ``return {"status": "success"`` 之前经
    ``run_in_background`` 派发 ``detect_sensitive_files``，且包 try/except。
    """
    src = inspect.getsource(IndexerService.run_full_index)

    dispatch_idx = src.find("detect_sensitive_files")
    # FINALIZING 末尾的 success 返回是最后一处 success 字面量。
    return_idx = src.rfind('"status": "success"')

    assert dispatch_idx >= 0, "run_full_index 缺少 detect_sensitive_files 派发"
    assert "run_in_background" in src, "run_full_index 缺少 run_in_background 派发"
    assert return_idx >= 0, "run_full_index 缺少 success 返回"
    assert dispatch_idx < return_idx, (
        "detect_sensitive_files 派发应位于 return success 之前（FINALIZING 末尾）"
    )

    # 派发段必须有 try/except 兜底（派发失败不阻断 success）。
    pre_return = src[:return_idx]
    sentinel = "sensitive_detect_dispatch_failed"
    assert sentinel in pre_return, (
        "run_full_index 派发段缺少 try/except 兜底日志 sensitive_detect_dispatch_failed"
    )


# ---------------------------------------------------------------------------
# Section B：派发模板功能集成（成功触发 / 检测失败不阻断）
# ---------------------------------------------------------------------------


def test_detection_dispatched_with_repository_id_and_repo_path(monkeypatch) -> None:
    """索引完成后，detect_sensitive_files stub 应收到 (repository_id, repo_path)。"""
    captured: dict[str, object] = {}

    async def _stub(repository_id: str, repo_path: str) -> int:
        captured["args"] = (repository_id, repo_path)
        return 0

    monkeypatch.setattr(
        "services.sensitive_detect.detect_sensitive_files", _stub, raising=True
    )

    result = _finalize_with_detection("repo-123", "/tmp/repo-abc")
    assert result["status"] == "success"

    wait_for_pending(timeout=10.0)
    assert captured.get("args") == ("repo-123", "/tmp/repo-abc")


def test_index_returns_success_when_detection_raises(monkeypatch) -> None:
    """检测 stub 抛异常时，索引仍返回 status==success（fail-safe，T-24-05）。"""

    async def _boom(repository_id: str, repo_path: str) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "services.sensitive_detect.detect_sensitive_files", _boom, raising=True
    )

    result = _finalize_with_detection("repo-456", "/tmp/repo-xyz")
    # 检测在后台异步执行，索引返回不依赖其结果。
    assert result["status"] == "success"

    # 后台 runner 吞掉异常（wait_for_pending 内部 except pass），不冒泡到调用方。
    wait_for_pending(timeout=10.0)


def test_dispatch_failure_does_not_break_success(monkeypatch) -> None:
    """派发自身失败（run_in_background raise）也不得阻断 success 终态。"""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(
        "services.background_runner.run_in_background", _raise, raising=True
    )

    # 模板内 from-import 取到 patch 后的 run_in_background → 抛异常被 try/except 吞。
    result = _finalize_with_detection("repo-789", "/tmp/repo-fail")
    assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Section C：indexer.py 派发模板 token 漂移 guard
# ---------------------------------------------------------------------------


def test_indexer_dispatch_template_tokens_present() -> None:
    """indexer.py 必须含派发模板关键 token——防止与本测试 helper 漂移。"""
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    expected = [
        "from services.background_runner import run_in_background",
        "from services.sensitive_detect import detect_sensitive_files",
        "run_in_background(",
        "detect_sensitive_files(self.repository_id, repo_path)",
        "sensitive-detect:",
        "sensitive_detect_dispatch_failed",
    ]
    missing = [t for t in expected if t not in src]
    assert not missing, f"indexer.py 派发模板缺失 token：{missing}"


def test_run_in_background_accepts_factory_not_coroutine() -> None:
    """sanity：run_in_background 接收无参 factory（非 coroutine 本体）。"""
    called: list[int] = []

    async def _coro() -> int:
        called.append(1)
        return 42

    fut = run_in_background(lambda: _coro(), name="sanity-check")
    assert fut.result(timeout=10.0) == 42
    assert called == [1]
