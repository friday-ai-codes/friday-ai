"""Frontend API Call Resolver —— 三步推断算法抽取 ApiWrapper + ApiCallSite。
Step 0: 扫描 axios.{get/post/...} 调用 → 自动识别 LowLevelHelper
Step 1: 找调用 LowLevelHelper 的 export function → ApiWrapper，提取 URL
Step 2: volar textDocument/references 反向追踪 → ApiCallSite
JSDoc 富集：@description/@author/@date/yapi URL → ApiWrapper.metadata
"""
