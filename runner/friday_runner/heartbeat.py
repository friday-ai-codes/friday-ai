"""心跳资源指标采集。"""
import psutil
def collect_metrics(current_tasks: int, max_concurrent: int, accepting: bool = True) -> dict:
 """采集 CPU / 内存 / 磁盘使用率及任务数。"""
 return {
 "cpu_percent": psutil.cpu_percent(interval=None),
 "memory_percent": psutil.virtual_memory.percent,
 "disk_percent": psutil.disk_usage("/").percent,
 "current_tasks": current_tasks,
 "max_concurrent": max_concurrent,
 "accepting": accepting,
 }
def warmup -> None:
 """预热 psutil（首次 cpu_percent 调用返回 0.0）。"""
 psutil.cpu_percent
