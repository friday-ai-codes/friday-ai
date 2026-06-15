"""截图识别需求编排服务（Phase 35 Plan 01，VIS-01）。

链路：截图（瞬态 bytes）→ 经既有 provider 解析选 vision 能力模型 → 调多模态 LLM 提取
「文字 / UI 元素 / 业务意图」结构化语义 → 拼文本 query → 喂**既有**交付知识检索
``DeliveryKnowledgeSearchService.search_similar(entity_kinds=["work_item"])`` 召回 work_item
类需求 → 结构化返回。

边界与不变量：
- **不持久化原图**（VIS-01 标准 3）：截图仅在内存 bytes → base64 inline 送 LLM，绝不落盘、
  绝不走任何图片存储面；本模块也**不建图片向量库**（不引入向量写入 / embedding 写入面）。
- **复用既有检索**（VIS-01 标准 2，CONTEXT Grey Area 2）：召回走既有交付知识检索 chokepoint
  （含 ``resolve_allowed_project_ids`` 访问域 / 多仓 / fail-closed 排除），绝不新建检索。
- **graceful 降级**（VIS-01 标准 3，镜像 Phase 24 sensitive_detect T-24-07）：无 provider /
  无 default_model / 模型无 vision 能力 / 调用或解析异常 → 一律降级（不抛、不冒泡），且
  日志只记 ``error_type``（**不记 str(exc)**），防回显图片/密钥（T-35-04）。
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

import structlog

from services.model_modalities import infer_model_modalities
from services.provider_config import PROVIDER_REGISTRY, ProviderConfigService, ProviderType

logger = structlog.get_logger(__name__)

__all__ = [
    "DEGRADE_EXTRACTION_FAILED",
    "DEGRADE_NO_VISION_MODEL",
    "ExtractedSemantics",
    "extract_semantics",
    "recall_from_screenshot",
]

# 降级原因码（机器可判，供前端区分文案 / 是否展示「前往系统设置」入口；WR-01）。
# - no_vision_model：无 provider / 无 default_model / 模型无 vision 能力（配置问题，可去系统设置修复）。
# - extraction_failed：vision 模型调用或 JSON 解析失败 / 提取到空语义（运行期问题，配置无误时应重试）。
DEGRADE_NO_VISION_MODEL = "no_vision_model"
DEGRADE_EXTRACTION_FAILED = "extraction_failed"

# 降级固定中文文案（脱敏，不回显原始异常 / 图片内容；按原因码区分，对齐 35-UI-SPEC degraded 语义）。
_DEGRADED_REASONS: dict[str, str] = {
    DEGRADE_NO_VISION_MODEL: (
        "当前未配置可用的多模态（vision）模型，无法从截图提取语义；"
        "请在系统设置配置具备视觉能力的模型后重试。"
    ),
    DEGRADE_EXTRACTION_FAILED: (
        "已配置视觉模型，但本次未能从截图提取出有效语义；"
        "请稍后重试，或更换更清晰、信息更完整的截图。"
    ),
}

# vision 语义提取系统提示：严格输出 JSON {text, ui_elements, business_intent}。
_SYSTEM_PROMPT = (
    "你是界面截图语义提取助手。请观察用户上传的界面/原型截图，提取三类信息并"
    "严格输出 JSON 对象，仅含以下三个字符串字段，不要输出任何额外文字：\n"
    '{"text": "截图中的关键文字/文案（OCR）", '
    '"ui_elements": "可见 UI 控件与布局描述（按钮/输入框/列表等）", '
    '"business_intent": "推断的业务意图/功能场景"}'
)
_EXTRACT_INSTRUCTION = "请提取这张截图的文字、UI 元素与业务意图，按系统要求严格输出 JSON。"


@dataclass(frozen=True)
class ExtractedSemantics:
    """多模态 LLM 提取的结构化语义三段（任一可为空字符串）。"""

    text: str = ""
    ui_elements: str = ""
    business_intent: str = ""


def _model_supports_vision(provider_type: ProviderType, model_id: str) -> bool:
    """双判模型是否具备 image 输入能力：provider registry.supports_vision + 模型模态推断。

    任一不支持视为无 vision 能力（保守降级）。
    """
    meta = PROVIDER_REGISTRY.get(provider_type)
    if meta is None or not meta.supports_vision:
        return False
    modalities, _ = infer_model_modalities(provider_type=provider_type, model_id=model_id)
    return "image" in modalities


def _build_image_block(
    provider_type: ProviderType, mime_type: str, image_bytes: bytes
) -> dict:
    """从内存 bytes 直接构造 provider 多模态 image content block（绝不落盘）。"""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    if provider_type == ProviderType.ANTHROPIC:
        return {
            "type": "image",
            "source_type": "base64",
            "mime_type": mime_type,
            "data": b64,
        }
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
    }


def _parse_semantics_json(raw: str) -> ExtractedSemantics | None:
    """解析 LLM 输出为语义三段；非 JSON 时截取首个 {} 块容错，失败返回 None。

    容错复用 sensitive_detect._parse_llm_verdicts 同款思路（json.loads 失败 → 正则截取）。
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return ExtractedSemantics(
        text=str(data.get("text", "") or ""),
        ui_elements=str(data.get("ui_elements", "") or ""),
        business_intent=str(data.get("business_intent", "") or ""),
    )


