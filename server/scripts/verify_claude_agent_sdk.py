"""
环境验证脚本

验证 Claude Agent SDK subprocess 架构在 Python 3.14 + Django ASGI 环境下的兼容性。
覆盖三个维度：
  - SDK query() 正常返回文本响应
  - CLAUDE_* 环境变量在 SDK 子进程中被正确隔离
  - ASGI:   Django ASGI 环境下无 event loop 冲突

用法: cd server && uv run python scripts/verify_claude_agent_sdk.py

注：本文件原名 test_claude_agent_sdk.py 且位于 server/ 根目录。它不是 pytest 用例
（会真的起 SDK 子进程发请求），只因 pytest 的 testpaths=["tests"] 才没被收集——
改一次配置就会被当成测试跑。移入 scripts/ 并去掉 test_ 前缀以消除这个隐患。
"""

import asyncio
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import structlog
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

logger = structlog.get_logger()

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def clean_claude_env() -> Generator[dict[str, str], None, None]:
    """临时移除 os.environ 中所有 CLAUDE 前缀的环境变量，防止 SDK 子进程继承。

    SDK 内部通过 {**os.environ, **options.env} 构建子进程环境，
    无法通过 options.env 删除已有 key，因此必须在调用前从 os.environ 中移除。

    Yields:
        被移除的环境变量字典，便于验证函数检查哪些变量被清除。
    """
    saved: dict[str, str] = {}
    for key in list(os.environ):
        if key.startswith("CLAUDE") or key == "CLAUDECODE":
            saved[key] = os.environ.pop(key)
    try:
        yield saved
    finally:
        os.environ.update(saved)


def preflight_checks() -> bool:
    """前置检查：确认 API key 和 claude CLI 可用。"""
    ok = True

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("preflight_failed", reason="ANTHROPIC_API_KEY 环境变量未设置")
        ok = False

    if not shutil.which("claude"):
        logger.error("preflight_failed", reason="claude CLI 未找到，请确认 Claude Code 已安装")
        ok = False

    if ok:
        logger.info("preflight_passed")
    return ok


async def verify_text_response() -> bool:
    """验证 SDK query() 在 Python 3.14 + anyio 环境下正常返回文本响应。"""
    try:
        with clean_claude_env() as removed:
            if removed:
                logger.debug("env_cleaned", removed_keys=list(removed.keys()))

            options = ClaudeAgentOptions(
                system_prompt="Reply with exactly: FRIDAY_SDK_OK",
                permission_mode="plan",
                model="sonnet",
                max_turns=1,
            )

            messages: list[Any] = []
            async for message in query(prompt="Say the phrase", options=options):
                messages.append(message)
                logger.debug("message_received", type=type(message).__name__)

            if not messages:
                print("[FAIL] verify_text_response: 未收到任何消息")
                return False

            # 检查是否收到 ResultMessage
            result_messages = [m for m in messages if isinstance(m, ResultMessage)]
            if not result_messages:
                print(f"[FAIL] verify_text_response: 未收到 ResultMessage，收到的类型: {[type(m).__name__ for m in messages]}")
                return False

            print("[PASS] verify_text_response: SDK query() 正常返回文本响应")
            return True

    except Exception as e:
        print(f"[FAIL] verify_text_response: {e}")
        logger.exception("verify_text_response_error")
        return False


