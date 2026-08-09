"""仓库本地裸镜像服务（MCP 精确检索 / 全量文件读取的数据源）。

设计动机：``search_rag_chunks`` 是语义 + 关键词的 top-k 召回，对「穷举所有出现
位置」这类 grep 语义的问题在数学上保证不了全量；``get_repository_file`` 从
Qdrant chunk 拼接内容，行号与完整性都受 chunk 切分影响。本服务在
``settings.REPO_CLONE_DIR/<repo_id>`` 维护一个 bare 镜像，直接用
``git grep`` / ``git show`` 给出确定性的全量结果。

检索引擎：装有 ripgrep 时优先在快照 worktree 上跑 ``rg --json``（并行遍历更快、
解析无歧义）；rg 不可用或失败时自动回退 ``git grep``（git 必然存在，bare 镜像
无需 worktree）。两个引擎对同一快照给出相同的全量结果，仅性能与依赖不同。

一致性策略：base 分支优先 pin 到 ``last_indexed_commit_sha``（与 RAG 索引同一
快照，``matches_index=True``）；该 sha 不可得（远端不允许按 sha fetch）时回退
分支 HEAD（``matches_index=False``，结果可能新于索引）。

安全约束：
- token 只出现在单次 ``git fetch`` 的 argv URL 中，绝不写入镜像的 git config；
- 错误信息统一脱敏（剥离 URL 中的凭证段）后才对外返回；
- 分支名 / pathspec 做白名单校验，pattern 经 ``-e`` 传参，无 shell 注入面。
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings

logger = structlog.get_logger(__name__)

_FETCH_TTL_SECONDS = 60.0
_FAILURE_TTL_SECONDS = 120.0
_GIT_TIMEOUT_SECONDS = 300.0
_MAX_GREP_OUTPUT_BYTES = 8 * 1024 * 1024
_MAX_FILE_OUTPUT_BYTES = 8 * 1024 * 1024
_MAX_LINE_CHARS = 400
# detect_changes 通路的 unified diff 上限（T-123-DOS）；超限明确 MirrorError
DETECT_CHANGES_MAX_DIFF_BYTES = 16 * 1024 * 1024

# git check-ref-format 的保守子集：禁止前导 '-'（防 argv 注入）与 '..'
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,254}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CREDENTIAL_URL_RE = re.compile(r"://[^/@\s]+@")

# asyncio.Lock 绑定首次 acquire 的事件循环；async_to_sync / 测试场景下每个请求
# 可能运行在新 loop 中，因此按 (loop_id, repo_id) 维度建锁，避免跨 loop 复用报错。
_locks: dict[tuple[int, str], asyncio.Lock] = {}
# (repo_id, ref) -> (commit_sha, fetched_at)
_fetch_cache: dict[tuple[str, str], tuple[str, float]] = {}
# repo_id -> (detail, failed_at)：避免不可达仓库反复触发慢速 clone/fetch
_failure_cache: dict[str, tuple[str, float]] = {}


class MirrorError(Exception):
    """镜像不可用 / 调用非法。code 对齐 MCP error_response。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class MirrorSnapshot:
    """一次镜像解析结果：在哪个目录、以哪个 commit 为快照。"""

    repository_id: str
    repo_dir: Path
    commit_sha: str
    ref: str
    matches_index: bool


@dataclass(frozen=True)
class DiffMirrorResult:
    """tree-to-tree ``git diff`` 结果（two-dot + ``--find-renames``）。"""

    base_sha: str
    head_sha: str
    unified_diff: str


def _scrub(text: str) -> str:
    """剥离错误输出中 URL 内嵌的凭证段。"""
    return _CREDENTIAL_URL_RE.sub("://***@", text)


def _lock_for(repository_id: str) -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    return _locks.setdefault((loop_id, str(repository_id)), asyncio.Lock())


def reset_mirror_state() -> None:
    """测试用：清空模块级缓存。"""
    _locks.clear()
    _fetch_cache.clear()
    _failure_cache.clear()


