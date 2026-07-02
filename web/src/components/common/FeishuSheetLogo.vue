<script setup lang="ts">
// 飞书多维表格（Base）风格图标。互联网上无干净可用的官方「飞书多维表格」独立 SVG
// （allogo 等只有通用飞书品牌 logo），故按飞书品牌配色（蓝 #3370ff / 青 #00d6b9 /
// 橙 #ff811a）绘制一个可清晰识别为「表格」的网格图标，与 FeishuLogo（文档）区分。
// class 通过 attrs 透传到 <svg>。
defineOptions({ inheritAttrs: true })
</script>

<template>
  <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="6" y="8" width="36" height="32" rx="6" fill="#fff" stroke="#3370ff" stroke-width="2.4" />
    <!-- 表头行 -->
    <path d="M6 14a6 6 0 0 1 6-6h24a6 6 0 0 1 6 6v3H6z" fill="#3370ff" />
    <!-- 网格线 -->
    <line x1="18" y1="17" x2="18" y2="40" stroke="#3370ff" stroke-width="2" />
    <line x1="30" y1="17" x2="30" y2="40" stroke="#3370ff" stroke-width="2" />
    <line x1="6" y1="28.5" x2="42" y2="28.5" stroke="#3370ff" stroke-width="2" />
    <!-- 多维彩色单元格 -->
    <rect x="8.5" y="19" width="7.5" height="7" rx="1.4" fill="#00d6b9" />
    <rect x="20" y="30.5" width="8" height="7" rx="1.4" fill="#ff811a" />
  </svg>
</template>
