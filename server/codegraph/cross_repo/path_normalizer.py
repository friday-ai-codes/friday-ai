"""URL 路径归一化 —— 将 6+ 风格参数 placeholder 归一为 :param。

支持风格（按优先级顺序处理）：
1. Vue/JS template: ${userId} → :param
2. Django typed:    <int:pk> → :param
3. Django plain:    <pk>     → :param
4. Spring regex:    {id:[0-9]+} → :param
5. FastAPI/OpenAPI: {id}     → :param
6. Express/Rails:  :id       → :param（不影响已转换的 :param）
7. UUID segment              → :param
8. 纯数字 segment (≥2位)    → :param

per work item
"""

from __future__ import annotations

import re

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# Express/Rails :id 替换 —— 仅替换非 :param（防重复）
_EXPRESS_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")

_PARAM_SUBS: list[tuple[re.Pattern[str], str]] = [
    # 1. Vue/JS template: ${userId}, ${configGlobal.api}
    (re.compile(r"\$\{[^}]+\}"), ":param"),
    # 2. Django typed: <int:pk>, <slug:name>, <str:uuid>
    (re.compile(r"<[a-zA-Z_][a-zA-Z0-9_]*:[^>]+>"), ":param"),
    # 3. Django plain: <pk>, <id>
    (re.compile(r"<[^>]+>"), ":param"),
    # 4. Spring regex param: {id:[0-9]+}, {pid:[a-z]+}
    (re.compile(r"\{[^}:]+:[^}]+\}"), ":param"),
    # 5. FastAPI/OpenAPI: {user_id}, {item_id}
    (re.compile(r"\{[^}]+\}"), ":param"),
    # 6. UUID segment (处理 :id 之前，避免先替换成 :param 后被 Express 匹配)
    (_UUID_RE, ":param"),
    # 7. 纯数字 segment (≥2位，独立 path segment)
    (re.compile(r"(?<=/)\d{2,}(?=/|$)"), ":param"),
]


def normalize_url_path(path: str) -> str:
    """将 URL 路径中的动态参数 placeholder 归一为 :param，并转小写、去尾部斜杠。

    Args:
        path: 原始 URL 路径（可含各种框架风格的参数 placeholder）

    Returns:
        归一化后的路径字符串，如 "/users/:param/profile"

    Examples:
        >>> normalize_url_path("/users/:id/profile")
        '/users/:param/profile'
        >>> normalize_url_path("/users/{user_id}")
        '/users/:param'
        >>> normalize_url_path("/users/<int:pk>/")
        '/users/:param'
    """
    if not path:
        return path

    for pattern, replacement in _PARAM_SUBS:
        path = pattern.sub(replacement, path)

    # 处理 Express/Rails :id（排除已转换的 :param）
    def _replace_express(m: re.Match[str]) -> str:
        name = m.group(1)
        return ":param" if name != "param" else ":param"

    path = _EXPRESS_RE.sub(_replace_express, path)

    # 去重复的 :param（如误产生 :param:param）
    path = re.sub(r"(:param)+", ":param", path)

    # 转小写
    path = path.lower()

    # 去尾部斜杠（保留根路径 "/"）
    if len(path) > 1:
        path = path.rstrip("/")

    # 压缩连续斜杠
    path = re.sub(r"/+", "/", path)

    return path
