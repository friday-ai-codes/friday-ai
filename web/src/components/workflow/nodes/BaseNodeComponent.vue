<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Handle, Position } from '@vue-flow/core'
import { computed } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
interface Props extends NodeProps {
 icon?: any
 badge?: string
 badgeColor?: 'blue' | 'green' | 'purple' | 'orange' | 'cyan'
 theme?: 'default' | 'ai' | 'feishu' | 'trigger' | 'action'
}
const props = defineProps<Props>
const nodeTypesStore = useNodeTypesStore
const isSelected = computed( => props.selected)
// 判断是否是触发器节点（触发器没有输入 Handle）
const isTrigger = computed( => {
 const nodeType = props.data?.node_type || props.type || ''
 return nodeType.includes('trigger')
})
// 获取节点类型定义
const nodeTypeDef = computed( => {
 const nodeType = props.data?.node_type || props.type
 if (!nodeType) return null
 return nodeTypesStore.getNodeType(nodeType)
})
// 输入端口
const inputPorts = computed( => nodeTypeDef.value?.inputs || )
// 输出端口
const outputPorts = computed( => nodeTypeDef.value?.outputs || )
// 是否显示多端口（端口数 > 1 时显示标签）
const hasMultipleInputs = computed( => inputPorts.value.length > 1)
const hasMultipleOutputs = computed( => outputPorts.value.length > 1)
// 主题样式类
const themeClasses = computed( => {
 const themes: Record<string, string> = {
 default: '',
 ai: 'node-card--ai',
 feishu: 'node-card--feishu',
 trigger: 'node-card--trigger',
 action: 'node-card--action',
 }
 return themes[props.theme || 'default'] || ''
})
// Badge 颜色映射
const badgeClasses = computed( => {
 const colorMap: Record<string, string> = {
 blue: 'bg-primary/10 text-primary',
 green: 'bg-emerald-500/10 text-emerald-600',
 purple: 'bg-gradient-to-r from-violet-500 to-purple-500 text-white',
 orange: 'bg-amber-500/10 text-amber-600',
 cyan: 'bg-cyan-500/10 text-cyan-600',
 }
 return colorMap[props.badgeColor || 'blue']
})
const iconClasses = computed( => {
 const colorMap: Record<string, string> = {
 blue: 'bg-gradient-to-br from-blue-500/20 to-cyan-400/10 text-blue-500',
 green: 'bg-gradient-to-br from-emerald-500/20 to-teal-400/10 text-emerald-500',
 purple: 'bg-gradient-to-br from-violet-500/20 to-purple-400/10 text-violet-500',
 orange: 'bg-gradient-to-br from-amber-500/20 to-orange-400/10 text-amber-500',
 cyan: 'bg-gradient-to-br from-cyan-500/20 to-blue-400/10 text-cyan-500',
 }
 return colorMap[props.badgeColor || 'blue']
})
</script>
<template>
 <div class="workflow-node">
 <!-- 输入端口（多端口模式） -->
 <div v-if="!isTrigger && hasMultipleInputs" class="port-group port-group--top">
 <div v-for="port in inputPorts":key="port.name" class="port-item">
 <Handle
 type="target":id="port.name":position="Position.Top"
 class="port-handle"
 />
 <span class="port-label port-label--top">{{ port.label }}</span>
 </div>
 </div>
 <!-- 输入端口（单端口模式） -->
 <Handle
 v-else-if="!isTrigger"
 type="target":position="Position.Top"
 />
 <!-- 节点内容 -->
 <div
 class="node-card":class="[themeClasses, { 'node-card--selected': isSelected }]"
 >
 <!-- Header -->
 <div class="node-header">
 <div v-if="icon" class="node-icon":class="iconClasses">
 <component:is="icon" class="w-4 " />
 </div>
 <slot name="icon" />
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
 <!-- 输出端口（多端口模式） -->
 <div v-if="hasMultipleOutputs" class="port-group port-group--bottom">
 <div v-for="port in outputPorts":key="port.name" class="port-item">
 <span class="port-label port-label--bottom">{{ port.label }}</span>
 <Handle
 type="source":id="port.name":position="Position.Bottom"
 class="port-handle"
 />
 </div>
 </div>
 <!-- 输出端口（单端口模式） -->
 <Handle
 v-else
 type="source":position="Position.Bottom"
 />
 </div>
</template>
<style>
/**
 * Vue Flow 节点样式
 * 使用项目主题配色 (main.css @theme 变量)
 * 玻璃拟态风格
 */
