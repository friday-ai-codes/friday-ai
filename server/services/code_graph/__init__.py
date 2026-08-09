"""内存符号图服务包的**唯一对外面**（Phase 121 交付的 v0.22.0 图分析地基）。

用什么
======
取图走 :func:`get_graph_service` → :meth:`~services.code_graph.cache.GraphService.get_graph`；
重索引 / 重建边之后主动驱逐本 worker 旧图走 :func:`invalidate_repository`。其余 14 项
是数据契约（``CodeGraph`` / ``GraphMeta`` / ``ChunkEvidence``、四档边语义、五个异常
类型、两个阈值常量），供上层工具做类型标注、置信度解释与异常分支。

架构红线（本文件就是这条红线的机械防线）
========================================
所有图访问**必须**经 ``GraphService.get_graph()``。``loader`` / ``cache`` /
``signature`` / ``access`` 四个子模块**一律不对外导出**——上层工具直连 ``loader``
视为**架构违规**，在 plan-checker 与 code-review 中列为红线（121-CONTEXT Area 4）。

理由不是洁癖：``get_graph`` 是**权限校验**（``access.ensure_repository_readable``）、
**exclusion 过滤**（fail-closed 的 matcher 收口）与**水位一致性校验**（签名复校 +
边构建在途闸门）这三道闸的唯一收口点，绕过它等于同时绕过三道——被排除的 ``.env`` /
``*.pem`` / ``id_rsa`` 符号名会漏进每一个上层工具的输出，陈旧或半新的图会被读成
「影响面就这么大」。不导出把「绕过校验」从**需要自律**降级为**需要刻意书写内部模块
路径**（ASVS V1）。

⚠️ 光靠不导出**挡不住**这件事：``__all__`` 只影响 ``from … import *``，
``from services.code_graph.loader import load_graph`` 一直都能正常工作。真正的机械
防线是 ``tests/services/code_graph/test_access.py::test_no_upper_layer_imports_internal_submodules``
——它 AST 扫全仓，包外任何一处直连 ``loader`` / ``cache`` / ``signature`` / ``access``
都会让 CI 红。本文件负责收敛公开面，那条用例负责让越界当场暴露，两者缺一不可。

不导出什么
==========
``estimate_graph_bytes`` / ``NODE_COST_BYTES`` / ``EDGE_COST_BYTES``（存储层记账细节）、
``invalidate_matcher_fingerprint_cache``（``access`` 内部 memo 的失效面，已由
:func:`invalidate_repository` 联动）、``BARE_NAME_BLACKLIST``（裸名过滤的内部细节）、
以及一切私有 helper。需要它们的**只可能**是本包内部的模块。
"""

from __future__ import annotations

from services.code_graph.cache import (
    GraphService,
    get_graph_service,
    invalidate_repository,
)
from services.code_graph.model import (
    LOW_RESOLUTION_THRESHOLD,
    REDACTED_REPOSITORY,
    ChunkEvidence,
    CodeGraph,
    EdgeConfidence,
    EdgeKind,
    GraphAccessDenied,
    GraphBuildFailed,
    GraphBuildTimeout,
    GraphError,
    GraphMeta,
    GraphNotIndexed,
    confidence_score,
    derive_reason,
)

__all__ = [
    "ChunkEvidence",
    "CodeGraph",
    "EdgeConfidence",
    "EdgeKind",
    "GraphAccessDenied",
    "GraphBuildFailed",
    "GraphBuildTimeout",
    "GraphError",
    "GraphMeta",
    "GraphNotIndexed",
    "GraphService",
    "LOW_RESOLUTION_THRESHOLD",
    "REDACTED_REPOSITORY",
    "confidence_score",
    "derive_reason",
    "get_graph_service",
    "invalidate_repository",
]
