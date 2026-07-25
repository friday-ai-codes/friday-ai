"""守护飞书 HTTP 统一超时口径。

httpx 的 `AsyncClient()` 默认 timeout=None，即永不超时。飞书侧半开连接 / DNS 卡死
会把 async worker 一直占住，级联拖垮工作流触发、webhook 处理与 IM 发卡，且没有
任何超时日志。本测试守住两件事：默认必须有限、且调用点不再退回裸 AsyncClient()。
"""

from __future__ import annotations

import pathlib

import pytest
from django.test import override_settings

from services.feishu_http import feishu_client, feishu_timeout

SERVER_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 曾经全量无超时、现已收敛到 feishu_client() 的调用点。
GUARDED_MODULES = (
    "services/feishu.py",
    "services/feishu_im.py",
    "services/feishu_doc.py",
    "feishu/client.py",
)


class TestFeishuTimeoutDefault:
    def test_default_timeout_is_finite(self):
        assert feishu_timeout() > 0

    @override_settings(FEISHU_HTTP_TIMEOUT_SECONDS=12.5)
    def test_timeout_reads_settings_at_runtime(self):
        """运行时读 settings，运维改 env 无需改代码。"""
        assert feishu_timeout() == 12.5

    @override_settings(FEISHU_HTTP_TIMEOUT_SECONDS=7.0)
    def test_client_carries_configured_timeout(self):
        client = feishu_client()
        # httpx 把 timeout 拆成 connect/read/write/pool 四项，逐一核对避免只设了其中之一
        assert client.timeout.connect == 7.0
        assert client.timeout.read == 7.0
        assert client.timeout.write == 7.0
        assert client.timeout.pool == 7.0

    def test_explicit_override_wins(self):
        """大文档导出这类长耗时接口可显式放宽，但仍是有限值。"""
        client = feishu_client(timeout=60.0)
        assert client.timeout.read == 60.0

    def test_extra_kwargs_pass_through(self):
        client = feishu_client(headers={"X-Test": "1"})
        assert client.headers["X-Test"] == "1"


class TestNoBareAsyncClientRegression:
    """防回退：这几个模块里不能再出现裸 `httpx.AsyncClient()`。

    直接扫源码而不是 mock——新增调用点时最容易顺手复制既有的裸写法，
    只有文本级守卫能拦住。
    """

    @pytest.mark.parametrize("rel_path", GUARDED_MODULES)
    def test_module_has_no_bare_async_client(self, rel_path: str):
        source = (SERVER_ROOT / rel_path).read_text(encoding="utf-8")
        assert "httpx.AsyncClient()" not in source, (
            f"{rel_path} 出现裸 httpx.AsyncClient()（默认永不超时）。"
            "请改用 services.feishu_http.feishu_client()。"
        )
