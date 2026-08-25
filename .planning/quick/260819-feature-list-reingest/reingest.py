"""确定性解析高三提分专项 Feature List V1.2 并重写项目 feature_list 工件。

不走 LLM：直接按 `## 模块 N：` / `#### 功能点 X：` 的固定结构切分，
经 FeatureListService.aset_feature_list(mode="manual") 唯一写入入口落库。
「响应式适配」章节按文档声明（不属于业务功能模块）不计入模块。
"""

import asyncio
import os
import re
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

PROJECT_ID = "75248ff9-3a22-4175-b940-6093d71eb4dc"
MD_PATH = os.path.join(os.path.dirname(__file__), "feature_list_v1.2.md")

MODULE_RE = re.compile(r"^## (模块 \d+：.+?)\s*$")
FEATURE_RE = re.compile(r"^#### (功能点 [A-Za-z0-9]+：.+?)\s*$")
SUMMARY_HEAD_RE = re.compile(r"^### \d+\.1 功能简述\s*$")
ACCEPT_ITEM_RE = re.compile(r"^- \[ \] (.+)$")


def parse(text: str) -> list[dict]:
    lines = text.splitlines()
    # 模块区间：第一个模块标题到「## 响应式适配」（不含）
    idxs = [i for i, ln in enumerate(lines) if MODULE_RE.match(ln)]
    end = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "## 响应式适配"), len(lines)
    )
    modules = []
    for n, start in enumerate(idxs):
        stop = idxs[n + 1] if n + 1 < len(idxs) else end
        mod_lines = lines[start:stop]
        mod_name = MODULE_RE.match(mod_lines[0]).group(1)

        # summary：功能简述小节正文
        summary = ""
        for i, ln in enumerate(mod_lines):
            if SUMMARY_HEAD_RE.match(ln):
                buf = []
                for ln2 in mod_lines[i + 1 :]:
                    if ln2.startswith("###") or ln2.strip() == "---":
                        if buf:
                            break
                        continue
                    if ln2.strip():
                        buf.append(ln2.strip())
                summary = " ".join(buf)
                break

        # 功能点切分
        fidxs = [i for i, ln in enumerate(mod_lines) if FEATURE_RE.match(ln)]
        features = []
        for m, fs in enumerate(fidxs):
            fe = fidxs[m + 1] if m + 1 < len(fidxs) else len(mod_lines)
            fl = mod_lines[fs:fe]
            fname = FEATURE_RE.match(fl[0]).group(1)
            source = "\n".join(fl).strip()
            # 验收项：- [ ] 条目 + 紧随的「测试数据」行
            acceptance = []
            in_accept = False
            for i, ln in enumerate(fl):
                if ln.strip() == "**验收项**":
                    in_accept = True
                    continue
                if not in_accept:
                    continue
                mm = ACCEPT_ITEM_RE.match(ln.strip())
                if mm:
                    item = mm.group(1).strip()
                    if i + 1 < len(fl) and fl[i + 1].strip().startswith("测试数据"):
                        item += "（" + fl[i + 1].strip() + "）"
                    acceptance.append(item)
            features.append({"name": fname, "acceptance": acceptance, "source": source})
        modules.append({"module": mod_name, "summary": summary, "features": features})
    return modules


async def main() -> None:
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from initiatives.services.feature_list_service import FeatureListService

    with open(MD_PATH, encoding="utf-8") as f:
        text = f.read()
    modules = parse(text)

    total = sum(len(m["features"]) for m in modules)
    print(f"parsed modules={len(modules)} features={total}")
    for m in modules:
        print(f"  {m['module']}  features={len(m['features'])}")
        for f in m["features"]:
            print(f"     - {f['name']}  (acceptance={len(f['acceptance'])})")

    if "--dry-run" in sys.argv:
        return

    User = get_user_model()
    admin = await sync_to_async(
        lambda: User.objects.filter(is_superuser=True).order_by("id").first()
    )()
    art = await FeatureListService().aset_feature_list(
        PROJECT_ID,
        mode="manual",
        modules=modules,
        title="Feature List（高三提分专项 V1.2）",
        actor=admin,
        initiated_by_user_id=getattr(admin, "id", None),
    )
    print(f"artifact updated: {art.id}")


if __name__ == "__main__":
    asyncio.run(main())
