"""Phase — search_repository_code 0 结果诊断单元测试。
致敬 Claude Code issue #30150 的失败诊断思路 —— 与其让模型猜「为什么没结果」，
不如直接告诉它「问题在哪 + 建议怎么改」。
覆盖 4 类典型 query 形态：
- 多关键词混搜（用户实际遇到的反模式）
- 全小写自然语言词（无 L2 符号可匹配）
- L3 召回但分数低于 min_score（建议降阈值）
- L3 召回 0（建议换工具）
"""
from __future__ import annotations
from agents.tools.space_tools import _diagnose_empty_search
def test_diagnose_multi_keyword_query -> None:
 """用户实际 case：9 个空格分隔关键词混搜 → 应建议拆 query。"""
 diag = _diagnose_empty_search(
 query="studyRoom views classroom report floor friends shareRoom studying fighting",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=2,
 )
 assert "9 个空格分隔的词" in str(diag["issues"])
 assert any("拆成" in s for s in diag["suggestions"])
 assert diag["query_analysis"]["keyword_count"] == 9
def test_diagnose_pure_lowercase_natural_language -> None:
 """全小写自然语言（没有 PascalCase/dotted symbol）→ 建议用代码符号。"""
 diag = _diagnose_empty_search(
 query="user login page handler",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=1,
 )
 issues_text = str(diag["issues"])
 suggestions_text = str(diag["suggestions"])
 assert "全是小写自然语言词" in issues_text
 assert "代码层符号" in suggestions_text
 assert diag["query_analysis"]["is_pure_lowercase_words"] is True
def test_diagnose_single_pascal_symbol_no_issue -> None:
 """单个 PascalCase 符号是好 query —— 不应触发"多概念"或"全小写"诊断。"""
 diag = _diagnose_empty_search(
 query="UserService",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=1,
 )
 issues_text = str(diag["issues"])
 assert "9 个" not in issues_text
 assert "全是小写" not in issues_text
 # 但应该提示用其他工具（因为 L3 是 0）
 assert "list_space_repositories" in str(diag["suggestions"]) or \
 "list_space_structure" in str(diag["suggestions"])
 assert diag["query_analysis"]["has_uppercase_symbol"] is True
def test_diagnose_score_just_below_threshold_suggests_lower_min_score -> None:
 """L3 召回了候选但最高分稍低于 min_score → 建议降 min_score 重试。"""
 diag = _diagnose_empty_search(
 query="entrance",
 min_score=0.5,
 l3_top_score=0.42, # 略低于 0.5
 l3_raw_count=10,
 searched_repos=1,
 )
 issues_text = str(diag["issues"])
 suggestions_text = str(diag["suggestions"])
 assert "略低于 min_score" in issues_text
 assert "min_score=0.3" in suggestions_text
def test_diagnose_score_far_below_threshold_suggests_change_query -> None:
 """L3 召回了但分数远低于 min_score（< 0.7 * threshold）→ 建议换 query，降阈值救不回来。"""
 diag = _diagnose_empty_search(
 query="entrance",
 min_score=0.5,
 l3_top_score=0.15, # 远低于 0.5 * 0.7 = 0.35
 l3_raw_count=20,
 searched_repos=1,
 )
 issues_text = str(diag["issues"])
 suggestions_text = str(diag["suggestions"])
 assert "远低于 min_score" in issues_text
 assert "降阈值救不回来" in issues_text
 # 应该建议换 query 而不是降阈值
 assert "min_score=0.3" not in suggestions_text
 assert "精准" in suggestions_text or "代码符号" in suggestions_text
def test_diagnose_l3_zero_recall_suggests_other_tools -> None:
 """L3 完全召回 0 → 提示模型用 list_space_structure 等工具看仓库实际内容。"""
 diag = _diagnose_empty_search(
 query="StudyRoom",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=3,
 )
 issues_text = str(diag["issues"])
 suggestions_text = str(diag["suggestions"])
 assert "召回 0 条候选" in issues_text
 assert (
 "list_space_structure" in suggestions_text
 or "list_space_repositories" in suggestions_text
 )
def test_diagnose_returns_complete_structure -> None:
 """诊断字典必须包含 summary / issues / suggestions / query_analysis / score_analysis。"""
 diag = _diagnose_empty_search(
 query="x",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=0,
 )
 assert "summary" in diag
 assert "issues" in diag and isinstance(diag["issues"], list) and len(diag["issues"]) >= 1
 assert "suggestions" in diag and isinstance(diag["suggestions"], list) and len(diag["suggestions"]) >= 1
 assert "query_analysis" in diag
 assert "score_analysis" in diag
 assert diag["score_analysis"]["min_score_threshold"] == 0.5
def test_diagnose_short_query_no_keyword_issue -> None:
 """短 query（< 阈值）不应触发"多关键词"诊断。"""
 diag = _diagnose_empty_search(
 query="login api", # 2 词，低于 4 阈值
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=1,
 )
 issues_text = str(diag["issues"])
 assert "2 个空格分隔的词" not in issues_text
 # 但 "全小写" 会触发（因为 2 词且都小写）
 assert diag["query_analysis"]["is_pure_lowercase_words"] is True
def test_diagnose_dotted_identifier_recognized_as_symbol -> None:
 """点号分隔的标识符（如 django.db.models）应被识别为代码符号，不触发"全小写"诊断。"""
 diag = _diagnose_empty_search(
 query="user.login.handler",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=1,
 )
 assert diag["query_analysis"]["has_dotted_identifier"] is True
 assert diag["query_analysis"]["is_pure_lowercase_words"] is False
 issues_text = str(diag["issues"])
 assert "全是小写自然语言词" not in issues_text
def test_diagnose_repro_user_reported_case -> None:
 """复现用户上报的真实 case，验证诊断给出正确指引。"""
 diag = _diagnose_empty_search(
 query="studyRoom views classroom report floor friends shareRoom studying fighting",
 min_score=0.5,
 l3_top_score=None,
 l3_raw_count=0,
 searched_repos=2,
 )
 issues_str = " ".join(diag["issues"])
 suggestions_str = " ".join(diag["suggestions"])
 # 关键诊断点 1：识别出多概念混搜
 assert "9 个" in issues_str
 assert "灾难性差" in issues_str
 # 关键诊断点 2：给出可执行建议（拆 query）
 assert "拆成" in suggestions_str
 # 建议里应该包含原 query 里的具体词作为示例（让 LLM 直接抄）
 assert "studyRoom" in suggestions_str or "views" in suggestions_str
