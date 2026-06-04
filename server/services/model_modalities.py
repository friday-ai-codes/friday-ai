"""模型输入模态能力推断与归一化。
Provider 的 available_models 是聊天入口判断附件能力的真源；本模块只做
保守推断：认识的模型自动标注，不认识的一律只给 text，由用户在 Provider
编辑弹窗里显式修正。
"""
from __future__ import annotations
from typing import Any, Literal
from services.model_capabilities import ModelCapabilities, ModelCapabilitiesEntry
from services.provider_config import ProviderType
InputModality = Literal["text", "image", "audio", "video", "pdf"]
SUPPORTED_INPUT_MODALITIES: tuple[InputModality, ...] = (
 "text",
 "image",
 "audio",
 "video",
 "pdf",
)
_KNOWN_TEXT_ONLY_PREFIXES = (
 "deepseek",
 "deepseek-",
 "deepseek/",
)
def normalize_input_modalities(value: Any) -> list[InputModality]:
 """归一化 input_modalities，保证 text 始终存在且顺序稳定。"""
 raw_items = value if isinstance(value, list) else
 seen: set[str] = set
 normalized: list[InputModality] =
 for item in ["text", *raw_items]:
 modality = str(item or "").strip.lower
 if modality not in SUPPORTED_INPUT_MODALITIES or modality in seen:
 continue
 seen.add(modality)
 normalized.append(modality) # type: ignore[arg-type]
 return normalized or ["text"]
def _provider_capability_key(provider_type: ProviderType) -> str:
 if provider_type in {ProviderType.OPENAI_CHAT, ProviderType.OPENAI_RESPONSES}:
 return "openai"
 return provider_type.value
def _known_capabilities(
 provider_type: ProviderType,
 model_id: str,
) -> ModelCapabilitiesEntry | None:
 """只返回精确/前缀命中的能力，拒绝 provider wildcard 乐观兜底。"""
 provider = _provider_capability_key(provider_type)
 table = ModelCapabilities._load # noqa: SLF001 - 能力推断需要知道是否命中 fixture。
 if (provider, model_id) in table:
 return table[(provider, model_id)]
 best: ModelCapabilitiesEntry | None = None
 best_len = 0
 for (entry_provider, entry_model), entry in table.items:
 if entry_provider != provider or entry_model == "*":
 continue
 if model_id.startswith(entry_model) and len(entry_model) > best_len:
 best = entry
 best_len = len(entry_model)
 return best
def infer_model_modalities(
 *,
 provider_type: ProviderType | str | None,
 model_id: str,
 raw_model: dict[str, Any] | None = None,
) -> tuple[list[InputModality], str]:
 """推断模型输入模态，返回 (modalities, source)。"""
 raw_model = raw_model or {}
 if "input_modalities" in raw_model:
 return normalize_input_modalities(raw_model.get("input_modalities")), "manual"
 if "supports_vision" in raw_model:
 modalities: list[InputModality] = ["text"]
 if bool(raw_model.get("supports_vision")):
 modalities.append("image")
 return modalities, "legacy_supports_vision"
 model_lower = model_id.strip.lower
 if model_lower.startswith(_KNOWN_TEXT_ONLY_PREFIXES):
 return ["text"], "known_rules"
 try:
 provider_enum = ProviderType(str(provider_type))
 except ValueError:
 return ["text"], "manual_default"
 known = _known_capabilities(provider_enum, model_id)
 if known is not None:
 modalities = ["text", "image"] if known.supports_vision else ["text"]
 return modalities, "known_rules"
 if provider_enum == ProviderType.ANTHROPIC and model_lower.startswith("claude-"):
 return ["text", "image"], "known_rules"
 return ["text"], "manual_default"
