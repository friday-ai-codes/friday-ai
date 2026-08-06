# Quick 260806-fy2 SUMMARY — AI 澄清提问对话式改造

## Done

- **后端**：`blueprint_ambiguity_score` 归一保留 `related_feature_points` / `recommended`；system prompt 强制口语化题面、禁止裸写 `fp_id`、须填相关功能点与推荐项。
- **前端**：新增 `BlueprintClarificationWizard`（一题一题、选项+推荐+其他、整包提交）；`ThreadCard` 按 `isStructuredClarificationQuestions` 分流；功能点 chip 带标题并可 `goto-anchor`。
- **接线**：`[id].vue` 从 `requirement_spec.feature_points` 建标题 map，经 Sidebar → Card → Wizard。

## Verify

- `uv run pytest tests/services/process_runtime/test_blueprint_ambiguity_score.py -q` ✅
- `pnpm exec vitest run clarificationQuestions + threadSidebar` ✅ 42 passed

## Notes

- 旧线程无 `related_feature_points` 时，向导仍从题面 regex 抽 `fp_*` 并回填标题。
- 扁平 `{label,value}` / 确认门 / 人工评论路径未改。
- 新提问质量依赖下一轮规格门 LLM；已入库的旧题面不会自动改写，但 UI 向导已可逐步作答。
