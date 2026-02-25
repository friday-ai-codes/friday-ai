<script setup lang="ts">
import type { Node } from '@antv/x6'
import { computed, inject, ref } from 'vue'
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6ParallelNode - parallel/join 节点组件，支持动态端口增删。
 *
 * parallel 模式：动态增删输出端口（最少 2 个）
 * join 模式：动态增删输入端口（最少 2 个）
 * 通过 node data 中的 node_type 区分方向。
 */
const getNode = inject< => Node>('getNode')!
const node = getNode
const nodeData = ref<Record<string, unknown>>(node.getData || {})
node.on('change:data', ({ current }: { current: Record<string, unknown> }) => {
 nodeData.value = current || {}
})
const isParallel = computed( => nodeData.value.node_type === 'parallel')
const dynamicPorts = computed( => {
 const group = isParallel.value ? 'output': 'input'
 return node.getPorts.filter(p => p.group === group)
})
const canRemove = computed( => dynamicPorts.value.length > 2)
function addPort {
 const idx = dynamicPorts.value.length
 if (isParallel.value) {
 node.addPort({
 id: `output-${idx}`,
 group: 'output',
 attrs: { circle: { 'data-port-name': `branch_${idx}` } },
 })
 // 同步 branches 数组
 const branches = [...(nodeData.value.branches as string || )]
 branches.push(`branch_${idx}`)
 node.setData({ ...nodeData.value, branches }, { overwrite: true })
 } else {
 node.addPort({
 id: `input-${idx}`,
 group: 'input',
 attrs: { circle: { 'data-port-name': `input_${idx}` } },
 })
 }
}
function removePort {
 if (!canRemove.value) return
 const ports = dynamicPorts.value
 const last = ports[ports.length - 1]
 if (last?.id) {
 node.removePort(last.id)
 }
 if (isParallel.value) {
 const branches = [...(nodeData.value.branches as string || )]
 branches.pop
 node.setData({ ...nodeData.value, branches }, { overwrite: true })
 }
}
</script>
<template>
 <X6BaseNode v-slot="{ label, description, shortId }">
 <div class="flex items-center gap-3 px-4 py-3">
 <!-- Icon with purple gradient background -->
 <div class="shrink-0 .5 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-400/10">
 <span:class="isParallel ? 'icon-[lucide--git-fork]': 'icon-[lucide--merge]'"
 class="text-lg text-violet-500"
 />
 </div>
 <div class="flex-1 min-w-0">
 <div class="font-medium text-sm truncate":title="label">
 {{ label }}
 </div>
 <div
 v-if="description"
 class="text-xs text-muted-foreground truncate mt-0.5":title="description"
 >
 {{ description }}
 </div>
 <div class="text-[10px] text-muted-foreground/60 font-mono mt-0.5 truncate":title="shortId">
 {{ shortId }}
 </div>
 </div>
 </div>
 <!-- Dynamic port +/- buttons -->
 <div class="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center gap-1">
 <button
 class="w-5 rounded-full bg-primary/10 hover:bg-primary/20 text-primary text-xs flex items-center justify-center transition-colors"
 title="添加端口"
 @click.stop="addPort"
 >
 +
 </button>
 <button
 class="w-5 rounded-full bg-primary/10 hover:bg-primary/20 text-primary text-xs flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
 title="移除端口":disabled="!canRemove"
 @click.stop="removePort"
 >
 -
 </button>
 </div>
 </X6BaseNode>
</template>
