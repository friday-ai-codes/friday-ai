<script setup lang="ts">
/**
 * DynamicPortNode - parallel/join 节点的动态端口管理
 *
 * parallel: 动态 source 端口（底部输出）
 * join: 动态 target 端口（顶部输入）
 * 支持 2-5 个端口增删、名称编辑。
 */
import { Handle, Position, useVueFlow } from '@vue-flow/core'
import { GitFork, GitMerge, Plus, X } from 'lucide-vue-next'
import { computed } from 'vue'
import BaseWorkflowNode from './BaseWorkflowNode.vue'

interface Port {
  id: string
  name: string
}

const props = defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    disabled?: boolean
    ports?: Port[]
    [key: string]: unknown
  }
  selected?: boolean
}>()

const { updateNodeData, removeEdges, getEdges } = useVueFlow()

const isParallel = computed(() => props.data.nodeType === 'parallel')

const defaultPorts: Port[] = [
  { id: 'port-1', name: '分支1' },
  { id: 'port-2', name: '分支2' },
]

const ports = computed(() => props.data.ports ?? defaultPorts)

function portTop(index: number, total: number): string {
  if (total <= 1)
    return '50%'
  return `${((index + 1) / (total + 1)) * 100}%`
}

function addPort() {
  if (ports.value.length >= 5)
    return
  const newPorts = [...ports.value, { id: `port-${Date.now()}`, name: `分支${ports.value.length + 1}` }]
  updateNodeData(props.id, { ports: newPorts })
}

function removePort(portId: string) {
  if (ports.value.length <= 2)
    return
  const newPorts = ports.value.filter(p => p.id !== portId)
  // 删除关联边
  const connected = getEdges.value.filter(e =>
    (e.sourceHandle === portId && e.source === props.id)
    || (e.targetHandle === portId && e.target === props.id),
  )
  if (connected.length)
    removeEdges(connected)
  updateNodeData(props.id, { ports: newPorts })
}

function updatePortName(portId: string, name: string) {
  const newPorts = ports.value.map(p => p.id === portId ? { ...p, name } : p)
  updateNodeData(props.id, { ports: newPorts })
}
</script>

<template>
  <BaseWorkflowNode :id="id" :data="data" :selected="selected" :hide-handles="isParallel ? 'output' : 'input'">
    <template #icon>
      <GitFork v-if="isParallel" class="w-4 h-4" />
      <GitMerge v-else class="w-4 h-4" />
    </template>

    <template #content>
      <div class="space-y-1">
        <div
          v-for="port in ports"
          :key="port.id"
          class="flex items-center gap-1"
        >
          <input
            :value="port.name"
            class="flex-1 text-xs bg-transparent border-b border-border/50 text-foreground outline-none focus:border-primary/50 transition-colors"
            @change="updatePortName(port.id, ($event.target as HTMLInputElement).value)"
          >
          <button
            v-if="ports.length > 2"
            class="text-muted-foreground hover:text-destructive transition-colors p-0.5"
            @click="removePort(port.id)"
          >
            <X class="w-3 h-3" />
          </button>
        </div>

        <button
          v-if="ports.length < 5"
          class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors mt-1"
          @click="addPort"
        >
          <Plus class="w-3 h-3" />
          <span>添加端口</span>
        </button>
      </div>
    </template>
  </BaseWorkflowNode>

  <!-- 动态 Handle：横向 L→R——parallel 渲染 source（右侧），join 渲染 target（左侧），沿垂直方向均分 -->
  <Handle
    v-for="(port, i) in ports"
    :id="port.id"
    :key="port.id"
    :type="isParallel ? 'source' : 'target'"
    :position="isParallel ? Position.Right : Position.Left"
    :style="{ top: portTop(i, ports.length) }"
  />
</template>
