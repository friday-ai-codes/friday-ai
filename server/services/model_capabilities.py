"""ModelCapabilities — Provider 模型能力 + 定价查询服务（contract / contract）。

数据源：本地 vendored fixture `server/agents/fixtures/model_prices.json`（不引入 litellm Python 包）。
查询优先级：精确 → 前缀（longest-match）→ Provider `*` 兜底 → 全局 `*/*` 兜底 → DEFAULT_CAPABILITIES。

implementation 交付:
- ModelCapabilitiesEntry @dataclass(frozen=True) 六字段 Decimal 定价
- ModelCapabilities.get() 四级 lookup 永不 raise
- ModelCapabilities.merge_ollama() 写入 credential.available_models（caller 负责 save/aupdate）
- _FIXTURE_KEY_MAP 支持 LiteLLM 上游字段名与 v21.0 内部字段名双向映射

implementation 承接点: runtime cache + /api/show context_length 主动拉取。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

FIXTURE_PATH = Path(__file__).parent.parent / "agents" / "fixtures" / "model_prices.json"


@dataclass(frozen=True)
class ModelCapabilitiesEntry:
    """单模型能力与定价条目（v21.0 内部 schema，与 LiteLLM 上游字段通过 _FIXTURE_KEY_MAP 映射）。"""

    provider: str
    model: str
    max_input_tokens: int
    max_output_tokens: int
    input_cost_per_token: Decimal
    output_cost_per_token: Decimal
    cached_input_cost_per_token: Decimal = Decimal("0")
    cache_creation_cost_per_token: Decimal = Decimal("0")
    reasoning_cost_per_token: Decimal = Decimal("0")
    vision_cost_per_token: Decimal = Decimal("0")
    supports_function_calling: bool = True
    supports_vision: bool = False
    supports_thinking: bool = False
    supports_reasoning: bool = False
    supports_prompt_caching: bool = False


# fixture key（与上游 LiteLLM 兼容）→ ModelCapabilitiesEntry 字段名映射
# 同名字段（v21.0 内部规范）映射到自身；LiteLLM 历史字段名映射到新字段名
_FIXTURE_KEY_MAP: dict[str, str] = {
    "max_input_tokens": "max_input_tokens",
    "max_output_tokens": "max_output_tokens",
    "input_cost_per_token": "input_cost_per_token",
    "output_cost_per_token": "output_cost_per_token",
    "cached_input_cost_per_token": "cached_input_cost_per_token",
    "cache_creation_cost_per_token": "cache_creation_cost_per_token",
    "reasoning_cost_per_token": "reasoning_cost_per_token",
    "vision_cost_per_token": "vision_cost_per_token",
    "supports_function_calling": "supports_function_calling",
    "supports_vision": "supports_vision",
    "supports_thinking": "supports_thinking",
    "supports_reasoning": "supports_reasoning",
    "supports_prompt_caching": "supports_prompt_caching",
    # 兼容上游 LiteLLM 字段名（备用，未来若直接 vendor LiteLLM JSON 可用）
    "cache_read_input_token_cost": "cached_input_cost_per_token",
    "cache_creation_input_token_cost": "cache_creation_cost_per_token",
    "output_cost_per_reasoning_token": "reasoning_cost_per_token",
}

_DECIMAL_FIELDS = {
    "input_cost_per_token",
    "output_cost_per_token",
    "cached_input_cost_per_token",
    "cache_creation_cost_per_token",
    "reasoning_cost_per_token",
    "vision_cost_per_token",
}


DEFAULT_CAPABILITIES = ModelCapabilitiesEntry(
    provider="*",
    model="*",
    max_input_tokens=128000,
    max_output_tokens=4096,
    input_cost_per_token=Decimal("0.000003"),
    output_cost_per_token=Decimal("0.000015"),
    supports_function_calling=True,
)


class ModelCapabilities:
    """Provider 模型能力查询。

    类级 `_cache` 使 fixture JSON 进程内只读一次；Django runserver 重启自动重载。
    """

    _cache: dict[tuple[str, str], ModelCapabilitiesEntry] | None = None

    @classmethod
    def _load(cls) -> dict[tuple[str, str], ModelCapabilitiesEntry]:
        if cls._cache is None:
            raw_list = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
            cls._cache = {(e["provider"], e["model"]): cls._parse_entry(e) for e in raw_list}
        return cls._cache

    @classmethod
    def _parse_entry(cls, raw: dict[str, Any]) -> ModelCapabilitiesEntry:
        kwargs: dict[str, Any] = {"provider": raw["provider"], "model": raw["model"]}
        for fixture_key, entry_key in _FIXTURE_KEY_MAP.items():
            if fixture_key in raw:
                val = raw[fixture_key]
                if entry_key in _DECIMAL_FIELDS:
                    kwargs[entry_key] = Decimal(str(val))
                else:
                    kwargs[entry_key] = val
        return ModelCapabilitiesEntry(**kwargs)

    @classmethod
    def get(cls, provider: str, model: str) -> ModelCapabilitiesEntry:
        """查询优先级：精确 → 前缀（longest-match）→ Provider `*` → 全局 `*/*` → DEFAULT_CAPABILITIES。"""
        table = cls._load()
        # 1. 精确匹配
        if (provider, model) in table:
            return table[(provider, model)]
        # 2. 前缀匹配（longest-match）—— 同 provider 内
        best: ModelCapabilitiesEntry | None = None
        best_len = 0
        for (p, m), entry in table.items():
            if p == provider and m != "*" and model.startswith(m) and len(m) > best_len:
                best = entry
                best_len = len(m)
        if best is not None:
            return best
        # 3. Provider 级兜底
        if (provider, "*") in table:
            return table[(provider, "*")]
        # 4. 全局兜底
        return table.get(("*", "*"), DEFAULT_CAPABILITIES)

    @classmethod
    def merge_ollama(cls, credential: Any, models_from_tags: list[str]) -> None:
        """contract：Ollama /api/tags 返回的模型清单合并到 credential.available_models。

        本 phase：仅写 available_models 字段（caller 负责 save / aupdate 入库）。
        implementation 可在此基础上增加运行时 cache 与 /api/show context_length 拉取。

        Args:
            credential: ProviderCredential 实例（仅赋值 available_models，不 save）
            models_from_tags: Ollama /api/tags 返回的 model name 列表
        """
        credential.available_models = list(models_from_tags)
        logger.info(
            "model_capabilities_merge_ollama",
            credential_id=str(getattr(credential, "id", "")),
            models_count=len(models_from_tags),
        )