async def extract_semantics(
    image_bytes: bytes,
    mime_type: str,
    *,
    node_config: dict | None = None,
) -> tuple[ExtractedSemantics | None, str | None]:
    """多模态 LLM 提取截图语义；任意降级条件/异常 → 不抛（VIS-01 标准 1）。

    返回 ``(semantics, degrade_reason)``：
    - 成功 → ``(ExtractedSemantics, None)``。
    - 配置类降级 → ``(None, DEGRADE_NO_VISION_MODEL)``：无可用 provider 凭证 /
      无 ``extra["default_model"]`` / 模型无 vision 能力（双判失败）。
    - 运行期降级 → ``(None, DEGRADE_EXTRACTION_FAILED)``：模型调用异常 / JSON 解析失败。

    区分两类原因码（WR-01）：配置问题可引导用户去系统设置修复；运行期失败应提示重试，
    避免「模型已配置但调用失败」时误导用户去配置模型。

    隐私：异常仅记 ``error_type``，不记 ``str(exc)``（防回显图片/密钥，T-35-04）。
    """
    try:
        from services.provider_config import ProviderMissingError

        resolved = await ProviderConfigService.aresolve_or_error(node_config)
        if isinstance(resolved, ProviderMissingError):
            logger.info("screenshot_recall.skipped_no_provider")
            return None, DEGRADE_NO_VISION_MODEL

        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.info("screenshot_recall.skipped_no_model")
            return None, DEGRADE_NO_VISION_MODEL

        if not _model_supports_vision(resolved.provider_type, model_name):
            logger.info(
                "screenshot_recall.skipped_no_vision",
                provider_type=str(resolved.provider_type),
            )
            return None, DEGRADE_NO_VISION_MODEL

        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model, content_to_text

        system = SystemMessage(content=_SYSTEM_PROMPT)
        human = HumanMessage(
            content=[
                {"type": "text", "text": _EXTRACT_INSTRUCTION},
                _build_image_block(resolved.provider_type, mime_type, image_bytes),
            ]
        )
        model = build_chat_model(resolved, model_name, streaming=False)
        response = await model.ainvoke([system, human])
        parsed = _parse_semantics_json(content_to_text(response.content))
        if parsed is None:
            # 模型已配置但输出无法解析为语义 JSON → 运行期失败（非配置问题）。
            logger.warning("screenshot_recall.parse_failed")
            return None, DEGRADE_EXTRACTION_FAILED
        return parsed, None
    except Exception as exc:  # noqa: BLE001 — 任何异常一律 graceful 降级（T-35-04）
        logger.warning(
            "screenshot_recall.extract_failed",
            error_type=type(exc).__name__,
        )
        return None, DEGRADE_EXTRACTION_FAILED


def _build_query(semantics: ExtractedSemantics) -> str:
    """拼接三段非空语义为文本 query（段间换行）。"""
    segments = [semantics.text, semantics.ui_elements, semantics.business_intent]
    return "\n".join(seg.strip() for seg in segments if seg and seg.strip())


