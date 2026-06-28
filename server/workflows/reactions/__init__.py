"""Reaction runtime package (Chassis v2 · P0).

把 lifecycle hook / process event / artifact transition 投影成稳定的
``Signal`` 值对象，再由 ``ReactionRuntime`` 幂等地触发横切副作用。

红线：signal 是对既有事实源的**即时投影**，不落第三套事件表。
"""

from workflows.reactions.signal import (
    SIGNAL_NAMES,
    Signal,
    project_from_hook,
)

__all__ = ["Signal", "SIGNAL_NAMES", "project_from_hook"]
