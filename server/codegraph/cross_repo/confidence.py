"""match_confidence 评分函数 —— Phase。
评分规则：
- 1.0: http_method 一致 + url_path 归一化后完全一致
- 0.7: url_path 归一化后一致，但 http_method 不同（或一方为 ANY）
- 0.4: url_path 归一化前缀匹配 ≥ 2 path segments，method 任意
- 0.0: 无匹配
"""
from __future__ import annotations
from codegraph.cross_repo.path_normalizer import normalize_url_path
#: 代表"任意 method"的标记（URL 匹配时忽略 method 约束）
ANY_METHOD = "ANY"
#: 最低匹配阈值，低于此分不写入 CrossRepoApiCall
MIN_CONFIDENCE: float = 0.4
def compute_confidence(
 wrapper_method: str,
 wrapper_path: str,
 endpoint_method: str,
 endpoint_path: str,
) -> float:
 """计算 ApiWrapper 与 Endpoint 的匹配置信度。
 Args:
 wrapper_method: ApiWrapper 的 HTTP method（如 "GET"）
 wrapper_path: ApiWrapper 的 url_path_pattern（原始，函数内部归一化）
 endpoint_method: Endpoint 的 HTTP method（如 "GET"）
 endpoint_path: Endpoint 的 url_path（原始，函数内部归一化）
 Returns:
 float: 0.0 / 0.4 / 0.7 / 1.0
 Examples:
 >>> compute_confidence("GET", "/users/:id", "GET", "/users/<int:pk>")
 1.0
 >>> compute_confidence("POST", "/users/{id}", "GET", "/users/:id")
 0.7
 >>> compute_confidence("GET", "/users/:id/profile", "GET", "/users/:id/settings")
 0.4
 >>> compute_confidence("GET", "/orders", "GET", "/users")
 0.0
 """
 norm_w = normalize_url_path(wrapper_path)
 norm_e = normalize_url_path(endpoint_path)
 w_method = wrapper_method.upper
 e_method = endpoint_method.upper
 method_match = (
 w_method == e_method
 or w_method == ANY_METHOD
 or e_method == ANY_METHOD
 )
 # 1.0: 完全匹配（method + path 均一致）
 if method_match and norm_w == norm_e:
 return 1.0
 # 0.7: path-only 匹配（path 一致，method 不同）
 if norm_w == norm_e:
 return 0.7
 # 0.4: 前缀匹配 ≥ 2 segments
 w_segs = [s for s in norm_w.split("/") if s]
 e_segs = [s for s in norm_e.split("/") if s]
 if len(w_segs) >= 2 and len(e_segs) >= 2 and w_segs[:2] == e_segs[:2]:
 return 0.4
 return 0.0
def passes_threshold(confidence: float) -> bool:
 """是否达到最低置信度阈值（>= MIN_CONFIDENCE = 0.4）。"""
 return confidence >= MIN_CONFIDENCE