/* 节点容器 - 必须 relative 以正确定位 Handle */
.workflow-node {
 position: relative;
}
/* 节点卡片 - 玻璃拟态风格 */
.workflow-node .node-card {
 min-width: 200px;
 max-width: 280px;
 padding: 12px 14px;
 background: color-mix(in srgb, var(--color-card, #fff) 90%, transparent);
 backdrop-filter: blur(8px);
 border: 2px solid color-mix(in srgb, var(--color-border, hsl(219 30% 85%)) 60%, transparent);
 border-radius: 16px;
 box-shadow:
 0 4px 6px -1px rgb(0 0 0 / 0.05),
 0 2px 4px -2px rgb(0 0 0 / 0.05);
 transition:
 border-color 0.2s ease,
 box-shadow 0.3s ease,
 transform 0.2s ease;
}
.workflow-node .node-card:hover {
 border-color: color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 50%, transparent);
 box-shadow:
 0 10px 15px -3px rgb(0 0 0 / 0.08),
 0 4px 6px -4px rgb(0 0 0 / 0.05),
 0 0 0 1px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 10%, transparent);
 transform: translateY(-1px);
}
.workflow-node .node-card--selected {
 border-color: var(--color-primary, hsl(213 47% 47%));
 box-shadow:
 0 0 0 3px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 20%, transparent),
 0 10px 25px -5px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 15%, transparent);
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
 width: 32px;
 height: 32px;
 border-radius: 10px;
 flex-shrink: 0;
}
.workflow-node .node-title {
 flex: 1;
 font-size: 14px;
 font-weight: 600;
 color: var(--color-foreground, hsl(212 64% 19%));
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}
.workflow-node .node-badge {
 font-size: 10px;
 font-weight: 500;
 padding: 3px 10px;
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
/* ========== 多端口布局 ========== */
.workflow-node .port-group {
 display: flex;
 justify-content: space-around;
 gap: 8px;
 position: absolute;
 left: 50%;
 transform: translateX(-50%);
 z-index: 1;
}
.workflow-node .port-group--top {
 top: -20px;
}
.workflow-node .port-group--bottom {
 bottom: -20px;
}
.workflow-node .port-item {
 display: flex;
 flex-direction: column;
 align-items: center;
 position: relative;
}
.workflow-node .port-label {
 font-size: 9px;
 color: var(--color-muted-foreground, hsl(212 40% 40%));
 white-space: nowrap;
 background: var(--color-card, #fff);
 padding: 1px 4px;
 border-radius: 4px;
 opacity: 0;
 transition: opacity 0.15s ease;
}
.workflow-node:hover .port-label {
 opacity: 1;
}
.workflow-node .port-label--top {
 margin-top: 2px;
}
.workflow-node .port-label--bottom {
 margin-bottom: 2px;
}
/* Handle 样式 - 使用 Vue Flow 变量 + 项目主题色 */
.workflow-node .vue-flow__handle {
 width: 14px;
 height: 14px;
 background: var(--color-muted-foreground, hsl(212 40% 40%));
 border: 3px solid var(--color-card, #fff);
 border-radius: 50%;
 box-shadow: 0 2px 4px rgb(0 0 0 / 0.1);
 transition:
 background-color 0.15s ease,
 box-shadow 0.15s ease,
 transform 0.15s ease;
}
.workflow-node .vue-flow__handle:hover {
 background: var(--color-primary, hsl(213 47% 47%));
 box-shadow:
 0 0 0 4px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 25%, transparent),
 0 2px 8px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 30%, transparent);
}
.workflow-node .vue-flow__handle.connecting,
.workflow-node .vue-flow__handle.valid {
 background: var(--color-primary, hsl(213 47% 47%));
}
/* Handle 位置微调 */
.workflow-node .vue-flow__handle-top {
 top: -7px;
}
.workflow-node .vue-flow__handle-bottom {
 bottom: -7px;
}
/* 多端口模式下的 Handle */
.workflow-node .port-item .vue-flow__handle {
 position: relative;
 top: auto;
 bottom: auto;
}
/* ========== 主题变体 ========== */
/* AI 主题 - 科技感渐变边框 */
.workflow-node .node-card--ai {
 background: linear-gradient(
 135deg,
 color-mix(in srgb, var(--color-card, #fff) 95%, hsl(270 80% 60%)),
 color-mix(in srgb, var(--color-card, #fff) 90%, hsl(280 70% 50%))
 );
 border-color: color-mix(in srgb, hsl(270 70% 60%) 40%, transparent);
}
.workflow-node .node-card--ai:hover {
 border-color: hsl(270 70% 55%);
 box-shadow:
 0 0 20px color-mix(in srgb, hsl(270 80% 60%) 20%, transparent),
 0 10px 25px -5px color-mix(in srgb, hsl(270 80% 60%) 15%, transparent);
}
.workflow-node .node-card--ai.node-card--selected {
 border-color: hsl(270 70% 55%);
 box-shadow:
 0 0 0 3px color-mix(in srgb, hsl(270 80% 60%) 25%, transparent),
 0 0 30px color-mix(in srgb, hsl(270 80% 60%) 20%, transparent);
}
/* 飞书主题 - 飞书蓝色调 */
.workflow-node .node-card--feishu {
 background: linear-gradient(
 135deg,
 color-mix(in srgb, var(--color-card, #fff) 95%, hsl(214 100% 50%)),
 color-mix(in srgb, var(--color-card, #fff) 92%, hsl(214 90% 45%))
 );
 border-color: color-mix(in srgb, hsl(214 100% 50%) 35%, transparent);
}
.workflow-node .node-card--feishu:hover {
 border-color: hsl(214 100% 50%);
 box-shadow:
 0 0 15px color-mix(in srgb, hsl(214 100% 50%) 15%, transparent),
 0 10px 20px -5px color-mix(in srgb, hsl(214 100% 50%) 12%, transparent);
}
.workflow-node .node-card--feishu.node-card--selected {
 border-color: hsl(214 100% 50%);
 box-shadow:
 0 0 0 3px color-mix(in srgb, hsl(214 100% 50%) 25%, transparent),
 0 0 25px color-mix(in srgb, hsl(214 100% 50%) 15%, transparent);
}
/* 触发器主题 - 蓝绿渐变 */
.workflow-node .node-card--trigger {
 background: linear-gradient(
 135deg,
 color-mix(in srgb, var(--color-card, #fff) 95%, hsl(200 80% 50%)),
 color-mix(in srgb, var(--color-card, #fff) 92%, hsl(180 70% 45%))
 );
 border-color: color-mix(in srgb, hsl(190 75% 50%) 35%, transparent);
}
.workflow-node .node-card--trigger:hover {
 border-color: hsl(190 75% 45%);
}
.workflow-node .node-card--trigger.node-card--selected {
 border-color: hsl(190 75% 45%);
 box-shadow:
 0 0 0 3px color-mix(in srgb, hsl(190 75% 50%) 25%, transparent),
 0 0 20px color-mix(in srgb, hsl(190 75% 50%) 15%, transparent);
}
/* 操作主题 - 绿色调 */
.workflow-node .node-card--action {
 background: linear-gradient(
 135deg,
 color-mix(in srgb, var(--color-card, #fff) 95%, hsl(160 70% 45%)),
 color-mix(in srgb, var(--color-card, #fff) 92%, hsl(170 60% 40%))
 );
 border-color: color-mix(in srgb, hsl(160 65% 45%) 35%, transparent);
}
.workflow-node .node-card--action:hover {
 border-color: hsl(160 65% 40%);
}
.workflow-node .node-card--action.node-card--selected {
 border-color: hsl(160 65% 40%);
 box-shadow:
 0 0 0 3px color-mix(in srgb, hsl(160 65% 45%) 25%, transparent),
 0 0 20px color-mix(in srgb, hsl(160 65% 45%) 15%, transparent);
}
/* ========== Dragging State ========== */
/* Dragging state - "picked up" feel */
.vue-flow__node.dragging .node-card {
 transform: scale(1.05);
 box-shadow:
 0 20px 25px -5px rgb(0 0 0 / 0.15),
 0 8px 10px -6px rgb(0 0 0 / 0.1);
 z-index: 1000;
}
/* Improve performance during drag */
.vue-flow__node.dragging {
 will-change: transform;
}
.vue-flow__node.dragging .node-card {
 /* Temporarily reduce backdrop-filter complexity during drag */
 backdrop-filter: blur(4px);
}
/* Smooth transition for scale on drag start/stop */
.workflow-node .node-card {
 transition:
 border-color 0.2s ease,
 box-shadow 0.3s ease,
 transform 0.15s ease;
}
/* ========== Collision Warning Styles ========== */
/* Collision warning - approaching 30px boundary */
.vue-flow__node.collision-warning .node-card {
 border-color: hsl(0 84% 60%); /* red-500 */
 box-shadow:
 0 0 0 3px hsl(0 84% 60% / 0.3),
 0 0 15px hsl(0 84% 60% / 0.2);
 animation: pulse-warning 0.5s ease-in-out infinite alternate;
}
@keyframes pulse-warning {
 from {
 box-shadow:
 0 0 0 3px hsl(0 84% 60% / 0.2),
 0 0 10px hsl(0 84% 60% / 0.15);
 }
 to {
 box-shadow:
 0 0 0 5px hsl(0 84% 60% / 0.35),
 0 0 20px hsl(0 84% 60% / 0.25);
 }
}
/* Collision blocked state */
.vue-flow__node.collision-blocked .node-card {
 border-color: hsl(0 84% 50%);
 cursor: not-allowed;
}
/* Collision warning during drag */
.vue-flow__node.dragging.collision-warning .node-card {
 border-color: hsl(0 84% 60%);
 box-shadow:
 0 0 0 4px hsl(0 84% 60% / 0.4),
 0 0 25px hsl(0 84% 60% / 0.3),
 0 20px 25px -5px rgb(0 0 0 / 0.15);
}
</style>
