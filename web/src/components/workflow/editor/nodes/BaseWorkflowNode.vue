<script setup lang="ts">
/**
 * BaseWorkflowNode - 所有自定义节点的基础壳组件
 *
 * 负责：glassmorphism 外观、动态 Handle 渲染、选中态高亮。
 * 子节点通过 #icon 和 #content slot 注入内容。
 */
import { Handle, Position } from '@vue-flow/core'
import { computed } from 'vue'
import { getNodeDefinition } from '~/types/workflow/registry'
import { getDefaultPortsForNodeType } from '~/components/workflow/x6/ports/portGroups'
import { useNodeStyle } from './composables/useNodeStyle'
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
const nodeDef = computed( => getNodeDefinition(props.data.nodeType))
const style = computed( => useNodeStyle(nodeDef.value?.category ?? '').value)
const ports = computed( => getDefaultPortsForNodeType(props.data.nodeType))
const inputPorts = computed( => ports.value.filter(p => p.group === 'input'))
const outputPorts = computed( => ports.value.filter(p => p.group === 'output'))
/** 多端口时均匀分布的 left 百分比 */
function portLeft(index: number, total: number): string {
 if (total <= 1) return '50%'
 return `${((index + 1) / (total + 1)) * 100}%`
}
</script>
<template>
 <div
 class="w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl
 transition-all duration-200 group
 hover:shadow-md hover:border-opacity-70":class="[
 style.borderColor,
 selected ? `ring-2 ${style.ringColor} shadow-lg`: '',
 data.disabled ? 'grayscale opacity-50': '',
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
 <div class="w-4 " />
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
