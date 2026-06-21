<script setup lang="ts">
import type { NodeType } from '~/stores/useNodeTypesStore'
/**
 * NodeInsertMenu - 可复用节点选择 popover
 *
 * 供「边中点 +」与「节点 Handle 旁 +」共用：列出可用节点（按分类分组、可搜索），
 * 选中后 emit('select', nodeType) 并关闭。纯 UI + 选择事件，不直接改 store，
 * 插入逻辑由调用方处理以保持可复用。
 */
import { Plus } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { getNodeVisual } from './nodes/nodeVisuals'

const props = defineProps<{ triggerClass?: string }>()
const emit = defineEmits<{ (e: 'select', nodeType: string): void }>()

const nodeTypesStore = useNodeTypesStore()
const open = ref(false)
const search = ref('')

const CATEGORY_LABELS: Record<string, string> = {
  trigger: '触发器',
  action: '操作',
  control: '控制流',
  integration: '集成',
  ai: 'AI',
}

const groups = computed(() => {
  const byCat = nodeTypesStore.nodeTypesByCategory
  const q = search.value.trim().toLowerCase()
  const result: { category: string, label: string, items: NodeType[] }[] = []
  for (const [category, label] of Object.entries(CATEGORY_LABELS)) {
    let items = byCat[category] ?? []
    if (q) {
      items = items.filter(
        nt => nt.display_name.toLowerCase().includes(q) || nt.node_type.toLowerCase().includes(q),
      )
    }
    if (items.length)
      result.push({ category, label, items })
  }
  return result
})

function onSelect(nodeType: string) {
  emit('select', nodeType)
  open.value = false
  search.value = ''
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <slot name="trigger">
        <button
          type="button"
          class="flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground shadow ring-2 ring-background hover:scale-110 transition-transform"
          :class="props.triggerClass"
          title="添加节点"
          @click.stop
          @mousedown.stop
          @pointerdown.stop
        >
          <Plus class="w-3.5 h-3.5" />
        </button>
      </slot>
    </PopoverTrigger>
    <PopoverContent class="w-64 p-2 max-h-80 overflow-y-auto" align="center">
      <input
        v-model="search"
        type="text"
        placeholder="搜索节点..."
        class="w-full mb-2 px-2 py-1 text-xs rounded-md border border-border/60 bg-background outline-none focus:border-primary/50"
      >
      <div v-if="groups.length === 0" class="py-4 text-center text-xs text-muted-foreground">
        无匹配节点
      </div>
      <div v-for="group in groups" :key="group.category" class="mb-2 last:mb-0">
        <div class="px-1 mb-1 text-[11px] font-medium text-muted-foreground">
          {{ group.label }}
        </div>
        <button
          v-for="nt in group.items"
          :key="nt.node_type"
          type="button"
          class="flex items-center gap-2 w-full px-2 py-1.5 rounded-md text-xs text-foreground hover:bg-muted transition-colors text-left"
          @click="onSelect(nt.node_type)"
        >
          <component :is="getNodeVisual(nt.node_type).icon" class="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
          <span class="truncate">{{ nt.display_name }}</span>
        </button>
      </div>
    </PopoverContent>
  </Popover>
</template>
