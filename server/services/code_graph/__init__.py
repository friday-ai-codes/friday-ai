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

红线管到哪、管不到哪（Phase 122 的边界裁决，D-28）
==================================================
``impact`` / ``trace`` / ``symbol_resolve`` 三个**新内核**与 ``model`` 同属契约/算法层，
**刻意不进本 barrel，也不进** ``test_access.py`` 的 ``_INTERNAL_SUBMODULES``。壳层写
``import services.code_graph.impact`` 取用其中的分析函数是**合法的**，不构成架构违规。

理由：红线守的是「绕过 ``GraphService.get_graph()`` 的权限 / exclusion / 水位这三道闸」，
而这三个内核**自己就是经 ``get_graph`` 拿到图之后的纯消费者**——它们只吃
``MultiDiGraph`` 与参数，没有任何一条通往数据库的路，绕不动任何一道闸。把它们也锁进
barrel，只会逼壳层写一层毫无信息量的转发。

⚠️ **「内核可以直连」不等于「图可以直连」**。取图仍然**必须**经
:func:`get_graph_service` → ``get_graph()``，那才是 D-02 的实质。内核拿到的图是三道闸
的产物，谁把图递给它们、那张图怎么来的，红线一寸没松。

包内 vs 包外兄弟模块
--------------------
本相位新增的文件分两处落地，判据只有一条——**是否碰 ORM**：

- 包**内**（``impact`` / ``trace`` / ``symbol_resolve``）：零 ORM、零 Django，纯函数吃
  图。D-01 的分层要求本包内只有 ``loader`` 持有 ORM，它们进得来。
- 包**外兄弟模块**（``services/code_graph_tools.py`` / ``services/code_graph_cross_repo.py``）：
  必须直查 ``Symbol`` / ``Repository`` / ``CrossRepoApiCall``（``signature`` 补取、跨仓
  一跳），放进包内即破 D-01，所以它们只能待在包外。

⚠️ **「在包外」不等于「不受观测契约管」**：122-05 会把
``test_observability_contract`` 的**扫描面**显式扩展到这两个兄弟文件——同样的
``component="code_graph"``、同样的 ``code_graph_`` 事件名前缀、同样的静态可解析事件名与
``error=`` 脱敏，判据一条都不放松；唯一放宽的是 ``category`` 可取 ``sampling`` /
``caller`` 之一，因为壳层要发调用类事件。

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
from services.code_graph.query_service import (
    GRAPH_QUERY_RANKING_VERSION,
    GRAPH_QUERY_RESPONSE_VERSION,
    GraphQueryService,
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
    "GraphQueryService",
    "GraphService",
    "GRAPH_QUERY_RANKING_VERSION",
    "GRAPH_QUERY_RESPONSE_VERSION",
    "LOW_RESOLUTION_THRESHOLD",
    "REDACTED_REPOSITORY",
    "confidence_score",
    "derive_reason",
    "get_graph_service",
    "invalidate_repository",
]
