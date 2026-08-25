"""阶段 2 分仓方案（RepoPlan）的 jsonschema 契约（Phase 113-03，DESIGN §5.3）。

四条契约（模块级不变量，改动前先读）：

1. **与 ``blueprint_schema.py`` 平级独立**：RepoPlan 是**中间产物**（落
   ``PartialPlan.content.repo_plan``），不是蓝图文档，故不并入蓝图 schema 模块。
2. **绝不修改 ``blueprint_schema.py``**：该文件在 112-05 冻结面自检清单内（零命中断言）。
   报错脱敏出口是从那里**复制**过来的 12 行，**不 import 它的私有函数**。
3. **纯函数**（无 IO / 无 ORM / 无 LLM），仅依赖 stdlib + jsonschema。
4. ``validate_repo_plan`` **绝不外抛异常** —— 调用方靠 ``(ok, err)`` 决定有界重试
   ≤2 轮，仍不合格则开阻塞澄清线程，绝不静默降级。

字段与枚举一律与 111 已冻结的 ``blueprint_schema.BLUEPRINT_JSON_SCHEMA`` 同源（融合投影
要直接搬）：``impl_items[].change_type`` 对齐 ``implementation_overview.items[].change_type``；
``apis_consumed[].data_source.availability`` 对齐 ``api_contracts.items.data_source.availability``
（**可用性在 ``data_source`` 下，蓝图 schema 里没有顶层同名字段**）。
"""

from __future__ import annotations

from typing import Any

import jsonschema

__all__ = [
    "BLUEPRINT_REPO_PLAN_SCHEMA",
    "REPO_PLAN_ROLES",
    "REPO_PLAN_VERDICTS",
    "REPO_PLAN_CHANGE_TYPES",
    "REPO_PLAN_AVAILABILITY",
    "coerce_repo_plan_shapes",
    "validate_repo_plan",
]

# 校验报错出口长度上限：jsonschema 对 type/enum/const 类失败会把被校验实例的 repr
# 整段拼进 message 且不做截断，而 repo_plan content 是半可信正文（容器/LLM 产出，
# 可能夹带代码片段或凭证样本），报错会进 task.error 与调用方日志——出口统一脱敏 + 截断。
_MAX_ERROR_CHARS = 500
_TRUNCATED_SUFFIX = "…（已截断）"

# 与 ``subagent.api.callbacks._BLUEPRINT_ROLES`` / ``_BLUEPRINT_VERDICTS`` **同值**（同源枚举）。
REPO_PLAN_ROLES = ("direct", "indirect")
REPO_PLAN_VERDICTS = ("suitable", "partial", "unsuitable")

# SCHEMA-03 的 change_type：新建 / 改动 / 删除 / 间接完善。取值与
# ``blueprint_schema.BLUEPRINT_JSON_SCHEMA`` 的 ``implementation_overview.items[].change_type``
# **逐字一致**（已核对：既有枚举字面量即下列四值），融合投影时可直接搬不做映射。
REPO_PLAN_CHANGE_TYPES = ("create", "modify", "remove", "indirect_refine")

# 与 ``blueprint_schema`` 的 ``api_contracts.items.data_source.availability`` 枚举逐字同源
# （已核对：只有这两个值）。绝不引入蓝图 schema 里不存在的变体——写进去会让 113-05 的融合
# 投影在 ``validate_blueprint`` 处判非法，或更糟：114/115 按 schema 路径读不到而静默失效。
REPO_PLAN_AVAILABILITY = ("existing", "needs_support")

_CITATIONS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "证据引用（裸文件路径/符号名，融合装配时再归一为引用池 id）",
}

