<script setup lang="ts">
import { Clock, Copy, GitBranch } from 'lucide-vue-next'
import { Handle, Position, type NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
const props = defineProps<NodeProps>
const isSelected = computed( => props.selected)
const getIcon = (type: string) => {
 switch (type) {
 case 'condition': return GitBranch
 case 'delay': return Clock
 case 'parallel': return Copy
 default: return GitBranch
 }
}
// 获取输出 Handles（条件节点有多个分支）
const outputHandles = computed( => {
 const nodeType = props.data?.node_type || props.type
 if (nodeType === 'condition') {
 const conditions = props.data?.config?.conditions ||
 const handles = conditions.map((c: any, i: number) => ({
 id: `branch_${i}`,
 label: c.name || `分支 ${i + 1}`,
 }))
 handles.push({ id: 'else', label: '否则' })
 return handles
 }
 if (nodeType === 'parallel') {
 return [
 { id: 'fork', label: '分叉' },
 { id: 'join', label: '汇合' },
 ]
 }
 return [{ id: 'default', label: '输出' }]
})
const hasMultipleHandles = computed( => outputHandles.value.length > 1)
</script>
<template>
 <div class="workflow-node workflow-node--control">
 <!-- Input Handle -->
 <Handle
 type="target":position="Position.Left"
 />
 <!-- 节点内容 -->
 <div
 class="node-card":class="{ 'node-card--selected': isSelected }"
 >
 <!-- Header -->
 <div class="node-header">
 <div class="node-icon">
 <component:is="getIcon(props.data?.node_type || props.type || '')" class="w-4 " />
 </div>
 <span class="node-title">
 {{ label || props.data?.name || 'Untitled' }}
 </span>
 <span class="node-badge">
 控制
 </span>
 </div>
 <!-- Body -->
 <div class="node-body">
 <!-- 条件分支预览 -->
 <div v-if="(props.data?.node_type || props.type) === 'condition'" class="space-y-1 mb-2">
 <div
 v-for="handle in outputHandles":key="handle.id"
 class="flex items-center gap-2 text-[10px]"
 >
 <div
 class="w-2 rounded-full":class="handle.id === 'else' ? 'bg-gray-400': 'bg-purple-500'"
 />
 <span>{{ handle.label }}</span>
 </div>
 </div>
 <!-- 延迟配置预览 -->
 <div v-else-if="(props.data?.node_type || props.type) === 'delay'" class="font-mono text-[10px] bg-secondary px-1.5 py-0.5 rounded inline-block mb-2">
 {{ props.data?.config?.duration || 60 }}s
 </div>
 <p class="line-clamp-2">{{ props.data?.description || '控制流节点' }}</p>
 </div>
 </div>
 <!-- Output Handles -->
 <!-- 单个输出 -->
 <Handle
 v-if="!hasMultipleHandles"
 type="source":position="Position.Right"
 />
 <!-- 多个输出（条件分支） -->
 <template v-else>
 <Handle
 v-for="(handle, index) in outputHandles":key="handle.id"
 type="source":position="Position.Right":id="handle.id":style="{ top: `${((index + 1) / (outputHandles.length + 1)) * 100}%` }"
 class="workflow-node__handle--multi"
 />
 </template>
 </div>
</template>
<style>
/**
 * Control Node 样式
 * 继承 BaseNodeComponent 的样式，添加紫色主题
 */
.workflow-node--control {
 position: relative;
}
.workflow-node--control .node-card {
 min-width: 200px;
 max-width: 280px;
 padding: 12px 14px;
 background: var(--color-card, #fff);
 border: 2px solid var(--color-border, hsl(219 30% 85%));
 border-radius: var(--radius, 0.5rem);
 box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
 transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.workflow-node--control .node-card:hover {
 border-color: var(--color-primary, hsl(213 47% 47%));
}
.workflow-node--control .node-card--selected {
 border-color: var(--color-primary, hsl(213 47% 47%));
 box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 20%, transparent);
}
.workflow-node--control .node-header {
 display: flex;
 align-items: center;
 gap: 8px;
 margin-bottom: 8px;
}
.workflow-node--control .node-icon {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 28px;
 height: 28px;
 border-radius: 6px;
 flex-shrink: 0;
 background: rgb(147 51 234 / 0.1);
 color: rgb(147 51 234);
}
.workflow-node--control .node-title {
 flex: 1;
 font-size: 14px;
 font-weight: 500;
 color: var(--color-foreground, hsl(212 64% 19%));
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}
.workflow-node--control .node-badge {
 font-size: 10px;
 font-weight: 500;
 padding: 2px 8px;
 border-radius: 9999px;
 flex-shrink: 0;
 background: rgb(147 51 234 / 0.1);
 color: rgb(147 51 234);
}
.workflow-node--control .node-body {
 font-size: 12px;
 color: var(--color-muted-foreground, hsl(212 40% 40%));
 line-height: 1.5;
}
/* Handle 样式 */
.workflow-node--control .vue-flow__handle {
 width: 14px;
 height: 14px;
 background: var(--color-muted-foreground, hsl(212 40% 40%));
 border: 3px solid var(--color-card, #fff);
 border-radius: 50%;
 transition: background-color 0.15s ease, box-shadow 0.15s ease;
}
.workflow-node--control .vue-flow__handle:hover {
 background: var(--color-primary, hsl(213 47% 47%));
 box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary, hsl(213 47% 47%)) 30%, transparent);
}
.workflow-node--control .vue-flow__handle-left {
 left: -7px;
}
.workflow-node--control .vue-flow__handle-right {
 right: -7px;
}
/* 多个 Handle 的特殊定位 */
.workflow-node--control .workflow-node__handle--multi {
 position: absolute;
 right: -7px;
 transform: translateY(-50%);
}
</style>
