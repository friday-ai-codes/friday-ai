"""把本轮蓝图工件的 goal 块补成完整需求正文（修 4000 字符截断的历史落库）。

`_MAX_GOAL_CHARS` 已改成只做 DoS 兜底，但本轮 intake 是在改动**之前**跑的，
落库的 goal 块仍是 4000 字符截断版（断在模块 4 句中间）。这里按会话
`decomposition.requirement_text`（权威全文）原地补齐当前版本的那个块。

⛔ 不新开版本：这不是一次内容修订，而是修复同一份 intake 种子的落库缺陷；
新开版本会在版本树里留下一个语义上不存在的「修订」。
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

SESSION_ID = "4d6984c4-cbab-4ae3-ba5f-d49f5dfd5eb6"


def main() -> None:
    from delivery.models import ArtifactVersion, ConvergenceSession
    from services.process_runtime.blueprint_intake import GOAL_BLOCK_ID
    from services.process_runtime.blueprint_schema import validate_blueprint

    session = ConvergenceSession.objects.filter(id=SESSION_ID).first()
    if session is None:
        raise SystemExit(f"session not found: {SESSION_ID}")

    full = str((session.decomposition or {}).get("requirement_text") or "")
    if not full:
        raise SystemExit("decomposition.requirement_text 为空，拿不到权威全文")

    version = ArtifactVersion.objects.filter(id=session.current_artifact_version_id).first()
    if version is None:
        raise SystemExit("current_artifact_version 不存在")

    content = version.content
    blocks = (content.get("requirement_spec") or {}).get("goal") or []
    target = next((b for b in blocks if b.get("block_id") == GOAL_BLOCK_ID), None)
    if target is None:
        raise SystemExit(f"没找到 {GOAL_BLOCK_ID} 块")

    before = str(target.get("text") or "")
    print(f"goal block: {len(before)} chars -> {len(full)} chars")
    if before == full:
        print("已是全文，无需改动")
        return

    if "--dry-run" in sys.argv:
        return

    target["text"] = full
    ok, err = validate_blueprint(content)
    if not ok:
        raise SystemExit(f"改后不过 schema 校验，已放弃写入：{err}")

    version.content = content
    version.save(update_fields=["content"])

    fresh = ArtifactVersion.objects.get(id=version.id)
    text = next(
        b["text"]
        for b in fresh.content["requirement_spec"]["goal"]
        if b.get("block_id") == GOAL_BLOCK_ID
    )
    print(f"重读 DB：{len(text)} chars，模块 10 在正文里 = {'## 模块 10' in text}")


if __name__ == "__main__":
    main()