async def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
    max_output_bytes: int | None = None,
) -> tuple[int, bytes, bytes]:
    """执行子进程；可对 stdout 做字节上限截断（防全仓匹配撑爆内存）。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        if max_output_bytes is None:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, stdout, stderr
        assert proc.stdout is not None
        chunks: list[bytes] = []
        received = 0
        truncated = False
        deadline = time.monotonic() + timeout

        async def _read_all() -> None:
            nonlocal received, truncated
            while True:
                chunk = await proc.stdout.read(64 * 1024)  # type: ignore[union-attr]
                if not chunk:
                    return
                if received < max_output_bytes:
                    chunks.append(chunk)
                    received += len(chunk)
                if received >= max_output_bytes:
                    truncated = True
                    return

        await asyncio.wait_for(_read_all(), timeout=timeout)
        if truncated:
            proc.kill()
        stderr_bytes = b""
        if proc.stderr is not None:
            remaining = max(deadline - time.monotonic(), 1.0)
            try:
                stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=remaining)
            except asyncio.TimeoutError:
                stderr_bytes = b""
        await proc.wait()
        # 截断属于主动 kill，调用方按成功 + 截断处理
        returncode = 0 if truncated else (proc.returncode or 0)
        return returncode, b"".join(chunks), stderr_bytes
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise MirrorError("git_timeout", f"{cmd[0]} 命令超时（{int(timeout)}s）") from exc


async def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    proxy_url: str | None = None,
    timeout: float = _GIT_TIMEOUT_SECONDS,
    max_output_bytes: int | None = None,
) -> tuple[int, bytes, bytes]:
    from repositories.views import _build_git_env

    cmd: list[str] = ["git"]
    if proxy_url:
        cmd.extend(["-c", f"http.proxy={proxy_url}"])
    cmd.extend(args)
    return await _run_cmd(
        cmd,
        cwd=cwd,
        env=_build_git_env(proxy_url),
        timeout=timeout,
        max_output_bytes=max_output_bytes,
    )


async def _has_commit(repo_dir: Path, sha: str) -> bool:
    rc, _, _ = await _run_git(
        ["cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=repo_dir,
        timeout=15.0,
    )
    return rc == 0


@sync_to_async
def _fetch_repo_params(repository_id: str) -> dict[str, Any]:
    from repositories.models import Repository
    from services.git_credentials import resolve_git_token_sync

    repo = (
        Repository.objects.filter(id=repository_id, is_deleted=False).first()
    )
    if repo is None:
        raise MirrorError("repository_not_found", "仓库不存在")
    # 统一经凭证解析器取 token（Phase 26 REPO-01）：per-repo 优先，无则按 host
    # 命中实例凭证池。token 仍只进单次 fetch argv URL，绝不写镜像 git config。
    # 本函数已是 @sync_to_async 同步上下文，用同步入口。
    token: str | None = resolve_git_token_sync(repo)
    return {
        "git_url": repo.git_url,
        "proxy_url": repo.proxy_url,
        "token": token,
        "default_branch": repo.default_branch,
        "base_branch": repo.base_branch,
        "last_indexed_commit_sha": repo.last_indexed_commit_sha or "",
    }


def _local_ref_for(ref: str) -> str:
    return f"refs/friday/{ref}"


async def ensure_mirror_commit(
    repository_id: str,
    branch: str | None = None,
) -> MirrorSnapshot:
    """确保本地镜像里存在目标分支的快照 commit，返回快照信息。

    Raises:
        MirrorError: 镜像被禁用 / 分支名非法 / clone・fetch 失败。
    """
    if not getattr(settings, "REPO_MIRROR_ENABLED", True):
        raise MirrorError("mirror_disabled", "仓库本地镜像功能未启用")

    repository_id = str(repository_id)
    failure = _failure_cache.get(repository_id)
    if failure and (time.monotonic() - failure[1]) < _FAILURE_TTL_SECONDS:
        raise MirrorError("mirror_fetch_failed", failure[0])

    params = await _fetch_repo_params(repository_id)
    git_url = str(params["git_url"] or "")
    if not git_url:
        raise MirrorError("mirror_unavailable", "仓库缺少 git_url，无法建立本地镜像")

    base_ref = str(params["base_branch"] or params["default_branch"] or "")
    ref = str(branch or "").strip() or base_ref
    if not ref or not _SAFE_REF_RE.match(ref) or ".." in ref:
        raise MirrorError("invalid_params", f"非法分支名: {ref!r}")

    indexed_sha = str(params["last_indexed_commit_sha"] or "")
    pin_sha = indexed_sha if (ref == base_ref and _SHA_RE.match(indexed_sha)) else ""
    proxy_url = params["proxy_url"] or None

    async with _lock_for(repository_id):
        repo_dir = Path(settings.REPO_CLONE_DIR) / repository_id
        if not (repo_dir / "HEAD").exists():
            repo_dir.mkdir(parents=True, exist_ok=True)
            rc, _, stderr = await _run_git(
                ["init", "--bare", "--quiet", str(repo_dir)], timeout=30.0
            )
            if rc != 0:
                shutil.rmtree(repo_dir, ignore_errors=True)
                raise MirrorError(
                    "mirror_unavailable",
                    f"镜像目录初始化失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
                )

        # 1) 已 pin 的索引 commit 本地可用 → 零网络直接复用（与索引快照一致）
        if pin_sha and await _has_commit(repo_dir, pin_sha):
            return MirrorSnapshot(repository_id, repo_dir, pin_sha, ref, True)

        # 2) TTL 内的分支头缓存——有 pin_sha 时不得用漂移 tip 短路（D-01）。
        cached = _fetch_cache.get((repository_id, ref))
        if cached and (time.monotonic() - cached[1]) < _FETCH_TTL_SECONDS:
            if (not pin_sha or cached[0] == pin_sha) and await _has_commit(
                repo_dir, cached[0]
            ):
                return MirrorSnapshot(
                    repository_id, repo_dir, cached[0], ref, cached[0] == indexed_sha
                )

        from repositories.views import build_authenticated_git_url

        auth_url = build_authenticated_git_url(git_url, params["token"])
        fetch_base = ["fetch", "--depth", "1", "--quiet", auth_url]

        # 3) 优先按索引 sha fetch（GitHub/GitLab 普遍允许 reachable sha）
        if pin_sha:
            rc, _, _ = await _run_git(
                [*fetch_base, f"+{pin_sha}:{_local_ref_for(f'pin-{pin_sha[:12]}')}"],
                cwd=repo_dir,
                proxy_url=proxy_url,
            )
            if rc == 0 and await _has_commit(repo_dir, pin_sha):
                _fetch_cache[(repository_id, ref)] = (pin_sha, time.monotonic())
                return MirrorSnapshot(repository_id, repo_dir, pin_sha, ref, True)
            logger.info(
                "repo_mirror_sha_fetch_fallback",
                repository_id=repository_id,
                ref=ref,
            )

        # 4) 回退分支 HEAD
        rc, _, stderr = await _run_git(
            [*fetch_base, f"+refs/heads/{ref}:{_local_ref_for(ref)}"],
            cwd=repo_dir,
            proxy_url=proxy_url,
        )
        if rc != 0:
            detail = (
                f"镜像 fetch 失败（分支 {ref}）: {_scrub(stderr.decode(errors='replace'))[:300]}"
            )
            _failure_cache[repository_id] = (detail, time.monotonic())
            raise MirrorError("mirror_fetch_failed", detail)

        rc, out, _ = await _run_git(["rev-parse", _local_ref_for(ref)], cwd=repo_dir, timeout=15.0)
        sha = out.decode().strip()
        if rc != 0 or not _SHA_RE.match(sha):
            raise MirrorError("mirror_fetch_failed", f"无法解析分支 {ref} 的 commit")
        _failure_cache.pop(repository_id, None)
        _fetch_cache[(repository_id, ref)] = (sha, time.monotonic())
        return MirrorSnapshot(repository_id, repo_dir, sha, ref, sha == indexed_sha)


async def ensure_mirror_sha(
    repository_id: str,
    sha: str,
    *,
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> MirrorSnapshot:
    """按完整 40 位 sha pin 对象到本地 bare 镜像（⛔ 不经 ``refs/heads/{sha}``）。

    fetch 形态与 :func:`ensure_mirror_commit` 的索引 pin 同构：
    ``+{sha}:refs/friday/pin-{sha[:12]}``。
    """
    if not getattr(settings, "REPO_MIRROR_ENABLED", True):
        raise MirrorError("mirror_disabled", "仓库本地镜像功能未启用")

    repository_id = str(repository_id)
    sha = (sha or "").strip().lower()
    if not _SHA_RE.match(sha):
        raise MirrorError("invalid_params", f"非法 commit sha: {sha!r}")

    failure = _failure_cache.get(repository_id)
    if failure and (time.monotonic() - failure[1]) < _FAILURE_TTL_SECONDS:
        raise MirrorError("mirror_fetch_failed", failure[0])

    params = await _fetch_repo_params(repository_id)
    git_url = str(params["git_url"] or "")
    if not git_url:
        raise MirrorError("mirror_unavailable", "仓库缺少 git_url，无法建立本地镜像")

    indexed_sha = str(params["last_indexed_commit_sha"] or "").lower()
    proxy_url = params["proxy_url"] or None
    pin_ref = _local_ref_for(f"pin-{sha[:12]}")

    async with _lock_for(repository_id):
        repo_dir = Path(settings.REPO_CLONE_DIR) / repository_id
        if not (repo_dir / "HEAD").exists():
            repo_dir.mkdir(parents=True, exist_ok=True)
            rc, _, stderr = await _run_git(
                ["init", "--bare", "--quiet", str(repo_dir)], timeout=30.0
            )
            if rc != 0:
                shutil.rmtree(repo_dir, ignore_errors=True)
                raise MirrorError(
                    "mirror_unavailable",
                    f"镜像目录初始化失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
                )

        if await _has_commit(repo_dir, sha):
            return MirrorSnapshot(
                repository_id, repo_dir, sha, sha, sha == indexed_sha
            )

        from repositories.views import build_authenticated_git_url

        auth_url = build_authenticated_git_url(git_url, params["token"])
        rc, _, stderr = await _run_git(
            ["fetch", "--depth", "1", "--quiet", auth_url, f"+{sha}:{pin_ref}"],
            cwd=repo_dir,
            proxy_url=proxy_url,
            timeout=timeout,
        )
        if rc != 0 or not await _has_commit(repo_dir, sha):
            detail = (
                f"镜像 sha fetch 失败: {_scrub(stderr.decode(errors='replace'))[:300]}"
            )
            _failure_cache[repository_id] = (detail, time.monotonic())
            raise MirrorError("mirror_fetch_failed", detail)

        _failure_cache.pop(repository_id, None)
        _fetch_cache[(repository_id, sha)] = (sha, time.monotonic())
        return MirrorSnapshot(repository_id, repo_dir, sha, sha, sha == indexed_sha)


async def diff_mirror(
    base: MirrorSnapshot,
    head: MirrorSnapshot,
    *,
    timeout: float = 120.0,
) -> DiffMirrorResult:
    """对同一 bare 镜像做 tree-to-tree two-dot diff（``-U0 --find-renames``）。

    左端 sha 完全由调用方传入的 ``base.commit_sha`` 决定（D-01）；
    ⛔ 禁止三-dot ``A...B``（会把左端换成 merge-base）。
    """
    if base.repo_dir != head.repo_dir:
        raise MirrorError("invalid_params", "diff_mirror 要求同一 bare 镜像目录")
    if base.repository_id != head.repository_id:
        raise MirrorError("invalid_params", "diff_mirror 禁止跨仓")

    rc, out, stderr = await _run_git(
        [
            "diff",
            "--unified=0",
            "--find-renames",
            base.commit_sha,
            head.commit_sha,
        ],
        cwd=base.repo_dir,
        timeout=timeout,
        max_output_bytes=DETECT_CHANGES_MAX_DIFF_BYTES,
    )
    # _run_cmd 截断时强制 rc=0 并返回 ≥cap 字节；此处显式失败，禁止静默截断
    if len(out) >= DETECT_CHANGES_MAX_DIFF_BYTES:
        raise MirrorError(
            "diff_too_large",
            f"git diff 输出超过上限（{DETECT_CHANGES_MAX_DIFF_BYTES} bytes）",
        )
    if rc not in (0, 1):  # git diff: 1 = 有差异
        raise MirrorError(
            "mirror_fetch_failed",
            f"git diff 失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
        )
    return DiffMirrorResult(
        base_sha=base.commit_sha,
        head_sha=head.commit_sha,
        unified_diff=out.decode(errors="replace"),
    )


def _validate_pathspec(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned.startswith("-") or "\0" in cleaned or "\n" in cleaned:
        raise MirrorError("invalid_params", f"非法路径过滤: {value!r}")
    return cleaned


# 记录元组：(file_path, line, content, kind)，kind ∈ {"match", "context"}
GrepRecord = tuple[str, int, str, str]


def _rg_binary() -> str | None:
    """ripgrep 可执行文件路径；未安装或被开关关闭时返回 None。"""
    if not getattr(settings, "REPO_MIRROR_USE_RIPGREP", True):
        return None
    return shutil.which("rg")


def _worktree_root(repository_id: str) -> Path:
    return Path(settings.REPO_CLONE_DIR) / f"{repository_id}.worktrees"


async def _ensure_worktree(snapshot: MirrorSnapshot) -> Path:
    """确保快照 commit 有 checked-out worktree（ripgrep 只能搜真实文件）。

    每个仓库只保留当前快照一份 worktree；快照切换（重建索引）时旧的会被清掉。
    """
    root = _worktree_root(snapshot.repository_id)
    target = root / snapshot.commit_sha[:12]
    if (target / ".git").exists():
        return target
    async with _lock_for(f"worktree:{snapshot.repository_id}"):
        if (target / ".git").exists():
            return target
        root.mkdir(parents=True, exist_ok=True)
        for stale in root.iterdir():
            shutil.rmtree(stale, ignore_errors=True)
        await _run_git(["worktree", "prune"], cwd=snapshot.repo_dir, timeout=30.0)
        rc, _, stderr = await _run_git(
            ["worktree", "add", "--detach", "--force", str(target), snapshot.commit_sha],
            cwd=snapshot.repo_dir,
        )
        if rc != 0:
            shutil.rmtree(target, ignore_errors=True)
            raise MirrorError(
                "mirror_unavailable",
                f"worktree 创建失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
            )
        return target


async def ensure_worktree_for_scan(repository_id: str, commit_sha: str) -> Path:
    """公开 worktree API：确保 ``commit_sha`` 已 pin 到 mirror 并检出可扫描目录（D-02）。

    业务层（Semgrep 扫描等）应调用本函数，⛔ 不长期依赖私有 ``_ensure_worktree``。
    """
    snapshot = await ensure_mirror_sha(str(repository_id), commit_sha)
    return await _ensure_worktree(snapshot)


async def _ripgrep_records(
    rg_bin: str,
    worktree: Path,
    *,
    pattern: str,
    regex: bool,
    case_sensitive: bool,
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    context_lines: int,
) -> list[GrepRecord]:
    """ripgrep 引擎：在快照 worktree 上跑 ``rg --json``。

    --json 的事件流自带 match/context 类型与精确行号，单遍解析无歧义；
    --sort path 保证输出顺序确定（与 git grep 的 tree 序一致）。
    --no-ignore + --hidden 保证搜索范围 = 全部 checked-out（即 tracked）文件，
    与 git grep 语义对齐；.git 元数据文件显式排除。
    """
    args = [rg_bin, "--json", "--sort", "path", "--no-ignore", "--hidden", "-g", "!.git"]
    if not case_sensitive:
        args.append("-i")
    if not regex:
        args.append("-F")
    if context_lines > 0:
        args.extend(["-C", str(context_lines)])
    for glob in include_globs:
        args.extend(["-g", glob])
    for glob in exclude_globs:
        args.extend(["-g", f"!{glob}"])
    args.extend(["-e", pattern, "--"])
    # rg 在 stdin 非 tty 且无路径参数时会转去读 stdin，必须显式给搜索路径
    args.extend(paths or ["./"])

    rc, out, stderr = await _run_cmd(
        args,
        cwd=worktree,
        timeout=60.0,
        max_output_bytes=_MAX_GREP_OUTPUT_BYTES,
    )
    if rc not in (0, 1):  # 0=有命中 1=无命中
        raise MirrorError(
            "grep_failed",
            f"ripgrep 失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
        )
    records: list[GrepRecord] = []
    for raw_line in out.decode(errors="replace").splitlines():
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except ValueError:
            continue  # 字节截断产生的残行
        event_type = event.get("type")
        if event_type not in ("match", "context"):
            continue
        data = event.get("data") or {}
        file_path = str((data.get("path") or {}).get("text") or "")
        if not file_path:
            continue  # 非 UTF-8 路径（path.bytes），极罕见，跳过
        if file_path.startswith("./"):
            file_path = file_path[2:]
        content = str((data.get("lines") or {}).get("text") or "").rstrip("\n")
        records.append((file_path, int(data.get("line_number") or 0), content, event_type))
    return records


def _parse_git_grep_output(out: bytes, commit_sha: str) -> list[tuple[str, int, str]]:
    """解析 ``git grep -n -z`` 输出。

    ``-z`` 下命中行与上下文行格式相同：``<sha>:<path>\\0<lineno>\\0<content>``
    （hunk 分隔符 ``--`` 不含 NUL，直接跳过）。kind 区分由调用方通过
    「仅命中」的对照集合完成。
    """
    line_re = re.compile(r"^(\d+)\0(.*)$", re.DOTALL)
    prefix = f"{commit_sha}:"
    records: list[tuple[str, int, str]] = []
    for raw_line in out.decode(errors="replace").split("\n"):
        if "\0" not in raw_line:
            continue
        left, _, right = raw_line.partition("\0")
        file_path = left[len(prefix) :] if left.startswith(prefix) else left
        parsed = line_re.match(right)
        if parsed is None:
            continue
        records.append((file_path, int(parsed.group(1)), parsed.group(2)))
    return records


async def _git_grep_records(
    snapshot: MirrorSnapshot,
    *,
    pattern: str,
    regex: bool,
    case_sensitive: bool,
    paths: list[str],
    include_globs: list[str],
    exclude_globs: list[str],
    context_lines: int,
) -> list[GrepRecord]:
    """git grep 引擎：直接在 bare 镜像对象库上搜，无需 worktree。"""
    base_args = ["grep", "-n", "-I", "-z", "--no-color"]
    if not case_sensitive:
        base_args.append("-i")
    base_args.append("-E" if regex else "-F")
    tail_args = ["-e", pattern, snapshot.commit_sha, "--"]
    tail_args.extend(paths)
    tail_args.extend(f":(glob){glob}" for glob in include_globs)
    tail_args.extend(f":(glob,exclude){glob}" for glob in exclude_globs)

    async def _run_grep(extra: list[str]) -> list[tuple[str, int, str]] | None:
        rc, out, stderr = await _run_git(
            [*base_args, *extra, *tail_args],
            cwd=snapshot.repo_dir,
            timeout=60.0,
            max_output_bytes=_MAX_GREP_OUTPUT_BYTES,
        )
        if rc == 1:
            return None  # 无命中
        if rc != 0:
            raise MirrorError(
                "grep_failed",
                f"git grep 失败: {_scrub(stderr.decode(errors='replace'))[:300]}",
            )
        return _parse_git_grep_output(out, snapshot.commit_sha)

    # 第一遍：仅命中行 → 精确的命中集合；第二遍（需上下文时）：带 -C 的完整输出
    match_records = await _run_grep([])
    if match_records is None:
        return []
    match_set = {(path, line) for path, line, _ in match_records}
    if context_lines > 0:
        all_records = await _run_grep(["-C", str(context_lines)]) or []
    else:
        all_records = match_records
    return [
        (path, line, content, "match" if (path, line) in match_set else "context")
        for path, line, content in all_records
    ]


async def grep_mirror(
    snapshot: MirrorSnapshot,
    *,
    pattern: str,
    regex: bool = False,
    case_sensitive: bool = True,
    paths: list[str] | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    context_lines: int = 0,
    max_matches: int = 100,
) -> dict[str, Any]:
    """在镜像快照上执行精确检索，返回 matches / 统计 / 截断标记 / 引擎。

    引擎选择：rg 可用（已安装且未被 ``REPO_MIRROR_USE_RIPGREP=false`` 关闭）
    时优先 ripgrep，worktree 创建或 rg 执行失败则回退 git grep；两个引擎
    对同一快照给出相同结果。
    """
    safe_paths = [_validate_pathspec(p) for p in paths or []]
    safe_includes = [_validate_pathspec(g) for g in include_globs or []]
    safe_excludes = [_validate_pathspec(g) for g in exclude_globs or []]
    engine_kwargs: dict[str, Any] = {
        "pattern": pattern,
        "regex": regex,
        "case_sensitive": case_sensitive,
        "paths": safe_paths,
        "include_globs": safe_includes,
        "exclude_globs": safe_excludes,
        "context_lines": context_lines,
    }

    records: list[GrepRecord] | None = None
    engine = "git-grep"
    rg_bin = _rg_binary()
    if rg_bin is not None:
        try:
            worktree = await _ensure_worktree(snapshot)
            records = await _ripgrep_records(rg_bin, worktree, **engine_kwargs)
            engine = "ripgrep"
        except MirrorError as exc:
            logger.warning(
                "repo_mirror_ripgrep_fallback_git_grep",
                repository_id=snapshot.repository_id,
                code=exc.code,
                detail=exc.detail,
            )
            records = None
    if records is None:
        records = await _git_grep_records(snapshot, **engine_kwargs)
        engine = "git-grep"

    return {**_aggregate_records(records, max_matches), "engine": engine}


def _aggregate_records(records: list[GrepRecord], max_matches: int) -> dict[str, Any]:
    """把引擎输出的记录流聚合成工具返回结构（含逐文件计数）。"""
    total_match_lines = 0
    file_counts: dict[str, int] = {}
    for file_path, _, _, kind in records:
        if kind == "match":
            total_match_lines += 1
            file_counts[file_path] = file_counts.get(file_path, 0) + 1

    matches: list[dict[str, Any]] = []
    match_count = 0
    truncated = False
    for file_path, line, content, kind in records:
        if kind == "match":
            if match_count >= max_matches:
                truncated = True
                break
            match_count += 1
        matches.append(
            {
                "file_path": file_path,
                "line": line,
                "kind": kind,
                "content": content[:_MAX_LINE_CHARS],
            }
        )
    return {
        "matches": matches,
        "total_matches": total_match_lines,
        "files_with_matches": len(file_counts),
        "file_counts": [
            {"file_path": path, "match_count": count} for path, count in sorted(file_counts.items())
        ],
        "truncated": truncated or total_match_lines > max_matches,
    }


async def read_mirror_file(snapshot: MirrorSnapshot, file_path: str) -> str | None:
    """读取快照中单个文件的完整内容；不存在返回 None。"""
    cleaned = _validate_pathspec(file_path)
    rc, out, _ = await _run_git(
        ["show", f"{snapshot.commit_sha}:{cleaned}"],
        cwd=snapshot.repo_dir,
        timeout=30.0,
        max_output_bytes=_MAX_FILE_OUTPUT_BYTES,
    )
    if rc != 0:
        return None
    return out.decode(errors="replace")


async def list_mirror_paths(snapshot: MirrorSnapshot) -> list[str]:
    """列出快照中全部文件路径（用于后缀模糊解析）。"""
    rc, out, _ = await _run_git(
        ["ls-tree", "-r", "--name-only", "-z", snapshot.commit_sha],
        cwd=snapshot.repo_dir,
        timeout=30.0,
        max_output_bytes=_MAX_FILE_OUTPUT_BYTES,
    )
    if rc != 0:
        return []
    return [p for p in out.decode(errors="replace").split("\0") if p]
