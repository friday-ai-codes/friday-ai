"""容器失败归因 —— 「这次失败该不该烧掉重试预算」的唯一判据（纯函数，零依赖）。

为什么需要它
============

调研 / 拟方案容器的重试上界是**按派发次数**记的（``RepoResearchTask.attempt``，上界见
``blueprint_research_adapter._MAX_ATTEMPTS``）。派发即计数，且计数不区分两类完全不同的失败：

- **产物问题**：容器真的跑完了，但产出不合格（缺字段、schema 不过、结论自相矛盾）。
  这类失败重试一次两次就该放弃 —— 再跑一遍大概率还是这个结果，继续烧钱没有意义。
- **基础设施问题**：容器**根本没跑起来**或跑到一半被环境掐断（模型额度耗尽、API key 失效、
  runner 掉线、镜像拉不下来、网络不通）。这类失败与需求本身无关，环境修好后重跑就能过。

2026-09-04 的事故正是后者被当成前者记账：编码 Agent 额度不足（403）⇒ 五个仓的容器全部秒败
⇒ 每仓 ``attempt`` 各 +1 ⇒ 两波之后撞上上界 ⇒ **整个会话永久报废**，只能新建会话重来。
连废三个会话（``f5d22090`` / ``e7366b5d`` / ``6a14d871``）。用户把 key 换好了，但预算已经
烧光了 —— 环境问题恢复了，编排却回不来。

判据纪律
========

⛔ **宁可漏判，不可错判**：漏判（基础设施故障被当成产物问题）最坏是照旧烧掉一次预算，
就是现状；错判（产物问题被当成基础设施故障）会让一个永远也跑不出合格产物的仓**无限重派**
容器，把预算变成摆设。所以关键词只收「不可能由产物质量引起」的那一类信号。
"""

from __future__ import annotations

import re

__all__ = ["INFRASTRUCTURE_FAILURE_REASON", "is_infrastructure_failure"]

# 归因命中时写进 ``RepoResearchTask.error["reason"]`` 与失败事件 ``error_kind`` 的值。
# 与 ``container_failed``（产物侧失败）并列，运维据此一眼分清「环境炸了」和「跑不出东西」。
INFRASTRUCTURE_FAILURE_REASON = "infrastructure_failed"

# 逐条都必须满足「不可能由产物质量引起」。⛔ 不要往里加 "error" / "failed" / "exception"
# 这类泛化词——那等于把所有失败都判成基础设施故障，重试上界直接失效。
_INFRA_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # 额度 / 计费：模型侧拒绝服务，与需求无关
        r"额度不足|余额不足|配额(?:不足|超限|用尽)|欠费",
        r"\b(?:insufficient_quota|quota[_ ]exceeded|out of credits?|insufficient[_ ]balance)\b",
        r"\bbilling\b.{0,40}\b(?:required|hard limit|exceeded)\b",
        # 认证 / 授权：key 失效或没配对，重跑再多次也一样
        r"\b(?:invalid[_ ]api[_ ]key|authentication[_ ]error|unauthorized|forbidden)\b",
        r"\bapi key\b.{0,30}\b(?:invalid|expired|missing|not found)\b",
        r"凭证(?:失效|无效|缺失|未配置)|未配置(?:模型|供应商)凭证",
        # 上游限流：暂时性，等一会儿就好
        r"\b(?:rate[_ ]limit(?:ed|_error|_exceeded)?|too many requests)\b",
        # 429 必须挂在 status/code/http 上下文里——裸的 "429" 完全可能是产物正文里的数字。
        r"\b(?:status|code|http)\b[^0-9]{0,10}429\b",
        # runner / 容器编排：容器压根没起来
        r"\bno (?:online |available )?runner\b|runner (?:offline|unavailable|disconnected)",
        r"runner\s*(?:掉线|离线|不可用)|(?:无在线|没有在线|无可用)\s*runner",
        r"\b(?:image ?pull ?back ?off|errimagepull|imagepullbackoff)\b",
        r"\b(?:docker|container)\b.{0,40}\b(?:daemon|socket)\b.{0,40}"
        r"\b(?:not running|unavailable|refused)\b",
        # 网络：连不上上游
        r"\b(?:connection (?:refused|reset|timed out)|dns (?:failure|resolution failed))\b",
        r"\b(?:ECONNREFUSED|ENETUNREACH|EAI_AGAIN)\b",
    )
)


def is_infrastructure_failure(error_text: object) -> bool:
    """失败文本是否属于**基础设施故障**（⇒ 不该烧掉重试预算）。

    入参是容器回调里的 error 原文（已脱敏截断也没关系，关键词都在开头附近）。非字符串、
    空串一律回 ``False`` —— 判不出来就按「产物问题」走既有计数，见模块 docstring 的纪律。
    """
    text = str(error_text or "")
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INFRA_PATTERNS)
