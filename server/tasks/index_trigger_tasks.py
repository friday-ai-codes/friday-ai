"""索引自动触发任务（Phase）。
包含：
- Webhook push 事件处理
- APScheduler 定时轮询
- 防抖去重缓存
"""
import asyncio
import hashlib
import hmac
import time
import structlog
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 IndexStatus,
 Repository,
 TriggerType,
)
from services.indexer import clone_and_index_repository
logger = structlog.get_logger(__name__)
# ---------------------------------------------------------------------------
# 防抖去重缓存
# ---------------------------------------------------------------------------
# {commit_sha: timestamp} — 10 分钟内存窗口
_dedup_cache: dict[str, float] = {}
_DEDUP_WINDOW_SECONDS = 600 # 10 分钟
def _is_duplicate(commit_sha: str) -> bool:
 """检查 commit SHA 是否在去重窗口内。"""
 now = time.monotonic
 # 清理过期条目
 expired = [k for k, v in _dedup_cache.items if now - v > _DEDUP_WINDOW_SECONDS]
 for k in expired:
 del _dedup_cache[k]
 # 检查是否重复
 if commit_sha in _dedup_cache:
 return True
 _dedup_cache[commit_sha] = now
 return False
def clear_dedup_cache -> None:
 """清空去重缓存（用于测试）。"""
 _dedup_cache.clear
# ---------------------------------------------------------------------------
# Webhook 签名验证
# ---------------------------------------------------------------------------
def verify_webhook_signature(payload: bytes, secret: str, signature: str) -> bool:
 """验证 work item 签名（兼容 GitHub/Gitea 格式）。"""
 expected = hmac.new(secret.encode, payload, hashlib.sha256).hexdigest
 # GitHub 格式: sha256=<hex>
 if signature.startswith("sha256="):
 signature = signature[7:]
 return hmac.compare_digest(expected, signature)
def verify_gitlab_token(secret: str, token: str) -> bool:
 """验证 GitLab X-Gitlab-Token。"""
 return hmac.compare_digest(secret, token)
# ---------------------------------------------------------------------------
# 解析 push 事件 payload
# ---------------------------------------------------------------------------
def parse_push_event(platform: str, payload: dict) -> dict[str, str]:
 """从不同平台的 push 事件中提取关键信息。
 返回: {"ref": str, "after": str(head commit sha)}
 """
 if platform == "github":
 return {
 "ref": payload.get("ref", ""),
 "after": payload.get("after", ""),
 }
 elif platform == "gitlab":
 return {
 "ref": payload.get("ref", ""),
 "after": payload.get("after", payload.get("checkout_sha", "")),
 }
 elif platform == "gitea":
 return {
 "ref": payload.get("ref", ""),
 "after": payload.get("after", ""),
 }
 return {"ref": "", "after": ""}
# ---------------------------------------------------------------------------
# 触发索引（共用逻辑）
# ---------------------------------------------------------------------------
# 模块级强引用集合：防止 asyncio.create_task 被 GC 回收
_auto_index_tasks: set[asyncio.Task] = set # type: ignore[type-arg]
async def trigger_auto_index(
 repository: Repository, trigger_type: str, commit_sha: str = ""
) -> dict[str, str]:
 """触发自动索引（webhook 或定时轮询共用）。
 返回: {"status": "triggered"/"skipped"/"duplicate", ...}
 """
 repo_id = str(repository.id)
 #: 检查开关
 if not repository.auto_index_enabled:
 return {"status": "skipped", "reason": "auto_index_disabled"}
 # 正在索引中则跳过
 if repository.index_status == IndexStatus.INDEXING:
 return {"status": "skipped", "reason": "already_indexing"}
 #: 防抖去重
 if commit_sha and _is_duplicate(commit_sha):
 return {"status": "duplicate", "sha": commit_sha}
 # 创建 IndexHistory 记录
 tt = TriggerType.WEBHOOK if trigger_type == "webhook" else TriggerType.SCHEDULED
 from django.utils import timezone
 history = await IndexHistory.objects.acreate(
 repository_id=repo_id,
 trigger_type=tt,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 # 启动后台任务
 task: asyncio.Task = asyncio.create_task( # type: ignore[type-arg]
 clone_and_index_repository(repo_id, history_id=str(history.id)),
 name=f"auto-index-{repo_id}",
 )
 _auto_index_tasks.add(task)
 task.add_done_callback(_auto_index_tasks.discard)
 logger.info(
 "auto_index_triggered",
 repository_id=repo_id,
 trigger_type=trigger_type,
 commit_sha=commit_sha,
 history_id=str(history.id),
 )
 return {
 "status": "triggered",
 "history_id": str(history.id),
 "trigger_type": trigger_type,
 }
# ---------------------------------------------------------------------------
# 定时轮询任务
# ---------------------------------------------------------------------------
async def poll_repository_updates -> dict[str, int]:
 """轮询所有启用自动索引的仓库，检查远端 HEAD 是否变化。"""
 repositories = [
 repo
 async for repo in Repository.objects.filter(
 auto_index_enabled=True, is_deleted=False
 )
 ]
 checked = 0
 triggered = 0
 for repo in repositories:
 checked += 1
 if not repo.git_url or not repo.last_indexed_commit_sha:
 continue
 try:
 remote_sha = await _get_remote_head_sha(repo.git_url)
 if remote_sha and remote_sha != repo.last_indexed_commit_sha:
 result = await trigger_auto_index(repo, "scheduled", remote_sha)
 if result["status"] == "triggered":
 triggered += 1
 except Exception:
 logger.exception(
 "poll_check_failed",
 repository_id=str(repo.id),
 git_url=repo.git_url,
 )
 logger.info("poll_complete", checked=checked, triggered=triggered)
 return {"checked": checked, "triggered": triggered}
async def _get_remote_head_sha(git_url: str) -> str:
 """通过 git ls-remote 获取远端 HEAD SHA。"""
 proc = await asyncio.create_subprocess_exec(
 "git", "ls-remote", git_url, "HEAD",
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=15.0)
 if proc.returncode != 0:
 return ""
 output = stdout.decode.strip
 if output:
 return output.split[0]
 return ""
