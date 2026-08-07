# ricelove 导入纠偏：方案粒度拆项目

## Goal
把「能力簇/合集」与「具体方案」分开：【方案】/PRD 级文档成为独立 Project；Feature 页保留为能力簇容器。

## Locked decisions
- 种子：`【方案】` / `[方案]` / `【PRD】` / `[PRD]` / `【项目一级】` + 标题含 PRD（排除埋点/复盘/技术方案）
- Feature 项目保留为能力簇：留 `product_kb` + 跨版本公共文档；描述标注子项目列表
- 「高三提分专项」不动（非 ricelove，已有 feature_list / test_case）
- 不补写技术方案 / 不跑 blueprint
- MiMo：`mimo` credential + `mimo-v2.5-pro`

## Results（2026-08-07）
| 项 | 数量 |
|----|------|
| ricelove Feature（能力簇） | 247 |
| ricelove-scheme 独立项目 | 284 |
| 附属文档迁入方案项目 | 590 |
| 仍留在合集（公共/无法归类） | ~1017 |
| 方案项目已挂仓库 | 267 / 284 |

### 示例
- 合集：http://localhost:10240/projects/aecbe6fd-32b7-46a3-8033-47dd1851fe4f 「新用户引导相关」
- 独立方案：http://localhost:10240/projects/f3f5b5ee-f981-4139-a810-3aed9b1be2cf 「新用户引导3.0-新首页版」

## Gaps（源站本身就没有 / 难自动补）
| 类型 | ricelove 侧 | 说明 |
|------|-------------|------|
| `feature_list` | 0 | 仅「高三提分专项」有人工录入 |
| `test_case` | 0 | 同上 |
| `dev_spec` / `ui_design` | 很少 | 仅标题可识别的少数飞书链接 |
| 飞书正文 | 多数未拉取 | 限流 / 无权限，仅存外链 |
| 未匹配仓库 | 17 个方案项目无仓 | 父簇也无或未继承到 |

## Scripts
- `import_ricelove.py` — 初版 Feature→Project
- `resplit_schemes.py` — 方案/PRD → 独立 Project
- `assign_supports.py` — MiMo 把附属文档归到方案项目
