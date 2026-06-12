# 把存量 Repository 的 SSH 仓库地址改写为 HTTPS。
#
# 背景：任务容器（repo_summary / coding / explore）内没有 ssh，clone SSH 地址
# 必然失败（"error: cannot run ssh: No such file or directory"）；Access Token
# 认证也只兼容 HTTPS。入口侧已由 serializers.ssh_git_url_to_https 自动转换，
# 本迁移负责历史数据（转换逻辑按迁移惯例内联，不 import 应用代码）。

import re

from django.db import migrations

_SSH_SCP_RE = re.compile(r"^git@([^:/]+):(.+)$")
_SSH_URL_RE = re.compile(r"^ssh://(?:[^@/]+@)?([^:/]+)(?::\d+)?/(.+)$")


def _to_https(url: str) -> str:
    url = (url or "").strip()
    match = _SSH_SCP_RE.match(url) or _SSH_URL_RE.match(url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    return url


def convert_ssh_urls(apps, schema_editor):
    Repository = apps.get_model("repositories", "Repository")
    for repo in Repository.objects.all().iterator():
        new_git_url = _to_https(repo.git_url)
        new_proxy_url = _to_https(repo.proxy_url) if repo.proxy_url else repo.proxy_url
        if new_git_url != repo.git_url or new_proxy_url != repo.proxy_url:
            repo.git_url = new_git_url
            repo.proxy_url = new_proxy_url
            repo.save(update_fields=["git_url", "proxy_url"])


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0030_remote_head_branch_remove_description"),
    ]

    operations = [
        # 反向迁移无须还原（HTTPS 地址对所有链路都合法）
        migrations.RunPython(convert_ssh_urls, migrations.RunPython.noop),
    ]