def _degraded_result(reason_code: str) -> dict:
    """构造降级返回（含原因码 + 已脱敏文案；对齐 35-UI-SPEC ScreenshotRecallResult）。"""
    return {
        "degraded": True,
        "degraded_code": reason_code,
        "degraded_reason": _DEGRADED_REASONS.get(
            reason_code, _DEGRADED_REASONS[DEGRADE_EXTRACTION_FAILED]
        ),
        "semantics": None,
        "query": None,
        "results": [],
    }


def _clamp01(value) -> float:
    """把分值收敛到 [0, 1]（WR-03）。

    ``dto.score`` 为融合分（vector + recency），不保证落在 [0,1]，直接透出会让前端
    ``相关度 %`` 超过 100%。在 API 边界统一钳制，保证语义为「相关度」的概率区间。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _to_recalled_requirement(dto) -> dict:
    """SearchResultDTO → 35-UI-SPEC RecalledRequirement 形状。

    work_item_id 取 ``entity.source_id`` 优先、回退 ``entity.entity_id``（PLAN-CHECKER
    WARNING #1：不假设序列化 dict 顶层有 source_id）；link 来自 ``provenance.feishu_url``。
    relevance 经 ``_clamp01`` 钳制到 [0,1]（WR-03），不影响排序（单调钳制）。
    """
    entity = dto.entity
    work_item_id = str(getattr(entity, "source_id", "") or getattr(entity, "entity_id", "") or "")
    item: dict = {
        "work_item_id": work_item_id,
        "title": getattr(entity, "title", "") or "",
        "relevance": _clamp01(dto.score),
        "source": "delivery_knowledge",
    }
    feishu_url = getattr(getattr(entity, "provenance", None), "feishu_url", None)
    if feishu_url:
        item["link"] = feishu_url
    return item


async def recall_from_screenshot(
    image_bytes: bytes,
    mime_type: str,
    *,
    user,
    node_config: dict | None = None,
    top_k: int = 8,
) -> dict:
    """截图 → vision 提语义 → 文本 query → 既有交付知识检索召回 work_item（结构化返回）。

    返回形状对齐 35-UI-SPEC ``ScreenshotRecallResult``：
    - 提取降级（extract_semantics 失败）→ ``{degraded: true, degraded_code, degraded_reason,
      semantics: null, query: null, results: []}``（不抛；``degraded_code`` 区分
      no_vision_model / extraction_failed，WR-01）。
    - 提取成功但召回阶段异常 → ``{degraded: false, semantics, query, results: []}``（语义在、召回
      空，前端走 no-results 而非 error；不误判为 degraded）。
    - 正常 → ``{degraded: false, semantics, query, results: [...]}``。
    """
    semantics, degrade_reason = await extract_semantics(
        image_bytes, mime_type, node_config=node_config
    )
    if semantics is None:
        return _degraded_result(degrade_reason or DEGRADE_EXTRACTION_FAILED)

    query = _build_query(semantics)
    if not query.strip():
        # WR-02：三段语义全空 → 空 query 的最近邻是退化/任意结果，跳过检索，
        # 按「提取失败」降级返回（而非以空串误触发一次无意义的向量召回）。
        logger.info("screenshot_recall.empty_query_skip")
        return _degraded_result(DEGRADE_EXTRACTION_FAILED)

    results: list[dict] = []
    try:
        from knowledge.models import EntityKind
        from knowledge.retrieval import DeliveryKnowledgeSearchService

        dtos = await DeliveryKnowledgeSearchService().search_similar(
            query,
            user=user,
            entity_kinds=[EntityKind.WORK_ITEM.value],
            top_k=top_k,
        )
        results = [_to_recalled_requirement(dto) for dto in dtos]
    except Exception as exc:  # noqa: BLE001 — 召回故障不抛，区分降级与空召回（语义已成功）
        logger.warning(
            "screenshot_recall.search_failed",
            error_type=type(exc).__name__,
        )
        results = []

    return {
        "degraded": False,
        "semantics": {
            "text": semantics.text,
            "ui_elements": semantics.ui_elements,
            "business_intent": semantics.business_intent,
        },
        "query": query,
        "results": results,
    }