BLUEPRINT_REPO_PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "BlueprintRepoPlan",
    "description": "阶段 2 单仓分仓方案（DESIGN §5.3）：十一字段，落 PartialPlan.content.repo_plan",
    "type": "object",
    "$defs": {
        "block": {
            "type": "object",
            "description": "最小可锚定内容单元，与确认门 _as_block_list 产物同形",
            "required": ["block_id"],
            "properties": {
                "block_id": {"type": "string", "minLength": 1, "description": "块稳定标识"},
                "type": {"type": "string", "description": "块类型（paragraph/list/...）"},
                "text": {"description": "块正文（字符串或字符串数组）"},
            },
        },
    },
    # required 只锁三键：indirect 仓的能力引用清单只有 apis_provided 与 responsibility，
    # 强制其余字段会让合法的间接仓产物判非法。
    "required": ["repository_id", "role", "impl_items"],
    "properties": {
        "repository_id": {
            "type": "string",
            "minLength": 1,
            "description": "本方案所属仓库 id（服务端权威写入，不采信容器上报值）",
        },
        "role": {
            "type": "string",
            "enum": list(REPO_PLAN_ROLES),
            "description": "确认门锁定的角色：direct=需改动本仓 / indirect=只被依赖或参考",
        },
        "responsibility": {
            "type": "array",
            "items": {"$ref": "#/$defs/block"},
            "description": "确认门锁定的本仓职责（只读引用，不由容器改写）",
        },
        "fitness": {
            "type": "object",
            "description": "阶段 1 适配度结论快照",
            "properties": {
                "verdict": {"type": "string", "enum": list(REPO_PLAN_VERDICTS)},
                # 阶段 1 落的是字符串列表，确认门投影后是 block 列表——两种形状都合法。
                "reasons": {"type": "array", "items": {"type": ["string", "object"]}},
                "citations": _CITATIONS,
            },
        },
        "current_state": {
            "type": "array",
            "description": (
                "本仓现状分析。**这是 merge 阶段 current_state_analysis 的直接投影源，"
                "字段名不得漂移**（summary / findings[].title / detail / citations）。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"description": "现状小结"},
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "detail": {"type": "string"},
                                "citations": _CITATIONS,
                            },
                        },
                    },
                },
            },
        },
        "impl_items": {
            "type": "array",
            "minItems": 0,
            "description": "本仓实现项（SCHEMA-03 的功能↔模块↔仓库映射原料）",
            "items": {
                "type": "object",
                "required": ["item_id", "title", "change_type", "how"],
                "properties": {
                    "item_id": {"type": "string", "minLength": 1, "description": "本仓内唯一"},
                    "title": {"type": "string", "minLength": 1},
                    "change_type": {
                        "type": "string",
                        "enum": list(REPO_PLAN_CHANGE_TYPES),
                        "description": "变更类型（新建/改动/删除/间接完善）",
                    },
                    "how": {"description": "怎么改（伪代码或分步说明）"},
                    "files_touched": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "**本仓内**其他 item_id；跨仓依赖走 apis_consumed",
                    },
                    "test_strategy": {"description": "测试策略"},
                    "citations": _CITATIONS,
                },
            },
        },
        "apis_provided": {
            "type": "array",
            "description": "本仓对外提供的接口契约（同 §3.9 结构）",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "request_schema": {"type": "object"},
                    "response_schema": {"type": "object"},
                    "description": {"description": "接口说明"},
                    "citations": _CITATIONS,
                },
            },
        },
        "apis_consumed": {
            "type": "array",
            "description": (
                "本仓需要消费的接口契约（同 §3.9 结构）。可用性与协作仓一律在 "
                "``data_source`` 下，**不存在顶层可用性字段**（111 schema 无此键）。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "request_schema": {"type": "object"},
                    "response_schema": {"type": "object"},
                    "description": {"description": "接口说明"},
                    "from_repository_id": {
                        "type": "string",
                        "description": (
                            "RepoPlan 中间产物**专属**键（蓝图 api_contracts 无此键）：供 "
                            "113-04 建 provider→consumer 边与 113-05 对账定位。融合投影时映射到 "
                            "data_source.from_service / data_source.support_repository_id，"
                            "不落进蓝图顶层。"
                        ),
                    },
                    "data_source": {
                        "type": "object",
                        "description": "数据来源说明（含可用性与需配合的协作仓）",
                        "properties": {
                            "from_service": {"type": "string"},
                            "from_api": {"type": "string"},
                            "fields_needed": {"type": "array", "items": {"type": "string"}},
                            "availability": {
                                "type": "string",
                                "enum": list(REPO_PLAN_AVAILABILITY),
                                "description": "existing=对方已有 / needs_support=需对方配合产出",
                            },
                            "support_repository_id": {
                                "type": "string",
                                "description": "needs_support 时：哪个仓要配合（必填）",
                            },
                            "notes": {"description": "补充说明"},
                        },
                    },
                    "citations": _CITATIONS,
                },
            },
        },
        "local_impact": {
            "type": "object",
            "description": "本仓维度影响（同 §3.10 子集）",
            "properties": {
                "affected_modules": {"type": "array", "items": {"type": "string"}},
                "affected_features": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "citations": _CITATIONS,
                        },
                    },
                },
                "migration_required": {"type": "boolean"},
                "notes": {"description": "补充说明"},
            },
        },
        "risks": {
            "type": "array",
            "items": {"$ref": "#/$defs/block"},
            "description": "本仓风险",
        },
        "open_question_thread_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本仓未决澄清线程 id",
        },
    },
}

