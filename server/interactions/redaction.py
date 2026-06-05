"""入库前统一脱敏（contract / contract）。

所有写入 Interaction Ledger 的结构化数据——``InteractionEvent.payload`` /
``ToolCallRecord.input``·``output`` / ``ModelUsageRecord.*`` /
``InteractionRun.raw_request``——在 ``acreate`` 之前**必须**先经 ``redact_for_ledger``，
保证数据库里绝不出现明文 token / secret / API key / password（contract）。

设计要点：
- **复用不重写**：直接 import ``common/logging`` 的 ``_redact_value`` / ``REDACTED``，
  沿用同一套字段名 + 值正则（sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥），
  避免脱敏规则在两处漂移（威胁 security mitigation-02）。
- **friday_pat_ 兜底**：本系统 Access Token 前缀 ``friday_pat_`` 不被现有
  ``SENSITIVE_VALUE_PATTERN`` 覆盖（Pitfall 4），故在 ``_redact_value`` 之上再追加一层
  ``_scrub_pat`` 递归替换 ``friday_pat_xxxx``。同时 ``common/logging`` 的
  ``SENSITIVE_VALUE_PATTERN`` 也已同步追加该分支，让 structlog 输出一并脱敏。
- **结构化阶段脱敏**：在 dict / list 结构上脱敏，绝不先 ``json.dumps`` 成字符串再脱敏
  （否则字段名命中失效，威胁 security mitigation-05）。
- 纯逻辑模块，全量严格类型注解（Pitfall 5）。
"""

from __future__ import annotations

import re
from typing import Any

from common.logging import REDACTED, _redact_value

# Friday Access Token 明文前缀（access_tokens.generate_pat 生成）。
# 现有 common.logging.SENSITIVE_VALUE_PATTERN 不覆盖此前缀，这里做兜底。
_PAT_PATTERN = re.compile(r"friday_pat_[A-Za-z0-9_\-]{20,}")


def _scrub_pat(value: Any) -> Any:
    """递归替换字符串中的 ``friday_pat_`` 明文 token。

    dict / list 递归下钻，str 用 ``_PAT_PATTERN`` 替换为 REDACTED；
    int / bool / None 等其余类型原样返回。
    """
    if isinstance(value, dict):
        return {k: _scrub_pat(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_pat(item) for item in value]
    if isinstance(value, str):
        return _PAT_PATTERN.sub(REDACTED, value)
    return value


def redact_for_ledger(payload: Any) -> Any:
    """账本入库前统一脱敏入口。

    先用 ``common.logging._redact_value`` 覆盖字段名命中 + 通用凭证值
    （sk-ant-* / sk-* / AIza* / Bearer * / PEM 私钥），再用 ``_scrub_pat``
    兜底本系统 ``friday_pat_`` 明文（双保险）。对 nested dict / list / str 全覆盖，
    int / bool / None 原样返回。

    **写库前必经此函数**（contract / contract）：任何写入账本表的 payload /
    raw_request / tool input·output / model prompt 都先调用本函数再 acreate。
    """
    return _scrub_pat(_redact_value(payload))
