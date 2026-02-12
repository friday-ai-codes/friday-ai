"""服务器资源监控模块（Phase）。
提供：
- 动态计算最大并发容器数
- 实时资源使用率检查
- 资源可用性判断
用户决策：
- 资源阈值：CPU 80% / 内存 80% 时暂停新任务启动
- 动态并发：基于服务器资源自动计算，非固定值
"""
import os
from dataclasses import dataclass
from typing import NamedTuple
import psutil
import structlog
logger = structlog.get_logger(__name__)
# === 配置常量 ===
# 资源阈值（用户决策：CPU 80% / 内存 80%）
CPU_THRESHOLD_PERCENT = 80
MEMORY_THRESHOLD_PERCENT = 80
# 每容器资源估算
MEMORY_PER_CONTAINER_GB = 2.0 # 与 ContainerConfig.mem_limit 对应
# 并发硬上限（避免资源耗尽）
MAX_CONCURRENCY_LIMIT = 8
class ResourceMetrics(NamedTuple):
 """资源使用指标。"""
 cpu_percent: float
 memory_percent: float
 memory_available_gb: float
 cpu_count: int
@dataclass
class ResourceAvailability:
 """资源可用性检查结果。"""
 can_start: bool
 reason: str
 metrics: ResourceMetrics
 max_concurrency: int
 current_running: int
def get_resource_metrics -> ResourceMetrics:
 """获取当前资源使用指标。
 Returns:
 ResourceMetrics 包含 CPU 使用率、内存使用率、可用内存、CPU 核心数
 """
 # CPU 使用率（0.1s 采样间隔）
 cpu_percent = psutil.cpu_percent(interval=0.1)
 # 内存信息
 mem = psutil.virtual_memory
 memory_percent = mem.percent
 memory_available_gb = mem.available / (1024**3)
 # CPU 核心数
 cpu_count = os.cpu_count or 4
 return ResourceMetrics(
 cpu_percent=cpu_percent,
 memory_percent=memory_percent,
 memory_available_gb=memory_available_gb,
 cpu_count=cpu_count,
 )
def calculate_max_concurrency -> int:
 """基于服务器资源计算最大并发容器数。
 公式：min(CPU 核心数 - 1, 可用内存GB / 2, 上限 8)
 - 每容器默认限制 2GB 内存（见 ContainerConfig.mem_limit）
 - 保留 1 个核心给系统进程
 - 硬上限 8 避免资源耗尽
 Returns:
 最大并发容器数（至少为 1）
 """
 metrics = get_resource_metrics
 # 基于 CPU 核心数（保留 1 核给系统）
 cpu_based = max(1, metrics.cpu_count - 1)
 # 基于总内存（每容器 2GB）
 total_mem_gb = psutil.virtual_memory.total / (1024**3)
 mem_based = max(1, int(total_mem_gb / MEMORY_PER_CONTAINER_GB))
 # 取最小值，并应用硬上限
 max_concurrency = min(cpu_based, mem_based, MAX_CONCURRENCY_LIMIT)
 logger.debug(
 "max_concurrency_calculated",
 cpu_count=metrics.cpu_count,
 total_mem_gb=round(total_mem_gb, 1),
 cpu_based=cpu_based,
 mem_based=mem_based,
 result=max_concurrency,
 )
 return max_concurrency
async def check_resource_availability(current_running: int = 0) -> ResourceAvailability:
 """检查当前资源是否允许启动新容器。
 检查条件：
 1. CPU 使用率 < 80%
 2. 内存使用率 < 80%
 3. 当前运行数 < 最大并发数
 Args:
 current_running: 当前正在运行的容器数
 Returns:
 ResourceAvailability 包含是否可启动、原因、指标
 """
 metrics = get_resource_metrics
 max_concurrency = calculate_max_concurrency
 # 检查 CPU 阈值
 if metrics.cpu_percent >= CPU_THRESHOLD_PERCENT:
 return ResourceAvailability(
 can_start=False,
 reason=f"CPU 使用率过高 ({metrics.cpu_percent:.1f}% >= {CPU_THRESHOLD_PERCENT}%)",
 metrics=metrics,
 max_concurrency=max_concurrency,
 current_running=current_running,
 )
 # 检查内存阈值
 if metrics.memory_percent >= MEMORY_THRESHOLD_PERCENT:
 return ResourceAvailability(
 can_start=False,
 reason=f"内存使用率过高 ({metrics.memory_percent:.1f}% >= {MEMORY_THRESHOLD_PERCENT}%)",
 metrics=metrics,
 max_concurrency=max_concurrency,
 current_running=current_running,
 )
 # 检查并发数
 if current_running >= max_concurrency:
 return ResourceAvailability(
 can_start=False,
 reason=f"已达最大并发数 ({current_running}/{max_concurrency})",
 metrics=metrics,
 max_concurrency=max_concurrency,
 current_running=current_running,
 )
 return ResourceAvailability(
 can_start=True,
 reason="资源充足",
 metrics=metrics,
 max_concurrency=max_concurrency,
 current_running=current_running,
 )
def get_running_container_count -> int:
 """获取当前正在运行的 Friday 容器数。
 通过数据库查询 status=RUNNING 的 SubAgentSession 数量。
 Returns:
 正在运行的容器数
 """
 from subagent.models import SubAgentSession
 return SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 ).count
async def get_running_container_count_async -> int:
 """获取当前正在运行的 Friday 容器数（异步版本）。"""
 from subagent.models import SubAgentSession
 return await SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 ).acount