# 预编译校验器：schema 体量大，避免每次调用重新编译。
_REPO_PLAN_VALIDATOR = jsonschema.Draft202012Validator(BLUEPRINT_REPO_PLAN_SCHEMA)


def _format_error(json_path: str, message: Any) -> str:
    """校验报错唯一出口：脱敏 + 截断，只保留定位信息与开头的可读原因。"""
    text = str(message)
    try:
        from common.logging import redact_secrets_in_text

        text = redact_secrets_in_text(text)
    except Exception:  # noqa: BLE001 — 脱敏不可用时也不能让校验器抛（fail-safe）
        pass
    if len(text) > _MAX_ERROR_CHARS:
        text = text[:_MAX_ERROR_CHARS] + _TRUNCATED_SUFFIX
    return f"{json_path}: {text}"


def _check_depends_on(content: dict) -> str | None:
    """后置检查 (a)：``impl_items[].depends_on`` 只能引用**本仓**已声明的 item_id。

    跨仓依赖的表达面是 ``apis_consumed``（带 ``data_source``），不是 ``depends_on``——
    混用会让 113-05 的波次派生把跨仓边当成仓内顺序，拓扑结果失真。
    """
    items = content.get("impl_items")
    if not isinstance(items, list):
        return None
    known = {
        str(item.get("item_id")) for item in items if isinstance(item, dict) and item.get("item_id")
    }
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for dep in item.get("depends_on") or []:
            if str(dep) not in known:
                return f"impl_items[{index}].depends_on 引用的 {dep} 不存在于本仓实现项"
    return None


def _check_needs_support(content: dict) -> str | None:
    """后置检查 (b)：标了 ``needs_support`` 的消费项必须给出协作仓。

    这是 FLOW-06「消费的接口必须找到提供方或显式标注 needs_support」在**仓级**的前置守卫。
    判定**只认 ``data_source.*`` 路径**：``data_source`` 缺失视为未标注、不触发本检查；
    顶层同名字段一律不读（111 schema 里没有那个键，读它会让判定建立在幻觉字段上）。
    """
    consumed = content.get("apis_consumed")
    if not isinstance(consumed, list):
        return None
    for index, item in enumerate(consumed):
        if not isinstance(item, dict):
            continue
        data_source = item.get("data_source")
        if not isinstance(data_source, dict):
            continue
        if str(data_source.get("availability") or "") != "needs_support":
            continue
        if not str(data_source.get("support_repository_id") or "").strip():
            return (
                f"apis_consumed[{index}].data_source 标了 needs_support 但缺 "
                f"support_repository_id（找不到配合仓）"
            )
    return None


def _check_block_lists(content: dict) -> str | None:
    """后置检查 (c)：Block[] 中每个块仍须有正文，补锚点不能掩盖畸形块。

    ``block_id`` 可由服务端确定性生成，但 ``text`` 是代理交付的实质内容，不能编造。这里仅
    检查实际采用 Block[] 形状的字段；``impl_items[].how`` / ``test_strategy`` 的纯字符串
    仍是合法兼容形状。
    """

    fields: list[tuple[str, Any]] = [
        ("responsibility", content.get("responsibility")),
        ("risks", content.get("risks")),
    ]
    for item_index, item in enumerate(content.get("impl_items") or []):
        if not isinstance(item, dict):
            continue
        for field in ("how", "test_strategy"):
            value = item.get(field)
            if isinstance(value, list):
                fields.append((f"impl_items[{item_index}].{field}", value))

    for path, blocks in fields:
        if not isinstance(blocks, list):
            continue
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                return f"{path}[{block_index}] 必须是内容块对象"
            if "text" not in block:
                return f"{path}[{block_index}] 缺 text（仅 block_id 可安全补全）"
            text = block.get("text")
            if not isinstance(text, (str, list)):
                return f"{path}[{block_index}].text 必须是字符串或字符串数组"
            if isinstance(text, list) and any(not isinstance(value, str) for value in text):
                return f"{path}[{block_index}].text 必须是字符串数组"
    return None


