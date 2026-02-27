<script setup lang="ts">
/**
 * BaseWorkflowNode - 所有自定义节点的基础壳组件
 *
 * 负责：glassmorphism 外观、动态 Handle 渲染、选中态高亮。
 * 图标和颜色从 nodeVisuals 统一数据源获取。
 */
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { NodeToolbar } from '@vue-flow/node-toolbar'
import { Check, Copy, Loader2, Trash2, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getDefaultPortsForNodeType } from '~/components/workflow/x6/ports/portGroups'
import { generateShortId } from '~/utils/shortId'
import { getNodeVisual } from './nodeVisuals'
import { useNodeStyle, getExecutionStyle, type NodeExecutionStatus } from './composables/useNodeStyle'
const props = withDefaults(defineProps<{
 id: string
 data: {
 name: string
 nodeType: string
 disabled?: boolean
 [key: string]: unknown
 }
 selected?: boolean
 /** 隐藏指定方向的 Handle，供 DynamicPortNode 等自行管理端口 */
 hideHandles?: 'input' | 'output' | 'both' | 'none'
}>, { hideHandles: 'none' })
const store = useWorkflowsStore
const { getSelectedNodes } = useVueFlow
const visual = computed( => getNodeVisual(props.data.nodeType))
const style = computed( => useNodeStyle(visual.value.color).value)
/** 执行状态：由外部通过 data.executionStatus 驱动 */
const executionStatus = computed( =>
 (props.data.executionStatus as NodeExecutionStatus) ?? 'idle',
)
const execStyle = computed( => getExecutionStyle(executionStatus.value))
const ports = computed( => getDefaultPortsForNodeType(props.data.nodeType))
const inputPorts = computed( => ports.value.filter(p => p.group === 'input'))
const outputPorts = computed( => ports.value.filter(p => p.group === 'output'))
/** 多选时隐藏单节点工具栏，改用画布级统一工具栏 */
const isMultiSelect = computed( => getSelectedNodes.value.length > 1)
/** 多端口时均匀分布的 left 百分比 */
function portLeft(index: number, total: number): string {
 if (total <= 1) return '50%'
 return `${((index + 1) / (total + 1)) * 100}%`
}
function handleDelete {
 store.removeNode(props.id)
}
function handleCopy {
 const currentNode = store.nodes.find(n => n.id === props.id)
 if (!currentNode) return
 const newNode = {
 ...JSON.parse(JSON.stringify(currentNode)),
 id: crypto.randomUUID,
 shortId: generateShortId,
 position: {
 x: (currentNode.position?.x ?? 0) + 50,
 y: (currentNode.position?.y ?? 0) + 50,
 },
 }
 newNode.name = `${currentNode.name} (副本)`
 store.addNode(newNode)
}
</script>
<template>
 <!-- 单选浮动工具栏：仅单选时显示，多选时隐藏（由画布级统一工具栏接管） -->
 <NodeToolbar:is-visible="selected && !isMultiSelect":position="Position.Top":offset="10"
 >
 <div class="flex gap-1 bg-card/90 backdrop-blur-sm border border-border/50 rounded-xl shadow-lg">
 <button
 class=".5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
 title="复制节点"
 @click.stop="handleCopy"
 >
 <Copy class="w-3.5 .5" />
 </button>
 <button
 class=".5 rounded-lg hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
 title="删除节点"
 @click.stop="handleDelete"
 >
 <Trash2 class="w-3.5 .5" />
 </button>
 </div>
 </NodeToolbar>
 <div
 class="w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl
 transition-all duration-300 group
 hover:shadow-md hover:border-opacity-70":class="[
 execStyle ? execStyle.borderColor: style.borderColor,
 execStyle?.glowClass,
 selected ? `ring-2 ${style.ringColor} shadow-lg`: '',
 data.disabled ? 'grayscale opacity-50': '',
 executionStatus === 'skipped' ? 'opacity-45 grayscale-[0.3]': '',
 ]"
 >
 <!-- Input Handles -->
 <Handle
 v-for="(port, i) in inputPorts"
 v-show="hideHandles !== 'input' && hideHandles !== 'both'":key="port.id":id="port.id"
 type="target":position="Position.Top":style="{ left: portLeft(i, inputPorts.length) }"
 />
 <!-- 头部：图标 + 名称 -->
 <div class="flex items-center gap-2 mb-2">
 <div:class="['bg-gradient-to-br rounded-lg .5', style.iconBg]">
 <slot name="icon">
 <!-- 执行状态图标覆盖：running/success/failed 替换原始图标 -->
 <Loader2 v-if="executionStatus === 'running'" class="w-4 text-blue-500 animate-spin" />
 <Check v-else-if="executionStatus === 'success'" class="w-4 text-emerald-500" />
 <X v-else-if="executionStatus === 'failed'" class="w-4 text-red-500" />
 <component
 v-else:is="visual.icon"
 class="w-4 ":class="[style.iconColor, executionStatus === 'skipped' ? 'opacity-50': '']"
 />
 </slot>
 </div>
 <span class="text-sm font-medium text-foreground truncate">
 {{ data.name }}
 </span>
 </div>
 <!-- 内容 slot -->
 <slot name="content" />
 <!-- Output Handles -->
 <Handle
 v-for="(port, i) in outputPorts"
 v-show="hideHandles !== 'output' && hideHandles !== 'both'":key="port.id":id="port.id"
 type="source":position="Position.Bottom":style="{ left: portLeft(i, outputPorts.length) }"
 />
 </div>
</template>
<style>
/* 执行状态动画 — 不用 scoped，class 名有 node-execution 前缀足够唯一 */
@keyframes execution-pulse {
 0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
 50% { box-shadow: 0 0 12px 4px rgba(59, 130, 246, 0.2); }
}
@keyframes execution-breathe {
 0%, 100% { transform: scale(1); }
 50% { transform: scale(1.02); }
}
.node-execution-running {
 animation: execution-pulse 2s ease-in-out infinite,
 execution-breathe 2s ease-in-out infinite;
}
.node-execution-success {
 box-shadow: 0 0 8px 2px rgba(16, 185, 129, 0.15);
}
.node-execution-failed {
 box-shadow: 0 0 8px 2px rgba(239, 68, 68, 0.15);
}
.node-execution-skipped {
 border-style: dashed;
}
</style>
