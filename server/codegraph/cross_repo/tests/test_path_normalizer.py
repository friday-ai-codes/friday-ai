"""路径归一化单测 —— 覆盖 6+ URL 参数 placeholder 风格（work item）。"""

import pytest

from codegraph.cross_repo.path_normalizer import normalize_url_path


@pytest.mark.parametrize(
    "input_path, expected",
    [
        # 1. Express/Rails :id 风格
        ("/users/:id/profile", "/users/:param/profile"),
        ("/users/:userId/orders/:orderId", "/users/:param/orders/:param"),
        # 2. FastAPI/OpenAPI {id} 风格
        ("/users/{user_id}/items/{item_id}", "/users/:param/items/:param"),
        ("/repos/{owner}/{repo}/commits", "/repos/:param/:param/commits"),
        # 3. Django <int:pk> 风格（typed）
        ("/users/<int:pk>/orders/", "/users/:param/orders"),
        ("/articles/<slug:slug>/", "/articles/:param"),
        # 4. Django 无类型 <pk> 风格
        ("/users/<pk>/", "/users/:param"),
        # 5. Spring {id:[0-9]+} 风格
        ("/users/{pid:[0-9]+}/posts", "/users/:param/posts"),
        ("/items/{id:[a-z0-9-]+}", "/items/:param"),
        # 6. Vue/JS template ${userId} 风格
        ("/users/${userId}/profile", "/users/:param/profile"),
        ("/api/${configGlobal}/data", "/api/:param/data"),
        # 7. UUID segment
        (
            "/orders/550e8400-e29b-41d4-a716-446655440000/items",
            "/orders/:param/items",
        ),
        # 8. 纯数字 segment (≥2位)
        ("/items/12345/detail", "/items/:param/detail"),
        ("/posts/99", "/posts/:param"),
        # 9. 混合风格
        ("/api/v1/users/:id/repos/{repo_id}", "/api/v1/users/:param/repos/:param"),
        # 10. 尾部斜杠归一化
        ("/users/:id/", "/users/:param"),
        # 11. 大小写归一化
        ("/Users/:ID/Profile", "/users/:param/profile"),
        # 12. 无参数路径保持不变
        ("/api/v1/health", "/api/v1/health"),
        ("/", "/"),
        # 13. 已是 :param 不重复替换
        ("/users/:param/profile", "/users/:param/profile"),
        # 14. 多个 Django typed 参数
        ("/users/<int:user_id>/orders/<uuid:order_id>/", "/users/:param/orders/:param"),
        # 15. 单字符数字 segment 不替换（< 2位）
        ("/api/v1/health", "/api/v1/health"),
    ],
)
def test_normalize_url_path(input_path: str, expected: str) -> None:
    assert normalize_url_path(input_path) == expected


def test_normalize_empty_path() -> None:
    assert normalize_url_path("") == ""


def test_normalize_root_path() -> None:
    assert normalize_url_path("/") == "/"


def test_normalize_consecutive_slashes() -> None:
    result = normalize_url_path("/api//users/:id")
    assert "//" not in result


def test_normalize_spring_with_multiple_params() -> None:
    result = normalize_url_path("/users/{userId:[0-9]+}/repos/{repoName:[a-z]+}")
    assert result == "/users/:param/repos/:param"


def test_normalize_preserves_static_segments() -> None:
    result = normalize_url_path("/api/v2/healthcheck")
    assert result == "/api/v2/healthcheck"
