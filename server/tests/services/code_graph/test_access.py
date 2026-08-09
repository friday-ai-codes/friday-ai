"""``services/code_graph/access.py`` 的 fail-closed 收口用例（覆盖 GRAPH-04）。

本文件由 **Plan 121-03**（可读性闸门、matcher fail-closed、指纹 memo、观测契约
守护）落地主体，剩余两个桩由 **Plan 121-05**（exclusion 过滤节点连带邻接边）与
**Plan 121-09**（barrel 导出红线）填充。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from unittest import mock

import pytest

import services.code_graph as code_graph_package
from services.code_graph.access import (
    _MATCHER_FP_TTL_SECONDS,
    _check_user_acl,
    build_matcher_and_fingerprint,
    ensure_repository_readable,
    invalidate_matcher_fingerprint_cache,
    make_path_exclusion_memo,
)
from services.code_graph.model import GraphAccessDenied, GraphNotIndexed

# ── 121-05-T2：装配阶段 exclusion 过滤（GRAPH-04 的真正落点） ────────────────


def _assemble(repository, branch: str = ""):
    """按仓库当前的真实 exclusion 规则装配整张图（节点 + 边）。

    ⚠️ ``matcher`` 与 ``exclusion_fingerprint`` 由**调用方**解析并注入——``loader``
    是纯装配层，自身不做规则解析（真实链路里这一步由 ``cache.py`` 承担）。

    ⚠️ 走**公开入口** ``load_graph`` 而不是私有的 ``_load_symbol_nodes``：只装节点的
    话「邻接边一并消失」那半句断言会恒真（图里本来就没有边），威胁 ``T-121-泄漏``
    的 mitigation 就失去了回归。
    """
    from services.code_graph.loader import load_graph

    matcher, fingerprint = build_matcher_and_fingerprint(str(repository.id))
    return load_graph(
        str(repository.id), branch, matcher=matcher, exclusion_fingerprint=fingerprint
    )


# 121-VALIDATION.md 121-05-T2：命中 exclusion 的符号不在节点集，
# 其邻接边一并消失（装配阶段过滤，不是输出阶段过滤）。
@pytest.mark.django_db
def test_exclusion_hides_symbols_and_edges(
    indexed_repo, symbols_factory, call_edges_factory, exclusion_rule_factory
) -> None:
    """被排除文件的符号不进节点集，其邻接边随之整条消失。"""
    exclusion_rule_factory("secret/*")

    caller = symbols_factory("caller", "src/ok.py")
    callee = symbols_factory("callee", "secret/.env.py")
    call_edges_factory(caller, callee)

    result = _assemble(indexed_repo)
    graph = result.graph

    # 过滤发生在**装配阶段**：被排除符号的 id 根本没进过节点集。
    assert str(callee.id) not in graph.nodes
    # 未被排除的一端仍在（不是把整张图连坐掉）。
    assert str(caller.id) in graph.nodes
    # 邻接边一并消失：任一端点不在节点集内 ⇒ 整条边丢弃。
    assert graph.number_of_edges() == 0
    assert result.meta.excluded_file_count == 1


@pytest.mark.django_db
def test_exclusion_covers_unnormalizable_paths(indexed_repo, symbols_factory) -> None:
    """路径归一失败（``..`` 越界 / 绝对路径）一律视为排除，fail-closed。"""
    inside = symbols_factory("inside", "src/ok.py")
    escaped = symbols_factory("escaped", "../outside/x.py")
    absolute = symbols_factory("absolute", "/etc/shadow.py")

    graph = _assemble(indexed_repo).graph

    assert str(inside.id) in graph.nodes
    assert str(escaped.id) not in graph.nodes
    assert str(absolute.id) not in graph.nodes


@pytest.mark.django_db
def test_exclusion_file_count_is_deduped_by_file(
    indexed_repo, symbols_factory, exclusion_rule_factory
) -> None:
    """``excluded_file_count`` 数的是**去重文件数**，不是被丢弃的符号数。"""
    exclusion_rule_factory("secret/*")

    for line in range(1, 4):
        symbols_factory("s", "secret/a.py", start_line=line, end_line=line + 1)
    symbols_factory("s", "secret/b.py")
    symbols_factory("ok", "src/ok.py")

    result = _assemble(indexed_repo)

    # 4 个符号行落在 2 个被排除文件里 —— 计的是**文件**，不是符号。
    assert result.meta.excluded_file_count == 2  # secret/a.py + secret/b.py
    assert result.meta.node_count == 1


@pytest.mark.django_db
def test_exclusion_audit_does_not_spam_per_symbol(
    indexed_repo, exclusion_rule_factory
) -> None:
    """同一个被排除文件下 200 个符号，INFO 级审计埋点总共只打一次。

    装配循环是 10 万级迭代，per-item 的 INFO 会直接打爆 stdout 与日志落库队列
    （``.cursor/rules/observability-logging.mdc`` 的级别纪律点名过同款事故）。
    """
    from codegraph.models import Symbol

    exclusion_rule_factory("secret/*")
    Symbol.objects.bulk_create(
        [
            Symbol(
                repository=indexed_repo,
                branch_name="",
                name=f"s{i}",
                symbol_type="FUNCTION",
                file_path="secret/big.py",
                start_line=i,
                end_line=i + 1,
            )
            for i in range(200)
        ]
    )

    with mock.patch("services.exclusion.log_exclusion_blocked") as blocked_spy:
        result = _assemble(indexed_repo)

    assert result.meta.node_count == 0
    assert result.meta.excluded_file_count == 1
    assert blocked_spy.call_count == 1


# ── 121-03-T1：仓库可读性单一校验点 ────────────────────────────────────────


# 121-VALIDATION.md 121-03-T1：index_status != INDEXED ⇒ 显式抛错，
# 不返回空图（空图会被上层误读为「没有影响」）。
@pytest.mark.django_db(transaction=True)
async def test_not_indexed_raises(indexed_repo) -> None:
    """未索引仓库抛 ``GraphNotIndexed``，且没有任何「返回空图」的出口。"""
    from repositories.models import IndexStatus, Repository

    await Repository.objects.filter(id=indexed_repo.id).aupdate(
        index_status=IndexStatus.NOT_INDEXED
    )

    with pytest.raises(GraphNotIndexed) as excinfo:
        await ensure_repository_readable(None, str(indexed_repo.id))

    assert excinfo.value.details is not None
    assert excinfo.value.details["index_status"] == IndexStatus.NOT_INDEXED

    # 「不返回空图」是签名级保证：本函数唯一的正常出口是 None，拒绝出口只有 raise。
    signature = inspect.signature(ensure_repository_readable)
    assert signature.return_annotation == "None"


# 121-VALIDATION.md 121-03-T1：is_deleted=True 的仓库 ⇒ 拒绝。
@pytest.mark.django_db(transaction=True)
async def test_deleted_repo_denied(indexed_repo) -> None:
    """软删仓库与「不存在」合并为同一出口，不泄漏存在性差异。"""
    from repositories.models import Repository

    await Repository.objects.filter(id=indexed_repo.id).aupdate(is_deleted=True)

    with pytest.raises(GraphAccessDenied) as excinfo:
        await ensure_repository_readable(None, str(indexed_repo.id))

    missing_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(GraphAccessDenied) as excinfo_missing:
        await ensure_repository_readable(None, missing_id)

    # 同一句文案：调用方无法据此区分「已删」与「从来不存在」。
    assert excinfo.value.message == excinfo_missing.value.message


@pytest.mark.django_db(transaction=True)
async def test_invalid_repository_id_is_rejected() -> None:
    """非 UUID 的 ``repository_id`` 在打库之前就被拒（ASVS V5）。"""
    with pytest.raises(GraphAccessDenied):
        await ensure_repository_readable(None, "not-a-uuid")


@pytest.mark.django_db(transaction=True)
async def test_readable_repo_passes_gate(indexed_repo) -> None:
    """``indexed_repo`` 两道闸都过，静默返回 None。"""
    assert await ensure_repository_readable(None, str(indexed_repo.id)) is None


def test_user_acl_extension_point_is_empty() -> None:
    """ACL 扩展点存在且为空实现——本相位只收口校验点，不发明 ACL 模型。"""
    assert _check_user_acl(None, object()) is None
    assert _check_user_acl(object(), object()) is None
    assert (_check_user_acl.__doc__ or "").strip(), "_check_user_acl 必须带扩展点注释"


# ── 121-03-T2：exclusion 同步收口（fail-closed / 指纹 / memo / 记忆化） ──────


def _real_resolve_effective_specs():
    """取未被 patch 的原始实现（供 spy 的 ``side_effect`` 转调）。"""
    import services.exclusion as exclusion_module

    return exclusion_module._resolve_effective_specs


# 121-VALIDATION.md 121-03-T2：matcher 构造失败 ⇒ 抛 GraphAccessDenied，
# 不返回未过滤的图（出口是 raise，不是空列表）。
@pytest.mark.django_db
def test_fail_closed_on_matcher_build_error(indexed_repo) -> None:
    """规则解析/构造失败 ⇒ 整仓拒绝 + 审计埋点，且失败不被 memo 成「下次放行」。"""
    repo_id = str(indexed_repo.id)

    with (
        mock.patch(
            "services.exclusion._resolve_effective_specs",
            side_effect=RuntimeError("规则表炸了"),
        ) as resolve_spy,
        mock.patch("services.exclusion.log_exclusion_blocked") as blocked_spy,
    ):
        with pytest.raises(GraphAccessDenied) as excinfo:
            build_matcher_and_fingerprint(repo_id)

        # 审计埋点已发，且明确标注这是整仓级别的拦截。
        assert blocked_spy.call_count == 1
        assert blocked_spy.call_args.kwargs["surface"] == "code_graph"
        assert blocked_spy.call_args.kwargs["rel_path"] == "<repository>"
        assert excinfo.value.details is not None
        assert excinfo.value.details["error_type"] == "RuntimeError"

        # 再调一次仍抛：失败**不写 memo**，也不返回上一轮的旧 matcher。
        with pytest.raises(GraphAccessDenied):
            build_matcher_and_fingerprint(repo_id)
        assert resolve_spy.call_count == 2


@pytest.mark.django_db
def test_fingerprint_is_stable_across_calls(indexed_repo) -> None:
    """同一仓库连算两次，指纹字符串完全一致（清 memo 后重算也一致）。"""
    repo_id = str(indexed_repo.id)

    _, first = build_matcher_and_fingerprint(repo_id)
    invalidate_matcher_fingerprint_cache(repo_id)
    _, second = build_matcher_and_fingerprint(repo_id)

    assert first == second
    assert len(first) == 16


@pytest.mark.django_db
def test_matcher_fingerprint_memo_resolves_once(indexed_repo) -> None:
    """连调两次只解析编译一次；``invalidate`` 后重新解析。"""
    repo_id = str(indexed_repo.id)

    with mock.patch(
        "services.exclusion._resolve_effective_specs",
        side_effect=_real_resolve_effective_specs(),
    ) as resolve_spy:
        matcher_a, fp_a = build_matcher_and_fingerprint(repo_id)
        matcher_b, fp_b = build_matcher_and_fingerprint(repo_id)

        assert resolve_spy.call_count == 1
        # 命中 memo 拿到的是同一个 matcher 对象（没有重新编译该仓全部 glob/regex）。
        assert matcher_a is matcher_b
        assert fp_a == fp_b

        invalidate_matcher_fingerprint_cache(repo_id)
        build_matcher_and_fingerprint(repo_id)
        assert resolve_spy.call_count == 2


@pytest.mark.django_db
def test_fingerprint_changes_when_rules_change(
    indexed_repo, exclusion_rule_factory
) -> None:
    """新增一条 per-repo 规则后指纹改变（有效规则集的任何变更都要被指纹捕获）。"""
    from services.exclusion import invalidate_matcher_cache

    repo_id = str(indexed_repo.id)
    _, before = build_matcher_and_fingerprint(repo_id)

    exclusion_rule_factory("*.generated.ts")
    # 两份 memo 都要清：只清 exclusion 那份会读到本模块的 60s 旧值。
    invalidate_matcher_cache()
    invalidate_matcher_fingerprint_cache()

    _, after = build_matcher_and_fingerprint(repo_id)
    assert before != after


@pytest.mark.django_db
def test_path_exclusion_memo_dedupes_by_file_path(indexed_repo) -> None:
    """同一 file_path 判定 10 次只穿透 matcher 一次，审计埋点也只打一次。"""
    matcher, _ = build_matcher_and_fingerprint(str(indexed_repo.id))

    with (
        mock.patch.object(
            matcher, "is_excluded", wraps=matcher.is_excluded
        ) as is_excluded_spy,
        mock.patch("services.exclusion.log_exclusion_blocked") as blocked_spy,
    ):
        is_excluded = make_path_exclusion_memo(matcher)

        for _ in range(10):
            assert is_excluded("server/.env") is True
        for _ in range(10):
            assert is_excluded("server/app/views.py") is False

        assert is_excluded_spy.call_count == 2
        # INFO 级审计不随符号数增长：每个被排除 file_path 至多一次。
        assert blocked_spy.call_count == 1

    assert set(is_excluded.excluded_files) == {"server/.env"}
    with pytest.raises(AttributeError):
        is_excluded.excluded_files.add("server/app/views.py")


# ── 121-03-T3：观测契约守护 ─────────────────────────────────────────────────

_LOG_LEVELS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical"}
)
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")
_EVENT_PREFIX = "code_graph_"

# ``services/`` 下、与 ``code_graph/`` 包**同级**、但属于同一条链路的兄弟模块。
#
# 为什么它们在包外：D-01 把 ORM 严格收在包内的 ``loader.py`` 一处，包内其余模块零 ORM。
# 这些文件必须直查 ``Symbol`` / ``Repository`` / ``CrossRepoApiCall``（候选的 signature
# 补取、staleness 三态、跨仓一跳），放进包内即破那条分层。
#
# 为什么它们仍要受管：它们发的事件同属 ``code_graph`` 组件、同用 ``code_graph_`` 前缀，
# 脱敏与静态可解析事件名的要求一条不减。「在包外」是分层的结果，⛔ 不是观测契约的豁免。
#
# ⚠️ 清单**显式**列出，⛔ 不写成 ``code_graph_*.py`` 的 glob：glob 会让一次重命名静默地
# 把文件移出守护，而显式清单配下面的存在性断言会当场变红。
# 🚨 规矩：**谁新建包外兄弟模块，谁在同一个 plan 里把它加进来**（122-06 加
# ``code_graph_cross_repo.py``）。⛔ 不要提前登记还不存在的文件——存在性断言会在两个
# wave 之间一直红着。
_SIBLING_GUARDED_MODULES: tuple[str, ...] = ("code_graph_tools.py",)


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """收集模块级 ``NAME = "字面量"`` / ``NAME: Final[str] = "字面量"``。

    事件名走 ``Final[str]`` 常量是本仓既有形态（``codegraph/lsp/volar_pool.py``
    L42–47），所以「不得拼变量」这条要按**能否静态解析成字面量**判定，而不是
    要求 emit 点必须写裸字符串。f-string / 拼接 / 函数调用一律解析不出来，照样违规。
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _iter_logger_calls(tree: ast.Module):
    """产出包内所有 ``logger.<level>(...)`` 调用节点。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
            and func.attr in _LOG_LEVELS
        ):
            yield node


# 121-VALIDATION.md 121-03-T3（planner 追加行）：观测契约守护——包内每个 structlog
# 调用都带 component="code_graph" + category="sampling" + code_graph_ 事件名前缀。
def test_observability_contract() -> None:
    """code_graph 链路上每个 structlog 调用都满足强制观测契约。

    **扫描面 = 包内全部 ``*.py`` + 一份显式的包外兄弟清单**
    （:data:`_SIBLING_GUARDED_MODULES`）。包内那半用 ``glob``、不写死文件名——
    Plan 121-04~121-09 与 Phase 122 新增的**包内**模块自动受这条契约管住。包外那半
    必须显式登记，理由与规矩写在该常量处：谁新建兄弟模块，谁在同一个 plan 里把它加进
    清单；⛔ 不要提前登记还不存在的文件。

    🚨 Phase 122 之前，本用例只 glob 包内目录，``services/code_graph_tools.py`` 与
    ``services/code_graph_cross_repo.py`` 因此天然落在扫描面之外——**那是缺口，不是
    豁免**。它们照样发 ``code_graph_`` 前缀的事件、照样要把异常文本脱敏，在扩展之前
    没有任何机制强制这一点。122-05 补上第一个，122-06 补上第二个。

    判据对两类文件**逐字相同**，唯一放宽的是 ``category``：包外兄弟文件可取
    ``sampling`` / ``caller`` 之一（给壳层将来下沉的原语留位），包内文件仍**只许**
    ``sampling``——``services/code_graph/*.py`` 里出现 ``caller`` 是架构错误，内核不是
    调用入口。⛔ 其余四条（事件名静态可解析、``code_graph_`` 前缀、
    ``component == "code_graph"``、``error=`` 过 ``redact_secrets_in_text``）一条都不放宽。

    ⚠️ 事件名前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py``
    占用、``galaxy_cache_*`` 已被 ``codegraph/galaxy/cache.py`` 占用。唯一豁免是
    转调 ``services/exclusion.py::log_exclusion_blocked``——它发的是全仓统一审计
    事件 ``exclusion.blocked``，不是本包的 logger 调用，天然不在扫描范围。
    """
    package_dir = Path(code_graph_package.__file__).resolve().parent
    siblings = [package_dir.parent / name for name in _SIBLING_GUARDED_MODULES]
    for sibling in siblings:
        assert sibling.exists(), (
            f"兄弟模块清单漂移：{sibling} 不存在——重命名后请同步更新 "
            "_SIBLING_GUARDED_MODULES，⛔ 不要删条目了事"
        )

    violations: list[str] = []
    scanned = 0

    for source_path in sorted(package_dir.glob("*.py")) + siblings:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        constants = _module_string_constants(tree)

        for call in _iter_logger_calls(tree):
            scanned += 1
            where = f"{source_path.name}:{call.lineno}"

            # ① 事件名必须能静态解析成 snake_case 字面量（不得拼变量）
            event = None
            if call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    event = first.value
                elif isinstance(first, ast.Name):
                    event = constants.get(first.id)
            if event is None:
                violations.append(
                    f"{where}:<unresolved> 事件名不是字符串字面量/模块级字面量常量"
                )
                continue
            if not _SNAKE_CASE.match(event):
                violations.append(f"{where}:{event} 事件名不是 snake_case")

            # ④ 前缀
            if not event.startswith(_EVENT_PREFIX):
                violations.append(f"{where}:{event} 事件名缺少 {_EVENT_PREFIX} 前缀")

            keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}

            # ② component
            component = keywords.get("component")
            if not (
                isinstance(component, ast.Constant) and component.value == "code_graph"
            ):
                violations.append(f'{where}:{event} 缺少 component="code_graph"')

            # ③ category —— 唯一按文件位置放宽的一条：包内只许 sampling（内核不是调用
            #    入口），包外兄弟文件可取 sampling / caller 之一。
            allowed = (
                {"sampling"}
                if source_path.parent == package_dir
                else {"sampling", "caller"}
            )
            category = keywords.get("category")
            if not (
                isinstance(category, ast.Constant) and category.value in allowed
            ):
                violations.append(
                    f"{where}:{event} 的 category 不在 {sorted(allowed)} 之内"
                )

            # ⑤ 异常文本必须脱敏
            error_value = keywords.get("error")
            if error_value is not None and "redact_secrets_in_text" not in ast.unparse(
                error_value
            ):
                violations.append(
                    f"{where}:{event} 的 error= 未过 redact_secrets_in_text"
                )

    assert scanned > 0, f"未在 {package_dir} 下扫描到任何 logger 调用，契约守护形同虚设"
    assert not violations, "观测契约违规：\n" + "\n".join(violations)


# 121-VALIDATION.md 121-03-T2（planner 追加行）：matcher/指纹 60s TTL memo——
# 连算两次只解析一次（见 test_matcher_fingerprint_memo_resolves_once）；invalidate
# 后重新解析；构造失败不写 memo（见 test_fail_closed_on_matcher_build_error）。
def test_matcher_fingerprint_memo_ttl() -> None:
    """本模块 memo 的 TTL 与 ``services/exclusion.py`` 严格对齐。

    暴露窗口（规则变更后最多多久生效）必须与全仓既有 exclusion 读取面完全相同——
    对齐才说明这里没有引入新的弱化。要收窄就两处一起改。
    """
    from services.exclusion import _MATCHER_CACHE_TTL_SECONDS

    assert _MATCHER_FP_TTL_SECONDS == _MATCHER_CACHE_TTL_SECONDS


# 121-VALIDATION.md 121-09-T1（planner 追加行）：barrel 恰导出 17 项
# （含 invalidate_repository），loader/cache/signature/access 不可从包顶层取得。

# 🚨 **逐字写死**这 17 个字面量，⛔ 绝不从 ``code_graph_package.__all__`` 反查——
# 从模块自身反查出期望值的用例是自证的，`__all__` 里多塞一个 ``loader`` 它照样绿，
# 而「不多导出」恰恰是这条红线要守的全部内容。
_EXPECTED_BARREL_EXPORTS = frozenset(
    {
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
    }
)

# 这些名字**存在**于包内子模块，但一律不得出现在包顶层导出面上：前四个是「绕过
# GraphService 三道闸」的直接通路，后三个是存储层/内部 memo 的实现细节。
_FORBIDDEN_BARREL_EXPORTS = (
    "loader",
    "cache",
    "signature",
    "access",
    "estimate_graph_bytes",
    "NODE_COST_BYTES",
    "invalidate_matcher_fingerprint_cache",
)


def test_barrel_exports_only_public_surface() -> None:
    """``services.code_graph`` 的公开面恰是那 17 项，且不含任何内部通路。

    这条用例是**架构红线的机械防线**（威胁登记 T-121-绕闸，ASVS V1）。红线本身写在
    121-CONTEXT Area 4：所有图访问必须经 ``GraphService.get_graph()``，因为它是权限
    校验、exclusion 过滤与水位一致性校验三道闸的唯一收口点。靠自律守不住——靠
    ``__init__.py`` 不导出 + 这条断言才守得住：任何人想绕过校验，都得刻意写出
    ``services.code_graph.loader`` 这样的内部模块路径，而那在 code review 里藏不住。
    """
    exported = code_graph_package.__all__

    assert len(exported) == 17, f"barrel 导出面从 17 项变成了 {len(exported)} 项"
    assert set(exported) == _EXPECTED_BARREL_EXPORTS
    assert list(exported) == sorted(exported), "__all__ 必须字母序（照 code_intel/__init__.py）"

    for forbidden in _FORBIDDEN_BARREL_EXPORTS:
        assert forbidden not in exported, (
            f"{forbidden} 被导出到了包顶层——上层可借它绕过 GraphService 的三道闸"
        )

    # 每一项都真的能取到（``__all__`` 里写了但没 import 的名字会让 `import *` 直接炸）。
    for name in exported:
        assert hasattr(code_graph_package, name), f"__all__ 声明了 {name} 但包顶层取不到"

    # 钩子与上层工具的实际写法必须可用。
    from services.code_graph import (  # noqa: F401 — 断言的就是「能 import」本身
        CodeGraph,
        EdgeConfidence,
        GraphService,
        invalidate_repository,
    )


# 上层直连即架构违规的四个内部子模块（``model`` 是纯契约层，从包根导出，不在此列）。
_INTERNAL_SUBMODULES = frozenset({"loader", "cache", "signature", "access"})

# 全仓扫描时跳过的目录名（虚拟环境 / 依赖 / 构建产物 —— 不是本仓源码）。
_SCAN_SKIP_DIRS = frozenset(
    {".venv", "venv", "node_modules", "__pycache__", ".git", "build", "dist", ".mypy_cache"}
)


def test_no_upper_layer_imports_internal_submodules() -> None:
    """全仓只准从**包根**导入 ``services.code_graph``；直连内部子模块即架构违规。

    🚨 这条才是 ``__init__.py`` 自称的那道「机械防线」。
    ``test_barrel_exports_only_public_surface`` 守的是「barrel 没有变胖」——它只看
    ``__all__``，而 ``__all__`` 只影响 ``from … import *``；
    ``from services.code_graph.loader import load_graph`` 一直都能正常工作，绕过
    ``GraphService.get_graph`` 只需自造一个 ``matcher`` 传进去，可读性校验、exclusion、
    水位复校三道闸**一次全过**（威胁登记 T-121-绕闸，ASVS V1）。

    这条红线要到 Phase 122–127 才真正开始承压，现在建防线成本最低：目前违规数为 0，
    第一条违规写进来的那一刻就会红。
    """
    import ast

    server_root = Path(__file__).resolve().parents[3]
    package_dir = server_root / "services" / "code_graph"
    tests_dir = Path(__file__).resolve().parent
    violations: list[str] = []

    for path in server_root.rglob("*.py"):
        if any(part in _SCAN_SKIP_DIRS for part in path.parts):
            continue
        # 包自身与它的测试目录当然要引内部子模块。
        if package_dir in path.parents or tests_dir in path.parents:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # 非本仓源码 / 生成物，跳过
            continue

        modules: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append((node.lineno, node.module))
                # ⚠️ `from services.code_graph import loader` 的 node.module 就是包根，
                # 违规藏在 names 里。只看 node.module 会漏掉这种写法——而它恰恰是包内部
                # 自己惯用的拼法，也就是上层最容易照抄的那一种。
                if node.module == "services.code_graph":
                    modules.extend(
                        (node.lineno, f"{node.module}.{alias.name}")
                        for alias in node.names
                    )
            elif isinstance(node, ast.Import):
                modules.extend((node.lineno, alias.name) for alias in node.names)

        for lineno, module in modules:
            parts = module.split(".")
            if parts[:2] == ["services", "code_graph"] and len(parts) > 2:
                if parts[2] in _INTERNAL_SUBMODULES:
                    violations.append(
                        f"{path.relative_to(server_root)}:{lineno} {module}"
                    )

    assert not violations, (
        "上层直连 code_graph 内部子模块（绕过 GraphService 的三道闸）：\n"
        + "\n".join(violations)
    )


def test_barrel_docstring_records_the_architecture_red_line() -> None:
    """红线的**理由**必须写在 ``__init__.py`` 的 docstring 里，不能只活在计划文档里。

    只有导出面收敛、没有留下「为什么」的话，下一个人为了图方便补一行
    ``from services.code_graph.loader import load_graph`` 时看不到任何阻力信号。
    """
    doc = code_graph_package.__doc__ or ""
    assert "架构" in doc
    assert "loader" in doc

    source = Path(code_graph_package.__file__).read_text(encoding="utf-8")
    assert "from ." not in source, "barrel 必须用绝对导入（本仓 first-party 约定）"
