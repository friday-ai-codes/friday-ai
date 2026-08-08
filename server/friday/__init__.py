"""friday 项目包。

这里只做一件事：在**任何** Django 入口加载 app 之前把 `server/` 挪到 sys.path 最前。
`DJANGO_SETTINGS_MODULE=friday.settings` 决定了任何启动方式（manage.py / asgi / wsgi /
pytest / 临时脚本）都必经本模块，放在这里才能保证守卫不被绕过。原因与取舍见
`friday/path_guard.py`。
"""

from friday.path_guard import ensure_server_dir_first

ensure_server_dir_first()
