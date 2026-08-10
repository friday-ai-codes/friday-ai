# IMPACT-03 复验记录

## 处置：诚实延期

真实样本统计：

- `CrossRepoApiCall` = **0**
- `ApiCallSite` = **0**
- `ApiWrapper` = **0**

结论：**仍为零 / 不可测**。

- Phase 122 `test_cross_repo_hop.py` 仅覆盖合成数据四分支，
  **不得**表述为「跨仓 impact 已在真实数据上验证」。
- 产出器缺口 vs 仅缺运行时：镜像侧 Node/gopls 已由 127-02 补齐，
  但 kill-switch 默认仍 False，且本环境未完成能产生跨仓边的索引重建；
  倾向 **产出器/索引未跑通**（非单纯缺二进制），需 follow-up：
  在代表性前后端仓上开启 LSP、重建索引、再跑本命令。
- Follow-up：建议独立 quick/phase 在有真实 `CrossRepoApiCall` 后复验四分支
  并测量 `(file_path, name)` 二次解析命中率。
