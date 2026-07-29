"""process_runtime 的**零依赖**共享常量。

存在的理由只有一个：让两个互不依赖的模块共用同一个数值，而**不必**为此互相 import。
``builtin_processes``（process 注册）此前为拿到重路由轮次上界，在模块中段 import 了
``blueprint_research_adapter``（连带 ``delivery.services`` / ``delivery.models``），把重型
依赖拉进 process 注册的 import 期——那是循环 import 的潜在触发点。

**本模块不得 import 任何项目内模块**（保持可被任何层安全 import）。
"""

from __future__ import annotations

__all__ = ["MAX_REROUTE_ROUNDS"]

# 蓝图重路由轮次上界（CONTEXT：「reroute 上界 ≤2 轮」）。达到上界仍有 unsuitable 仓时
# **升确认门交人裁决**，绝不落 session 失败 —— CONTEXT「绝不静默失败」。
MAX_REROUTE_ROUNDS = 2
