"""一键摄取 URL 解析 helper（Phase 32-01，ING-01 / CONTEXT Grey Area 2）。

把两个**不可信用户输入** URL 翻译成既有入口可消费的标识：

- ``parse_board_url``：飞书工作项看板 URL → ``BoardRef(feishu_project_key,
  work_item_type, work_item_id)``，可直接喂 ``WorkItemIdentity``（INV-1 三元组）。
- ``parse_mr_url`` / ``aresolve_repo_and_mr``：GitLab/GitHub MR/PR URL → 已落库
  ``Repository`` + ``mr_iid``（复用 ``services.git_platform`` 的 git URL 解析 helper，
  禁自写 git URL 解析）。

**SSRF 边界（T-32-01）**：解析仅抽取标识符，绝不把原始用户 URL 当抓取目标——
飞书走 32-02 项目加密凭证 client，MR diff 走**匹配到已落库 Repository** 的 git
platform client。任何不可解析输入一律返回 None（不抛、不旁路写），让上层记 skipped。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from repositories.models import GitPlatform, Repository
from services.git_platform import (
    extract_github_owner_repo,
    extract_gitlab_url,
    extract_project_path,
)

__all__ = [
    "BoardRef",
    "MRRef",
    "parse_board_url",
    "parse_mr_url",
    "aresolve_repo_and_mr",
]

# 飞书域（看板/工作项 URL 宿主）；非飞书域一律拒绝。
_FEISHU_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com")

# 飞书工作项 URL path：/{simple_name}/{url_type}/detail/{id}
# simple_name = feishu_project_key（见 mcp_tools/work_item_context_service 的 URL 构造佐证）。
# 仅匹配标准 .../detail/{数字 id} 形态——容器型工作项 URL 段不可靠（PF-09 实测
# URL type 段 ≠ API type_key，仅 issue/story 等标准类型可靠），不匹配即返回 None。
_BOARD_PATH_RE = re.compile(
    r"^/(?P<key>[^/]+)/(?P<type>[^/]+)/detail/(?P<id>\d+)/?$"
)

# GitLab MR：.../{namespace.../project}/-/merge_requests/{iid}（namespace 可嵌套组）。
_GITLAB_MR_PATH_RE = re.compile(
    r"^/(?P<path>.+?)/-/merge_requests/(?P<iid>\d+)/?$"
)
# GitHub PR：.../{owner}/{repo}/pull/{iid}
_GITHUB_PR_PATH_RE = re.compile(
    r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<iid>\d+)/?$"
)


@dataclass(frozen=True)
class BoardRef:
    """飞书工作项身份三元组（解析结果，可直接构造 ``WorkItemIdentity``）。"""

    feishu_project_key: str
    work_item_type: str
    work_item_id: int


@dataclass(frozen=True)
class MRRef:
    """MR/PR URL 解析结果（host + 项目路径 + iid）。"""

    host: str
    project_path: str
    mr_iid: str


def _is_feishu_host(netloc: str) -> bool:
    host = netloc.split("@")[-1].split(":")[0].lower()
    return host.endswith(_FEISHU_HOST_SUFFIXES) or host in {"feishu.cn", "larksuite.com"}


def parse_board_url(url: str) -> BoardRef | None:
    """飞书看板/工作项 URL → ``BoardRef``，不可解析 → None（不抛）。

    匹配标准形态 ``https://{feishu_host}/{simple_name}/{url_type}/detail/{id}``
    （正则容忍尾部 ``?query`` / ``#fragment``）。``simple_name`` 即 feishu_project_key，
    ``url_type`` 段作 ``work_item_type``，``id`` 转 int。

    PF-09：URL type 段 ≠ API type_key，仅对标准 issue/story 等可靠；**容器型工作项
    URL 段不可靠 = out of scope**，其非标准形态不命中本正则即返回 None（让上层记
    skipped）。任何非飞书域 / 缺段 / 非数字 id 同样返回 None。
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if not _is_feishu_host(parsed.netloc):
        return None
    match = _BOARD_PATH_RE.match(parsed.path)
    if not match:
        return None
    try:
        work_item_id = int(match.group("id"))
    except ValueError:
        return None
    return BoardRef(
        feishu_project_key=match.group("key"),
        work_item_type=match.group("type"),
        work_item_id=work_item_id,
    )


def parse_mr_url(url: str) -> MRRef | None:
    """GitLab MR / GitHub PR URL → ``MRRef``，非 MR/PR → None（不抛）。

    识别 GitLab ``.../{namespace}/{project}/-/merge_requests/{iid}`` 与 GitHub
    ``.../{owner}/{repo}/pull/{iid}``，取 host、project_path（namespace/project 或
    owner/repo）、mr_iid（数字串）。
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except (ValueError, TypeError):
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()

    gl = _GITLAB_MR_PATH_RE.match(parsed.path)
    if gl:
        return MRRef(host=host, project_path=gl.group("path"), mr_iid=gl.group("iid"))
    gh = _GITHUB_PR_PATH_RE.match(parsed.path)
    if gh:
        project_path = f"{gh.group('owner')}/{gh.group('repo')}"
        return MRRef(host=host, project_path=project_path, mr_iid=gh.group("iid"))
    return None


def _norm_path(path: str) -> str:
    p = path.strip().lower().rstrip("/")
    if p.endswith(".git"):
        p = p[:-4]
    return p.lstrip("/")


def _repo_host_path(repository: Repository) -> tuple[str, str] | None:
    """从 ``Repository.git_url`` 归一抽取 (host, project_path)，复用 git_platform helper。

    github 走 ``extract_github_owner_repo``，其余（gitlab/gitea/bitbucket）走
    ``extract_gitlab_url`` + ``extract_project_path``。任一抽取失败返回 None（跳过该行）。
    """
    git_url = repository.git_url
    if not git_url:
        return None
    try:
        if repository.git_platform == GitPlatform.GITHUB:
            owner, repo = extract_github_owner_repo(git_url)
            return "github.com", f"{owner}/{repo}"
        base = extract_gitlab_url(git_url)  # scheme://host
        host = urlparse(base).netloc.split("@")[-1].split(":")[0].lower()
        return host, extract_project_path(git_url)
    except ValueError:
        return None


async def aresolve_repo_and_mr(url: str) -> tuple[Repository, str] | None:
    """MR/PR URL → ``(Repository, mr_iid)``，无匹配 → None（不抛、不旁路写）。

    先 ``parse_mr_url`` 抽取 (host, project_path, iid)，再用复用的 git URL 解析 helper
    对 ``Repository.objects`` 逐行归一比对（host + project_path 不区分大小写、去
    ``.git`` / 末尾斜杠）。仓库集小，``async for`` 遍历可接受。强制匹配到已落库
    Repository 才放行（T-32-01：不存在 fetch 任意用户 URL 的路径）。
    """
    ref = parse_mr_url(url)
    if ref is None:
        return None
    target_path = _norm_path(ref.project_path)
    async for repository in Repository.objects.all():
        hp = _repo_host_path(repository)
        if hp is None:
            continue
        host, path = hp
        if host == ref.host and _norm_path(path) == target_path:
            return repository, ref.mr_iid
    return None
