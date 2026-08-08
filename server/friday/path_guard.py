"""`server/` 置顶守卫——解决第三方 `workflows` 包与本项目 app 的顶层名冲突。

`llama-index-workflows`（`llama-index-core` 的传递依赖）装了一个顶层 `workflows`
包，与本项目的 Django app `server/workflows` **同名**。editable 安装写的
`_editable_impl_friday.pth` 把 `server/` **追加**在 sys.path 末尾，排在 site-packages
之后，于是 `import workflows` 解析到第三方包，`workflows.schemas` / `workflows.routing`
等子模块一律 `ModuleNotFoundError`。

只有 cwd 恰好是 `server/` 时（`manage.py`、`make dev`）才因 cwd 优先而幸免——任何
从别处启动的脚本、entrypoint 都会踩中。历史上这段逻辑被抄了三份且两份是坏的：
`manage.py` 那份正确，`friday/asgi.py` 那份写成 `if server_dir not in sys.path`
（`.pth` 已经把它加进去了，条件恒假 ⇒ 永不置顶，纯靠 cwd 兜底）。故收敛为单一实现。

**取舍**：置顶后 `workflows` 恒指向本项目 app，第三方那个被遮蔽——`llama_index.core`
内部的 `from workflows.context import Context` 会失败。本仓从不 import `llama_index`
（只在 pyproject 里挂着 `llama-index` / `llama-index-vector-stores-qdrant` 两条依赖），
故此取舍成立。**若将来真要用 llama_index，两个包无法共存，届时必须改名本项目 app
或摘掉该依赖**，而不是回退本守卫。
"""

from __future__ import annotations

import os
import sys

__all__ = ["SERVER_DIR", "ensure_server_dir_first"]

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_server_dir_first() -> None:
    """把 `server/` 挪到 sys.path 最前（幂等）。

    注意判据是「**是否在最前**」而不是「是否在路径里」：后者被 `.pth` 恒满足，
    写成那样等于什么都不做（asgi.py 的历史 bug）。
    """
    if sys.path and sys.path[0] == SERVER_DIR:
        return
    # 先摘掉既有位置（`.pth` 追加在末尾）再置顶，避免同一路径在 sys.path 里留两份
    sys.path[:] = [p for p in sys.path if p != SERVER_DIR]
    sys.path.insert(0, SERVER_DIR)