def _coerce_block_list(value: Any, *, purpose: str, repository_short_id: str) -> Any:
    """Block[] 形状归一：包装裸字符串、吸收常见正文别名并补稳定锚点。"""

    if not isinstance(value, list):
        return value
    coerced: list[Any] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            item = {"type": "paragraph", "text": item}
        if isinstance(item, dict):
            # MCP schema 已要求 text，但模型仍会把风险块写成
            # {summary, detail, citations}。这不是缺正文，而是字段名漂移；按信息量优先级
            # 机械搬运既有正文，不拼接、不改写语义。完全没有正文候选时仍交给后置检查拒绝。
            if "text" not in item:
                for alias in ("detail", "description", "summary", "title"):
                    candidate = item.get(alias)
                    if isinstance(candidate, (str, list)):
                        item = {**item, "text": candidate}
                        break
            if not str(item.get("block_id") or ""):
                item = {
                    **item,
                    "block_id": f"blk_repo_plan_{purpose}_{repository_short_id}_{index}",
                }
        coerced.append(item)
    return coerced


def coerce_repo_plan_shapes(content: Any) -> Any:
    """校验前的宽容归一化：吸收 LLM 产物的常见形状漂移（原地修改并返回）。

    只收敛**机械可判**的两类实测漂移，⛔ 不做任何语义补全，未知形状原样保留交给
    jsonschema 报错（宁可重试不猜）：

    1. ``local_impact.affected_features`` 写成字符串数组（schema 要求
       ``[{name, citations}]``）——字符串项包装为 ``{"name": s}``。
    2. Block[] 字段（``responsibility`` / ``risks`` / ``impl_items[].how`` /
       ``impl_items[].test_strategy``）的项缺 ``block_id``、写成裸字符串，或把既有正文放在
       ``detail`` / ``description`` / ``summary`` / ``title``——锚点可安全合成，正文别名只做
       字段搬运；没有任何正文候选的块仍由后置检查拒绝。
    """
    try:
        if not isinstance(content, dict):
            return content
        impact = content.get("local_impact")
        if isinstance(impact, dict):
            features = impact.get("affected_features")
            if isinstance(features, list):
                impact["affected_features"] = [
                    {"name": item} if isinstance(item, str) else item for item in features
                ]
        rid = str(content.get("repository_id") or "x")[:8]
        for field in ("responsibility", "risks"):
            if isinstance(content.get(field), list):
                content[field] = _coerce_block_list(
                    content[field],
                    purpose=field,
                    repository_short_id=rid,
                )
        items = content.get("impl_items")
        if isinstance(items, list):
            for item_index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("item_id") or item_index)[:16]
                for field in ("how", "test_strategy"):
                    if isinstance(item.get(field), list):
                        item[field] = _coerce_block_list(
                            item[field],
                            purpose=f"{field}_{item_id}",
                            repository_short_id=rid,
                        )
        # 3. api 契约的 request_schema / response_schema 写成字符串（schema 要求 object）
        #    ——字符串是模型对「字段清单」的自然写法，包装为 {"description": s} 保语义。
        for field in ("apis_provided", "apis_consumed"):
            apis = content.get(field)
            if not isinstance(apis, list):
                continue
            for api in apis:
                if not isinstance(api, dict):
                    continue
                for key in ("request_schema", "response_schema"):
                    value = api.get(key)
                    if isinstance(value, str):
                        api[key] = {"description": value}
    except Exception:  # noqa: BLE001 — 归一化 best-effort，绝不反噬校验主流程
        pass
    return content


def validate_repo_plan(content: Any) -> tuple[bool, str | None]:
    """校验 repo_plan 段：jsonschema 结构 + 两条后置检查。

    Args:
        content: 半可信 repo_plan dict（容器产物 / 服务端 LLM 合成产物）。

    Returns:
        ``(True, None)`` 合法；``(False, error_message)`` 非法（报错经
        :func:`_format_error` 脱敏 + 截断，绝不原样回显整段被校验实例）。**绝不外抛异常**。
    """
    if not isinstance(content, dict):
        return False, "repo_plan 必须是 JSON 对象"
    try:
        errors = sorted(_REPO_PLAN_VALIDATOR.iter_errors(content), key=lambda e: e.json_path)
        if errors:
            first = errors[0]
            return False, _format_error(first.json_path, first.message)
        for checker in (_check_depends_on, _check_needs_support, _check_block_lists):
            problem = checker(content)
            if problem is not None:
                return False, problem
    except Exception as exc:  # noqa: BLE001 — 绝不外抛：调用方靠 (ok, err) 决定重试/开澄清
        return False, _format_error("$", str(exc))
    return True, None
