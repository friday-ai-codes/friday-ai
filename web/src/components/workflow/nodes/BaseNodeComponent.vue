<script setup lang="ts">
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
interface Props extends NodeProps {
 icon?: any
 badge?: string
 badgeColor?: 'blue' | 'green' | 'purple' | 'orange'
}
const props = defineProps<Props>
const isSelected = computed( => props.selected)
// 判断是否是触发器节点（触发器没有输入 Handle）
const isTrigger = computed( => {
 const nodeType = props.data?.node_type || props.type || ''
 return nodeType.includes('trigger')
})
// Badge 颜色映射
const badgeClasses = computed( => {
 const colorMap = {
 blue: 'bg-primary/10 text-primary',
 green: 'bg-green-500/10 text-green-600',
 purple: 'bg-purple-500/10 text-purple-600',
 orange: 'bg-orange-500/10 text-orange-600',
 }
 return colorMap[props.badgeColor || 'blue']
})
const iconClasses = computed( => {
 const colorMap = {
 blue: 'bg-primary/10 text-primary',
 green: 'bg-green-500/10 text-green-600',
 purple: 'bg-purple-500/10 text-purple-600',
 orange: 'bg-orange-500/10 text-orange-600',
 }
 return colorMap[props.badgeColor || 'blue']
})
</script>
<template>
 <div class="workflow-node">
 <!-- Input Handle (Target) - 非触发器节点显示 -->
 <Handle
 v-if="!isTrigger"
 type="target":position="Position.Left"
 />
 <!-- 节点内容 -->
 <div
 class="node-card":class="{ 'node-card--selected': isSelected }"
 >
 <!-- Header -->
 <div class="node-header">
 <div v-if="icon" class="node-icon":class="iconClasses">
 <component:is="icon" class="w-4 " />
 </div>
 <span class="node-title">
 {{ label || data?.name || 'Untitled' }}
 </span>
 <span v-if="badge" class="node-badge":class="badgeClasses">
 {{ badge }}
 </span>
 </div>
 <!-- Body -->
 <div class="node-body">
 <slot>
 <span v-if="data?.description">{{ data.description }}</span>
 <span v-else class="node-placeholder">点击配置节点</span>
 </slot>
 </div>
 </div>
 <!-- Output Handle (Source) -->
 <Handle
 type="source":position="Position.Right"
 />
 </div>
</template>
<style>
/**
 * Vue Flow 节点样式
 * 使用项目主题配色 (main.css @theme 变量)
 */
/* 节点容器 - 必须 relative 以正确定位 Handle */
.workflow-node {
 position: relative;
}
/* 节点卡片 */
.workflow-node .node-card {
 min-width: 200px;
 max-width: 280px;
 padding: 12px 14px;
 background: var(--color-card, #fff);
 border: 2px solid var(--color-border, hsl(219 30% 85%));
 border-radius: var(--radius, 0.5rem);
 box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
 transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.workflow-node .node-card:hover {
 border-color: var(--color-primary, hsl(213 47% 47%));
}
.workflow-node .node-card--selected {
 border-color: var(--color-primary, hsl(213 47% 47%));
 box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 20%, transparent);
}
/* Header */
.workflow-node .node-header {
 display: flex;
 align-items: center;
 gap: 8px;
 margin-bottom: 8px;
}
.workflow-node .node-icon {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 28px;
 height: 28px;
 border-radius: 6px;
 flex-shrink: 0;
}
.workflow-node .node-title {
 flex: 1;
 font-size: 14px;
 font-weight: 500;
 color: var(--color-foreground, hsl(212 64% 19%));
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}
.workflow-node .node-badge {
 font-size: 10px;
 font-weight: 500;
 padding: 2px 8px;
 border-radius: 9999px;
 flex-shrink: 0;
}
/* Body */
.workflow-node .node-body {
 font-size: 12px;
 color: var(--color-muted-foreground, hsl(212 40% 40%));
 line-height: 1.5;
}
.workflow-node .node-placeholder {
 opacity: 0.5;
 font-style: italic;
}
/* Handle 样式 - 使用 Vue Flow 变量 + 项目主题色 */
.workflow-node .vue-flow__handle {
 width: 14px;
 height: 14px;
 background: var(--color-muted-foreground, hsl(212 40% 40%));
 border: 3px solid var(--color-card, #fff);
 border-radius: 50%;
 /* 不使用 transform，避免漂移 */
 transition: background-color 0.15s ease, box-shadow 0.15s ease;
}
.workflow-node .vue-flow__handle:hover {
 background: var(--color-primary, hsl(213 47% 47%));
 box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 30%, transparent);
}
.workflow-node .vue-flow__handle.connecting,
.workflow-node .vue-flow__handle.valid {
 background: var(--color-primary, hsl(213 47% 47%));
}
/* Handle 位置微调 */
.workflow-node .vue-flow__handle-left {
 left: -7px;
}
.workflow-node .vue-flow__handle-right {
 right: -7px;
}
</style>
