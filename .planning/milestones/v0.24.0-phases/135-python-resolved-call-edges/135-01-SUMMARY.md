---
phase: 135-python-resolved-call-edges
plan: 01
status: complete
commit: bda60d09
requirements: [EDGE-04, EDGE-05]
---

# 135-01 摘要

Python resolver 支持 module alias member、from-import alias direct call、唯一 imported/local
class member。带 qualifier 的调用不再先命中同文件裸名；动态 receiver、缺 MRO 证据或多候选
保持 unresolved/ambiguous。专项与既有 resolver 合计 22 项回归通过。
