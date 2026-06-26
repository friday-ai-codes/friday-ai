<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

/** 工作区左导航区块项。 */
export interface WorkbenchSection {
  id: string
  label: string
  icon?: string
  badge?: string | number
}

const props = defineProps<{
  sections: WorkbenchSection[]
  /** 左导航无障碍标签。 */
  navLabel?: string
}>()

const emit = defineEmits<{
  (e: 'update:section', value: string): void
}>()

const route = useRoute()
const router = useRouter()

function isKnown(id: string): boolean {
  return props.sections.some(s => s.id === id)
}

const fallback = computed(() => props.sections[0]?.id ?? '')

function readHash(): string {
  const raw = (route.hash || '').replace(/^#/, '')
  return raw && isKnown(raw) ? raw : fallback.value
}

const active = ref<string>(readHash())

function select(id: string) {
  if (!isKnown(id) || id === active.value)
    return
  active.value = id
}

onMounted(() => {
  active.value = readHash()
})

// active → URL #hash（深链书签）。
watch(active, (id) => {
  emit('update:section', id)
  if (id && id !== (route.hash || '').replace(/^#/, '')) {
    router.replace({ hash: `#${id}` }).catch(() => {})
  }
})

// URL #hash → active（前进/后退、外部跳转）。
watch(() => route.hash, () => {
  const next = readHash()
  if (next !== active.value)
    active.value = next
})

defineExpose({ active })
</script>

<template>
  <div class="flex gap-8">
    <!-- 左导航（宽屏） -->
    <aside class="hidden md:block w-48 shrink-0">
      <nav
        class="sticky top-22 space-y-0.5"
        :aria-label="navLabel"
      >
        <button
          v-for="section in sections"
          :key="section.id"
          type="button"
          class="group relative w-full text-left pl-4 pr-2.5 py-2 rounded-md text-sm transition-colors flex items-center gap-2"
          :class="active === section.id
            ? 'bg-primary/8 text-primary font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'"
          :aria-current="active === section.id ? 'page' : undefined"
          :data-testid="`workbench-nav-${section.id}`"
          @click="select(section.id)"
        >
          <span
            v-if="active === section.id"
            class="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-r-full bg-primary"
          />
          <span
            v-if="section.icon"
            :class="[section.icon, active === section.id ? 'opacity-100' : 'opacity-70 group-hover:opacity-100']"
          />
          <span class="flex-1 truncate">{{ section.label }}</span>
          <span
            v-if="section.badge !== undefined && section.badge !== null && section.badge !== ''"
            class="ml-auto inline-flex items-center justify-center min-w-5 h-5 px-1.5 rounded-full text-[11px] font-medium leading-none transition-colors"
            :class="active === section.id ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'"
          >
            {{ section.badge }}
          </span>
        </button>
      </nav>
    </aside>

    <!-- 窄屏：左轨折叠为顶部下拉 -->
    <div class="flex-1 min-w-0 space-y-6">
      <div class="md:hidden">
        <Select :model-value="active" @update:model-value="(v) => select(v as string)">
          <SelectTrigger class="w-full" :aria-label="navLabel">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="section in sections" :key="section.id" :value="section.id">
              {{ section.label }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <slot :active="active" />
    </div>
  </div>
</template>
