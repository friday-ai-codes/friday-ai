"""Git 仓库地址共享规范化工具。"""

from repositories.serializers import ssh_git_url_to_https


def normalize_git_url(url: str | None) -> str:
    """统一 SSH/HTTPS 地址用于仓库等价匹配。"""

    normalized = ssh_git_url_to_https(str(url or "")).strip().lower().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized
