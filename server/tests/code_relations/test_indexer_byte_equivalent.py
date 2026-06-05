"""initial implementation plan success criterion byte-equivalent white-box 断言。

`_extract_and_write_graph` 是 initial implementation 引入、initial implementation 退化为薄壳的图谱抽取
入口。plan 在 4 处 callsite 外层包裹 ``GraphBuildHistory`` 创建/转态，
**关键约束**是不能侵入薄壳内部循环 —— 否则违反 success criterion byte-equivalent。

本测试以 ``inspect`` 内省方式锁定薄壳形态：

1. 仍是 ``IndexerService`` 类方法（不抽出 module-level）
2. 签名稳定（self / repo_path / file_paths / repository_id，return dict）
3. 函数体仍读 ``settings.ENABLE_CODEGRAPH``（initial implementation 既有短路保留）
4. 4 处 callsite 调用形态不变（``await self._extract_and_write_graph(...)``）
5. 没有同名 module-level 函数（防御性 grep）
6. 薄壳函数体内不含 ``GraphBuildHistory`` —— history 生命周期全部由
   callsite 外层管理（薄壳纯净 / 关注点分离 / 测试无侵入）
7. ``dual_track_integration`` / initial implementation 既有套件 regression hook
   —— 实际跑由 security mitigation-4 + security mitigation-6 跨套件验证（``tests/code_relations/``
   全量），本文件仅做白盒结构断言。
"""

from __future__ import annotations

import inspect
import re
from typing import get_type_hints

from services.indexer import IndexerService

# ---------------------------------------------------------------------------
# 1. 薄壳函数仍在 IndexerService 类内
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_is_indexer_service_method() -> None:
    """``_extract_and_write_graph`` 必须是 ``IndexerService`` 的 async 方法。"""
    assert hasattr(IndexerService, "_extract_and_write_graph"), (
        "IndexerService 缺少 _extract_and_write_graph —— "
        "success criterion byte-equivalent 关键不变量被破坏（薄壳被抽出或重命名）"
    )
    method = IndexerService._extract_and_write_graph
    assert inspect.iscoroutinefunction(method), (
        "_extract_and_write_graph 必须是 async 方法（async def）"
    )


# ---------------------------------------------------------------------------
# 2. 签名稳定（3 形参 + return dict[str, Any]）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_signature_stable() -> None:
    """形参与 return 类型签名稳定 —— 任何变更会立刻引发本测试 FAIL。"""
    method = IndexerService._extract_and_write_graph
    sig = inspect.signature(method)
    param_names = set(sig.parameters.keys())

    required = {"self", "repo_path", "file_paths", "repository_id"}
    assert required.issubset(param_names), (
        f"_extract_and_write_graph 形参缺失 {required - param_names}（"
        f"当前: {param_names}）—— success criterion byte-equivalent 不变量被破坏"
    )

    # return 类型注解：dict[str, Any]
    hints = get_type_hints(method)
    return_hint = hints.get("return")
    assert return_hint is not None, "_extract_and_write_graph 缺少 return 类型注解"
    assert return_hint is dict or "dict" in str(return_hint), (
        f"_extract_and_write_graph 返回类型应是 dict[str, Any]，当前 {return_hint}"
    )


# ---------------------------------------------------------------------------
# 3. 薄壳函数体内仍读 settings.ENABLE_CODEGRAPH（initial implementation 既有短路保留）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_still_reads_global_flag() -> None:
    """initial implementation line 2080 等价短路 ``getattr(settings, "ENABLE_CODEGRAPH", False)``
    必须保留在薄壳函数体内 —— 删除会破坏 success criterion。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    # 兼容 quote 风格：双引号或单引号
    pattern = re.compile(
        r"getattr\(\s*settings\s*,\s*['\"]ENABLE_CODEGRAPH['\"]\s*,\s*False\s*\)"
    )
    assert pattern.search(src), (
        "_extract_and_write_graph 函数体内未发现 "
        "`getattr(settings, \"ENABLE_CODEGRAPH\", False)` 等价模式 —— "
        "initial implementation 既有短路丢失，success criterion byte-equivalent 不变量被破坏"
    )


# ---------------------------------------------------------------------------
# 4. 4 处 callsite 调用形态不变（仍是 await self._extract_and_write_graph(...)）
# ---------------------------------------------------------------------------


def test_four_callsites_use_self_extract_form() -> None:
    """4 处 callsite 必须仍以 ``await self._extract_and_write_graph(...)`` 形态
    调用 —— 不允许变为 module-level 函数 / GraphBuilder 包装等其他形态。
    """
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    matches = re.findall(r"await self\._extract_and_write_graph\(", src)
    assert len(matches) >= 4, (
        f"`await self._extract_and_write_graph(` 调用形态应 ≥ 4 处，"
        f"实际 {len(matches)} 处 —— 4 处既有 callsite 至少存在"
    )


# ---------------------------------------------------------------------------
# 5. 没有同名 module-level 函数（防御性 grep）
# ---------------------------------------------------------------------------


def test_no_module_level_extract_function() -> None:
    """禁止抽出 module-level ``async def _extract_and_write_graph`` ——
    薄壳必须保留在 ``IndexerService`` 类内。
    """
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    # 行首 async def _extract_and_write_graph（无前导空白 = module-level）
    pattern = re.compile(r"^async def _extract_and_write_graph", re.MULTILINE)
    matches = pattern.findall(src)
    assert len(matches) == 0, (
        f"发现 {len(matches)} 处 module-level async def _extract_and_write_graph"
        f" —— 薄壳必须仅以类方法形态存在"
    )


# ---------------------------------------------------------------------------
# 6. 薄壳函数体内不含 GraphBuildHistory（关注点分离 / 不侵入循环）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_does_not_touch_graph_build_history() -> None:
    """薄壳必须保持纯净 —— ``GraphBuildHistory`` 创建/转态全部由 callsite
    外层管理（CONTEXT Area 2 Q4 决议）。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    assert "GraphBuildHistory" not in src, (
        "_extract_and_write_graph 函数体内含 GraphBuildHistory —— "
        "违反薄壳纯净不变量；history 生命周期应在 4 处 callsite 外层管理"
    )


# ---------------------------------------------------------------------------
# 7. 薄壳函数体内不含 GraphBuildHistoryTrigger / Status（防误用）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_does_not_touch_trigger_or_status() -> None:
    """薄壳函数体内不应感知 trigger / status 枚举 —— 任何 history 状态机
    转移都应在 callsite 外层完成。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    for forbidden in (
        "GraphBuildHistoryTrigger",
        "GraphBuildHistoryStatus",
        "AUTO_AFTER_INDEX",
    ):
        assert forbidden not in src, (
            f"_extract_and_write_graph 函数体内含 {forbidden} —— "
            f"薄壳纯净不变量被破坏"
        )


# ---------------------------------------------------------------------------
# 8. 薄壳函数体内仍存在核心抽取动作的关键字（防误删导致空壳）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_still_has_core_extraction_tokens() -> None:
    """薄壳函数体内必须保留核心抽取动作的关键 token —— 防止误删导致
    实际不再抽取。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    required_tokens = [
        "_init_graph_services",  # 延迟初始化图谱服务
        "files_processed",  # 计数字段（与 stats dict key 对齐）
        "files_failed",
        "total_symbols",
        "total_imports",
        "total_calls",
        "total_endpoints",
    ]
    missing = [t for t in required_tokens if t not in src]
    assert not missing, (
        f"_extract_and_write_graph 缺失核心 token：{missing} —— "
        f"薄壳被破坏，success criterion byte-equivalent 不变量丢失"
    )


# ---------------------------------------------------------------------------
# 9. dual_track_integration regression hook（占位）
# ---------------------------------------------------------------------------


def test_dual_track_regression_hook_documented() -> None:
    """initial implementation 落地的 ``test_dual_track_integration.py`` 文件在当前
    HEAD 不存在（推测合并/重构期间被并入其他套件）—— 本 plan 通过执行
    ``tests/code_relations/`` 全量套件等价验证 byte-equivalent，
    避免对缺失文件的硬依赖。

    本测试仅做记录性占位（无运行时副作用），实际 byte-equivalent 回归由
    security mitigation-6 的全量 ``pytest tests/code_relations/`` 执行保证。
    """
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    # 防御性 assertion：确保 initial implementation baseline 标识仍在
    # （如果未来薄壳被深度重构，此 anchor 触发预警）
    assert "initial implementation" in src.lower() or "initial implementation" in src.lower(), (
        "indexer.py 中未见 initial implementation/278 锚点 —— 薄壳上下文可能已大幅漂移"
    )


# ---------------------------------------------------------------------------
# 10. 兜底抽取分支必须与 single-parse 缓存来源共用 get_extractor（两条路径一致）
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_uses_get_extractor_not_codeparser() -> None:
    """图谱兜底分支必须走 ``get_extractor(language).extract`` —— 与"创建索引"的
    single-parse 缓存来源（``unified_extraction``）完全同一抽取入口。

    历史 bug：兜底分支曾用 ``CodeParser._get_tree_sitter_parser`` +
    ``GraphExtractor.extract_all``，而 ``CodeParser`` 对 ``typescript`` 硬接
    JavaScript grammar（``"typescript": tree_sitter_javascript``），无法识别
    interface/type/enum，导致"手动重建图谱"路径抽出的符号数远低于"创建索引"
    路径（实测 60 个 TS 文件 400 → 98，整库 5608 → 2069）。两条路径必须共用
    get_extractor，否则符号数永远对不齐。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    assert "get_extractor(" in src, (
        "兜底分支未使用 get_extractor —— 必须与 unified_extraction 共用抽取入口，"
        "否则创建索引与手动重建的符号数会不一致"
    )
    assert "_get_tree_sitter_parser" not in src, (
        "兜底分支不得使用 CodeParser._get_tree_sitter_parser："
        "它对 typescript 用 JavaScript grammar，会与创建索引路径符号数不一致"
    )
    assert "extract_all(" not in src, (
        "兜底分支不得使用 GraphExtractor.extract_all —— "
        "改用 get_extractor(language).extract 与创建索引路径保持一致"
    )


# ---------------------------------------------------------------------------
# 11. 仅 backend 注册的语言（volar 注入的 javascript/jsx）必须有 TreeSitterExtractor 兜底
# ---------------------------------------------------------------------------


def test_extract_and_write_graph_has_treesitter_fallback_for_backend_only_langs() -> None:
    """EXTRACTOR_REGISTRY 未注册、但运行时经 volar ``register_backend`` 注入
    BACKEND_REGISTRY 的语言（javascript / jsx）必须有通用 TreeSitterExtractor
    兜底。

    回归点：上轮把兜底从 ``extract_all``（走 get_backend）改成 get_extractor
    后，javascript 因 EXTRACTOR_REGISTRY 未注册 → get_extractor 返回 None →
    文件被整体跳过，符号丢失（5608 → 5422）+ 每文件刷 ``extractor_not_found``
    warning。必须保留 TreeSitterExtractor 兜底覆盖这些语言。
    """
    src = inspect.getsource(IndexerService._extract_and_write_graph)
    assert "TreeSitterExtractor" in src, (
        "兜底分支缺少 TreeSitterExtractor fallback —— EXTRACTOR_REGISTRY 未注册的 "
        "backend 语言（javascript/jsx）会被跳过丢符号 + 刷 extractor_not_found"
    )
    assert "EXTRACTOR_REGISTRY" in src, (
        "兜底分支应判断 language 是否在 EXTRACTOR_REGISTRY，以决定走 get_extractor "
        "还是 TreeSitterExtractor fallback"
    )