async def verify_env_isolation() -> bool:
    """验证 CLAUDE_* 环境变量不会泄漏到 SDK 子进程。"""
    # 注入测试标记变量
    test_vars = {
        "CLAUDE_TEST_MARKER": "should_not_leak",
        "CLAUDECODE": "1",
        "CLAUDE_FAKE_VAR": "test_value",
    }
    # 先保存已有值（如果有的话）
    original_values: dict[str, str | None] = {}
    for key, value in test_vars.items():
        original_values[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        with clean_claude_env() as removed:
            # 验证 context manager 内 os.environ 不含 CLAUDE_* 变量
            leaked_keys = [k for k in os.environ if k.startswith("CLAUDE") or k == "CLAUDECODE"]
            if leaked_keys:
                print(f"[FAIL] verify_env_isolation: context manager 内仍有 CLAUDE_* 变量: {leaked_keys}")
                return False

            # 验证我们注入的测试变量都被移除了
            for key in test_vars:
                if key not in removed:
                    print(f"[FAIL] verify_env_isolation: 测试变量 {key} 未被 clean_claude_env 移除")
                    return False

            # 通过 SDK 调用验证子进程环境（可选的二次确认）
            options = ClaudeAgentOptions(
                system_prompt="If you see any environment variable starting with CLAUDE in your environment, print its name and value. Otherwise print: NO_CLAUDE_VARS_FOUND",
                permission_mode="plan",
                model="sonnet",
                max_turns=1,
            )

            response_text = ""
            async for message in query(prompt="Check your environment for CLAUDE variables", options=options):
                if isinstance(message, ResultMessage):
                    response_text = str(message)

            if "should_not_leak" in response_text or "CLAUDE_TEST_MARKER" in response_text:
                print("[FAIL] verify_env_isolation: 测试标记变量泄漏到 SDK 子进程")
                return False

        # context manager 退出后，验证变量已恢复
        for key, value in test_vars.items():
            current = os.environ.get(key)
            if current != value:
                print(f"[FAIL] verify_env_isolation: 变量 {key} 未正确恢复（期望={value}, 实际={current}）")
                return False

        print("[PASS] verify_env_isolation: CLAUDE_* 环境变量已成功隔离")
        return True

    except Exception as e:
        print(f"[FAIL] verify_env_isolation: {e}")
        logger.exception("verify_env_isolation_error")
        return False
    finally:
        # 清理注入的测试变量，恢复原始状态
        for key in test_vars:
            if original_values[key] is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_values[key]  # type: ignore[assignment]


async def verify_asgi_compat() -> bool:
    """验证 Django ASGI 环境下 SDK 调用无 event loop 冲突。"""
    try:
        # 设置 Django 环境
        server_dir = str(Path(__file__).resolve().parent)
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

        import django

        django.setup()

        logger.info("django_setup_complete", settings=os.environ["DJANGO_SETTINGS_MODULE"])

        # 在 Django 已初始化的环境下调用 SDK
        with clean_claude_env() as removed:
            if removed:
                logger.debug("env_cleaned_asgi", removed_keys=list(removed.keys()))

            options = ClaudeAgentOptions(
                system_prompt="Reply with: ASGI_OK",
                permission_mode="plan",
                model="sonnet",
                max_turns=1,
            )

            messages: list[Any] = []
            async for message in query(prompt="Confirm", options=options):
                messages.append(message)

            if not messages:
                print("[FAIL] verify_asgi_compat: Django 环境下未收到任何消息")
                return False

        print("[PASS] verify_asgi_compat: Django ASGI 环境下 SDK 调用正常")
        return True

    except Exception as e:
        print(f"[FAIL] verify_asgi_compat: {e}")
        logger.exception("verify_asgi_compat_error")
        return False


async def main() -> None:
    """运行所有验证函数并打印总结。"""
    if not preflight_checks():
        print("\n前置检查失败，请修复上述问题后重试。")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(" implementation: 环境验证")
    print("=" * 60 + "\n")

    results: dict[str, bool] = {}

    # 依次运行三个验证（某个失败不阻止后续）
    for name, coro in [
        ("verify_text_response", verify_text_response()),
        ("verify_env_isolation", verify_env_isolation()),
        ("verify_asgi_compat", verify_asgi_compat()),
    ]:
        print(f"\n--- {name} ---")
        results[name] = await coro

    # 打印总结
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print("\n" + "=" * 60)
    print(f" 结果: {passed}/{total} 验证通过")
    print("=" * 60)

    if passed == total:
        print("\n环境验证完成，可以继续 implementation")
    else:
        failed = [name for name, ok in results.items() if not ok]
        print(f"\n以下验证失败: {', '.join(failed)}")
        print("请检查错误信息并修复后重试。")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
