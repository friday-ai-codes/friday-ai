# Phase 87 — 飞书写 API live 验证 deferred 清单（87-01 BOARD-01）

**Mode:** Autonomous — 本期不阻断、不询问。所有写 API 端点 / 请求体 / 返回字段名当前为
`[ASSUMED]`，autonomous 路径以 `server/tests/services/test_feishu_create_work_item.py`
（respx mock）覆盖契约。下列三项需在**真实凭证 + 真实飞书空间**下人工补跑，回填
`[ASSUMED] → [VERIFIED]`。

背景：Phase 78 仅验证飞书项目 API 的**读**（get_work_item / query / relation 读），
**写 API 从未真机跑通**（见 MILESTONE-PROPOSAL §14 风险）。

---

## A-CREATE — work_item/create 真实端点 / 请求体 / 返回 id 字段名

**待验证 `[ASSUMED]`：**
- 端点：`POST /open_api/{project_key}/work_item/{work_item_type}/create`
- 请求体：`{"name": <feature名>, "field_value_pairs": [{"field_key": "description", "field_value": <富文本>}], "template_id"?: <id>}`
- 返回新 id 字段名：`data.id`（备选 `data.work_item_id`）
- 鉴权：`X-PLUGIN-TOKEN` + `X-USER-KEY`（镜像 `update_work_item_fields`）

**如何验证：**
1. 用真实 `plugin_token + user_key` 在测试空间对某 `work_item_type`（如 story）调
   `FeishuClient.create_work_item(project_key, "story", "UAT 建项冒烟", description="...")`。
2. 确认建项成功、记录真实返回体形状（id 字段名）、是否需要 `template_id`。
3. 回填：端点路径 / 请求体字段名 / 返回 id 字段名 → 去掉 `# [ASSUMED] A-CREATE` 注释。

---

## A-REL — relation_type=1 关联项目跟踪 + 父子写端点（是否需配置中心预配）

**待验证 `[ASSUMED]`：**
- 端点：`POST /open_api/{project_key}/work_item/{work_item_type}/{work_item_id}/relation`
- 请求体：`{"relation_type": 1, "target_id": <目标id>, "target_type"?: <类型>}`
- `relation_type=1` 是否即「关联项目跟踪」；父子关系类型是否需在**配置中心预配**后方可写。

**如何验证：**
1. 对 A-CREATE 新建的 work_item 调
   `add_work_item_relation(project_key, type, id, relation_type=1, target_id=<项目跟踪看板id>)`。
2. 确认关联写入成功、回到飞书 UI 核对「关联项目跟踪」生效。
3. 尝试写父子关系，确认是否需预配关系类型；回填真实 `relation_type` 取值表。

---

## A-DEGRADE — 父子关系类型未配的真实错误码（回填降级阈值）

**待验证 `[ASSUMED]`：**
- 关系能力探测端点：`GET /open_api/{project_key}/work_item/{work_item_type}/meta`（候选）
- meta 中关系类型定义的真实形状（`_extract_relation_type_keys` 当前兼容多候选）
- 父子关系类型**未配置**时 `add_work_item_relation` 的真实 `err_code`

**如何验证：**
1. 在**未配置**父子关系类型的空间调 `detect_relation_capability` + 尝试写父子关系。
2. 记录真实错误码 / meta 形状，回填 `detect_relation_capability` 的命中判定与
   `_extract_relation_type_keys` 解析逻辑（precise 化降级阈值）。
3. 确认降级路径：缺父子 → 建看板不挂父子 + 提示去配置中心（87-03 消费降级位）。

---

**回填后：** 移除 `server/services/feishu.py` 中对应 `[ASSUMED] A-*` 注释，并把本文件对应项
标记 `[VERIFIED]`。
