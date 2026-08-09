"""同步 Friday skills 到 task 构建物料目录。

单一事实源是仓库根的 ``skills/skills/``（git submodule），本脚本把其中的
编码期技能目录镜像拷贝到 ``task/assets/skills/``：
friday-code / friday-memory / friday-impact / friday-refactoring。
``task/assets/skills/`` 只是构建物料的镜像拷贝（task 镜像 build context 是
``./task``，无法直接 COPY 仓库根之外的内容）——**改动技能请改源头
skills/skills/ 后重跑本脚本**，勿手工编辑 assets 副本（hash 一致性测试
task/tests/test_skills_injection.py 会拦截双源漂移）。

用法::

    python task/scripts/sync_skills.py

幂等：目标目录存在则先删除再全量拷贝；源目录缺失时报错退出非 0（防静默漂移）。
仅使用 stdlib，无第三方依赖。

注意：friday-routing 等「仅 IDE」技能不进容器 SKILL_NAMES（与编码期工作流分流）。
"""

import shutil
import sys
from pathlib import Path

# 编码期容器同源技能（勿把 friday-routing 等仅 IDE 技能误加进来）
SKILL_NAMES = ("friday-code", "friday-memory", "friday-impact", "friday-refactoring")


def main() -> int:
    """执行同步，返回进程退出码。"""
    repo_root = Path(__file__).resolve().parents[2]
    source_base = repo_root / "skills" / "skills"
    target_base = repo_root / "task" / "assets" / "skills"

    for name in SKILL_NAMES:
        source = source_base / name
        if not source.is_dir():
            print(f"错误: 源目录不存在: {source}", file=sys.stderr)
            print("请确认 skills/ 子模块已初始化（git submodule update --init）", file=sys.stderr)
            return 1

    target_base.mkdir(parents=True, exist_ok=True)

    for name in SKILL_NAMES:
        source = source_base / name
        target = target_base / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        file_count = sum(1 for p in target.rglob("*") if p.is_file())
        print(f"已同步 {name}: {file_count} 个文件 → {target.relative_to(repo_root)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
