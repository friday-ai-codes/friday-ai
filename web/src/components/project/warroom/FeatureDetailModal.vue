<script setup lang="ts">
import type { FeatureDetailSection, FeatureNode } from '~/api/projectWorkspace'
import { computed, onMounted, ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import MermaidDiagram from './MermaidDiagram.vue'

// 功能点/模块详情：点开后用其整段原文（source）按需结构化为柔性 sections（描述/规则/数据流转/
// 流程图/验收项…），逐字保留原文。无 source 或结构化失败时回退展示原文 + 验收项。
const props = defineProps<{
  projectId: string
  /** 功能点或模块节点（携带 name / source / children）。 */
  node: FeatureNode
}>()
const emit = defineEmits<{ closed: [] }>()

const sections = ref<FeatureDetailSection[]>([])
const loading = ref(false)
const loaded = ref(false)

// 验收项（功能点子节点 kind=acceptance）——作为兜底/补充展示。
const acceptance = computed(() =>
  (props.node.children ?? []).filter(c => c.kind === 'acceptance').map(c => c.name),
)
const hasSource = computed(() => !!props.node.source?.trim())

function asList(content: string | string[]): string[] {
  return Array.isArray(content) ? content : [content]
}
function asText(content: string | string[]): string {
  return Array.isArray(content) ? content.join('\n') : content
}

onMounted(async () => {
  // 优先用解析阶段预生成 / 已缓存的详情（点开即时、零请求、无 loading）。
  if (props.node.detail_sections?.length) {
    sections.value = props.node.detail_sections
    loaded.value = true
    return
  }
  if (!hasSource.value)
    return
  loading.value = true
  try {
    // 兜底：未预热的旧数据首次点开时生成，后端会写缓存，之后不再重算。
    const { sections: out } = await projectWorkspaceApi.getFeatureDetail(
      props.projectId,
      props.node.source as string,
    )
    sections.value = out || []
  }
  catch {
    sections.value = []
  }
  finally {
    loading.value = false
    loaded.value = true
  }
})

const STATE_LABEL: Record<string, string> = {
  todo: '待开发',
  in_progress: '进行中',
  testing: '测试中',
  done: '已完成',
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-2xl border border-border/50 max-w-3xl w-full mx-4 max-h-[88vh]"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <header class="flex items-start gap-3 px-6 py-4 border-b border-border/50">
      <span class="inline-flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary shrink-0">
        <span class="icon-[lucide--git-branch] text-lg" />
      </span>
      <div class="min-w-0 flex-1">
        <h2 class="text-base font-semibold text-foreground break-words">
          {{ node.name }}
        </h2>
        <p class="text-xs text-muted-foreground">
          {{ node.module_normalized ? `${node.module_normalized} · ` : '' }}功能点详情
        </p>
      </div>
      <span
        v-if="node.state"
        class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium bg-muted text-muted-foreground"
      >
        {{ node.status_display_name || STATE_LABEL[node.state] || node.state }}
      </span>
    </header>

    <div class="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5">
      <div v-if="loading" class="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center">
        <span class="icon-[lucide--loader-2] animate-spin" /> 正在解析…
      </div>

      <!-- 结构化 sections -->
      <template v-else-if="sections.length">
        <section v-for="(sec, i) in sections" :key="i" class="space-y-1.5">
          <h3 v-if="sec.title" class="text-sm font-semibold text-foreground flex items-center gap-1.5">
            <span class="inline-block w-1 h-3.5 rounded-full bg-primary/60" />
            {{ sec.title }}
          </h3>
          <MermaidDiagram v-if="sec.type === 'mermaid'" :code="asText(sec.content)" />
          <ul v-else-if="sec.type === 'list'" class="space-y-1 pl-1">
            <li
              v-for="(item, ii) in asList(sec.content)"
              :key="ii"
              class="flex items-start gap-2 text-sm text-foreground/90 leading-relaxed"
            >
              <span class="icon-[lucide--check] text-emerald-500/70 mt-1 shrink-0" />
              <span class="whitespace-pre-wrap break-words">{{ item }}</span>
            </li>
          </ul>
          <p v-else class="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap break-words">
            {{ asText(sec.content) }}
          </p>
        </section>
      </template>

      <!-- 回退：无结构化结果时展示原文 + 验收项 -->
      <template v-else>
        <div v-if="hasSource" class="space-y-1.5">
          <h3 class="text-sm font-semibold text-foreground">
            原文
          </h3>
          <pre class="rounded-lg border border-border/50 bg-muted/20 p-3 text-xs font-mono text-foreground/80 whitespace-pre-wrap break-words">{{ node.source }}</pre>
        </div>
        <div v-if="acceptance.length" class="space-y-1.5">
          <h3 class="text-sm font-semibold text-foreground">
            验收项
          </h3>
          <ul class="space-y-1 pl-1">
            <li
              v-for="(acc, ai) in acceptance"
              :key="ai"
              class="flex items-start gap-2 text-sm text-foreground/90 leading-relaxed"
            >
              <span class="icon-[lucide--check] text-emerald-500/70 mt-1 shrink-0" />
              <span class="whitespace-pre-wrap break-words">{{ acc }}</span>
            </li>
          </ul>
        </div>
        <p v-if="!hasSource && !acceptance.length" class="py-6 text-center text-sm text-muted-foreground">
          该功能点暂无更多详情
        </p>
      </template>
    </div>
  </VueFinalModal>
</template>
