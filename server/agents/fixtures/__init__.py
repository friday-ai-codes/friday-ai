"""initial implementation: Provider model capabilities fixtures（LiteLLM 精选子集）。

来源：BerriAI/litellm 上游 model_prices_and_context_window.json 的精选子集。
本 phase 不引入 litellm Python 包（contract 锁定），仅 vendor JSON。
fixture schema 与 LiteLLM 字段命名一致；内部映射在 services/model_capabilities.py::_FIXTURE_KEY_MAP 完成。
"""
