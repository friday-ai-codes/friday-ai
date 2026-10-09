# 蓝图业务交付就绪门

新融合版本在原 blueprint/v1 结构上增加 `delivery_contract_version: 1`。这与 MCP 工具 schema 的注册表独立：它校验业务接口、提供/消费任务、数据来源和交接投影。

分仓方案每条 API 增加 delivery：status、implementation_item_ids、provider_repository_id（消费者）、fields_needed/data_sources（提供方）、evidence（既有/外部来源）。状态可为 planned_in_scope、existing_verified、external_verified、unresolved、deferred。

新接口无需预先存在实现代码。planned_in_scope 要求 schema 明确，提供/消费实现项均存在，新数据来源有建设任务、owner和acceptance。existing/external 的 evidence 要求仓库、精确 SHA 与相对路径；确认者仍需按研究证据核实真实性，结构校验不会访问远端或把任意路径变成真实证据。

请求/响应应提供 JSON Schema，或者 delivery.request_schema_ref/response_schema_ref（repository_id、commit_sha、path、sha256）。消费与提供两侧必须引用同一契约形状/版本。大型 schema 引用由运行侧下载复算后用于兼容性测试。

实现链：RepoPlan prompt/结构 → merge 原样投影并将本地 item ID 换算为稳定 ID → 按明确提供仓及精确 kind/method/path 绑定 → AI review 机械 blocker → 最终确认事务内重算 → confirmed handoff 再检查无损投影。

协作仓被排除时保留 needs_support，不将其偷偷改成 existing。明确延期必须有人工 decision_log.id 且 consumer_disabled=true；外部现有依赖要给证据。两者均由新版 readiness 独立核对。

旧已确认蓝图仍可只读取件，新增 delivery_readiness 返回 ready=false 和 legacy_contract_unverified；这允许保留固定 Mock 取件，不宣称它通过新业务门。缺口不能因旧 confirmed 状态而当成真实质量通过。新的融合版本自动启用门，不需要调用者自行选择绕过。

handoff 增加 delivery_readiness（绑定 contentHash/validatorVersion，含 blockers 与 contractTaskMatrix）。repository_tasks 新增 implementation_item_ids、feature_point_ids、provides、consumes、contract_dependencies。契约依赖与整仓任务完成依赖分开传递，已冻结schema可并行编码；集成阶段必须核对这些提供方。旧字段保留，调用者应按新字段做集合完整性检查。

版本化蓝图缺口返回 blueprint_delivery_not_ready，旧版本坐标仍返回 blueprint_handoff_stale。MCP 客户端只有确认状态、请求四坐标、任务数与服务端结果一致才落盘；新版 readiness 不通过不落文件。每次取件使用唯一文件名避免并发覆盖。

本次不宣称整个 MCP Phase 146–152 已完成。相关 handoff 工具已同步并补包级验证；完整目录生成、operation 控制面等仍按其独立里程碑实施。
