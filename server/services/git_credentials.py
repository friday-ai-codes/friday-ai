"""Git 凭证统一解析器（Phase 26 REPO-01）。

单一入口解析仓库的 Git access token，消除散落各处的 per-repo 取 token 逻辑。

解析优先级（per D-02 向后兼容 + TOKEN-01 显式 FK）：
1. per-repo 显式 ``GitCredential.encrypted_token`` —— 既有部署行为不回退，优先返回；
2. 仓库显式选择的「密钥提供方」``Repository.git_instance_credential`` FK（实例凭证）；
3. 否则按仓库 URL 的归一化 host 命中 ``GitInstanceCredential`` 实例凭证池；
4. 都无 → 返回 None（不抛异常、不静默伪造）；调用方保留各自既有「缺凭证」明确报错。

老仓库（仅 per-repo token 或仅 host 匹配，未设 FK）行为零回归：FK 为空时第 2 步天然跳过。

安全契约（per D-04 / 威胁 T-26-02）：
- token 是 Fernet 密文存库，``decrypt_value`` 为唯一解密出口；
- 函数体内绝不把 token 明文拼进任何日志，仅记 boolean ``has_token`` / ``source``。

Wave 2（26-02/26-03/26-04）接线统一调用本模块，禁止另写取 token 逻辑。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import structlog
from asgiref.sync import sync_to_async

from common.encryption import decrypt_value
from repositories.models import GitCredential, GitInstanceCredential

__all__ = [
    "resolve_git_token_sync",
    "aresolve_git_token",
    "_extract_git_host",
    "aremote_branch_count",
]

logger = structlog.get_logger(__name__)

# SSH 形式 git@host:path，复用 git_platform.extract_gitlab_url 的解析口径
_SSH_RE = re.compile(r"^[^@]+@([^:/]+):")


def _extract_git_host(git_url: str | None) -> str | None:
    """从 git URL 解析归一化小写 host（含端口若有），无法解析返回 None。

    同时支持 SSH（``git@gitlab.example.com:ns/p.git``）与
    HTTPS（``https://gitlab.example.com[:port]/ns/p.git``）两种格式，
    确保同一实例的两种 URL 解析出一致的 host，避免错配凭证（威胁 T-26-03）。
    """
    if not git_url:
        return None

    url = git_url.strip()

    # scp 风格 SSH（git@host:path）没有 :// 协议头；带协议头的（https/http/ssh://）
    # 一律走 urlparse，避免 SSH 正则误吞 https://user@host:port 的 userinfo 段而丢端口
    # （威胁 T-26-03：同域不同端口错配凭证）。
    if "://" not in url:
        ssh_match = _SSH_RE.match(url)
        if ssh_match:
            return ssh_match.group(1).lower()

    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        # netloc 可能含 user@ 与端口；仅取 host[:port]，去掉可能的认证段，
        # 保留端口与实例凭证存储口径（host[:port]）一致。
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        return netloc.lower()

    return None


def resolve_git_token_sync(repo) -> str | None:
    """解析仓库的 Git access token（同步 ORM 核心）。

    Args:
        repo: Repository 实例（需含 id / git_url）。

    Returns:
        解密后的 token 明文字符串；无任何可用凭证时返回 None。
    """
    # ① per-repo 显式 token 优先（向后兼容 per D-02）
    credential = GitCredential.objects.filter(repository=repo).first()
    if credential and credential.encrypted_token:
        logger.debug("git_token_resolved", repo_id=str(repo.id), source="per_repo", has_token=True)
        return decrypt_value(credential.encrypted_token)

    # ② 仓库显式选择的密钥提供方 FK（TOKEN-01）——标量取 FK id 避免 async 上下文
    #    lazy-FK 访问；FK 为空（老仓库）天然跳过，零回归。
    instance_credential_id = getattr(repo, "git_instance_credential_id", None)
    if instance_credential_id:
        fk_instance = GitInstanceCredential.objects.filter(id=instance_credential_id).first()
        if fk_instance and fk_instance.encrypted_token:
            logger.debug(
                "git_token_resolved",
                repo_id=str(repo.id),
                source="instance_fk",
                has_token=True,
            )
            return decrypt_value(fk_instance.encrypted_token)

    # ③ 按 host 命中实例凭证池
    host = _extract_git_host(getattr(repo, "git_url", None))
    if host:
        instance = GitInstanceCredential.objects.filter(host=host).first()
        if instance and instance.encrypted_token:
            logger.debug(
                "git_token_resolved",
                repo_id=str(repo.id),
                source="instance_pool",
                host=host,
                has_token=True,
            )
            return decrypt_value(instance.encrypted_token)

    # ④ 无凭证 → None（调用方保留既有缺凭证报错）
    logger.debug("git_token_resolved", repo_id=str(repo.id), source="none", has_token=False)
    return None


aresolve_git_token = sync_to_async(resolve_git_token_sync)


async def aremote_branch_count(auth_url: str, proxy_url: str | None = None) -> int:
    """用 ``git ls-remote --heads`` 探测远端分支数（不落盘、轻量）。

    用途：空仓 fail-fast。``git clone --depth 1 --branch <default>`` 对「零分支空仓」
    会以晦涩的 ``Git clone failed`` 报错，易被误判为凭证/网络故障；先用 ls-remote
    判定是否真为空仓，让调用方给出明确状态、并避免为空仓白白起容器烧 token。

    Returns:
        - ``>=1``：远端存在分支（正常仓库）。
        - ``0``：远端零分支（空仓）。
        - ``-1``：探测失败（鉴权/网络/超时等不可判定）——调用方**不得**据此判定空仓，
          应放行走正常流程，由后续 clone 暴露真实错误（绝不把不可判定误标为空仓）。
    """
    import asyncio

    cmd = ["git"]
    if proxy_url:
        cmd += ["-c", f"http.proxy={proxy_url}"]
    cmd += ["ls-remote", "--heads", auth_url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            return -1
        return sum(1 for line in out.decode(errors="ignore").splitlines() if line.strip())
    except Exception:  # noqa: BLE001 — 探测失败回退 -1（不可判定），绝不阻断主流程
        return -1
