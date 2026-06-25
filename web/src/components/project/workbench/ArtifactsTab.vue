<script setup lang="ts">
import type { Artifact, ArtifactView } from '~/api/artifacts'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactsApi } from '~/api/artifacts'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'

const props = defineProps<{ projectId: string, canManage: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()

const projectIdRef = toRef(props, 'projectId')

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-artifacts', projectIdRef],
  queryFn: () => artifactsApi.list(props.projectId),
})
const artifacts = computed<Artifact[]>(() => data.value ?? [])

// 按类型分组（ARTIFACT 类型分组列表）。
const grouped = computed(() => {
  const map = new Map<string, Artifact[]>()
  for (const a of artifacts.value) {
    const key = a.type_name || a.type_key
    if (!map.has(key))
      map.set(key, [])
    map.get(key)!.push(a)
  }
  return Array.from(map, ([name, list]) => ({ name, list }))
})

const viewOpen = ref(false)
const viewLoading = ref(false)
const viewData = ref<ArtifactView | null>(null)
const viewTitle = ref('')

const CARRIER_ICON: Record<string, string> = {
  feishu_doc: 'lucide--file-text',
  feishu_bitable: 'lucide--table',
  external_link: 'lucide--external-link',
  markdown: 'lucide--file-code',
  repo_file: 'lucide--file',
}

async function openView(artifact: Artifact) {
  viewTitle.value = artifact.title
  viewData.value = null
  viewOpen.value = true
  viewLoading.value = true
  try {
    viewData.value = await artifactsApi.view(props.projectId, artifact.id)
  }
  catch (e: unknown) {
    handleError(e, t('projects.artifacts.viewFailed'))
    viewOpen.value = false
  }
  finally {
    viewLoading.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <div v-if="isLoading" class="text-sm text-muted-foreground py-8 text-center">
      {{ t('projects.loading') }}
    </div>
    <div v-else-if="isError" class="py-8 text-center space-y-2">
      <p class="text-sm text-destructive">
        {{ t('projects.artifacts.loadError') }}
      </p>
      <button class="text-sm text-primary underline" @click="() => refetch()">
        {{ t('projects.retry') }}
      </button>
    </div>
    <div v-else-if="artifacts.length === 0" class="text-sm text-muted-foreground py-8 text-center">
      {{ t('projects.artifacts.empty') }}
    </div>

    <section v-for="group in grouped" v-else :key="group.name" class="space-y-2">
      <h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        {{ group.name }}
      </h3>
      <ul class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
        <li
          v-for="a in group.list"
          :key="a.id"
          class="flex items-center justify-between gap-3 px-4 py-3"
          data-testid="artifact-row"
        >
          <div class="min-w-0 flex items-center gap-3">
            <span :class="`icon-[${CARRIER_ICON[a.carrier] || 'lucide--file'}] text-muted-foreground`" />
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground truncate">
                {{ a.title }}
              </p>
              <p class="text-xs text-muted-foreground">
                {{ t(`projects.artifacts.carrier.${a.carrier}`) }} · v{{ a.version }}
                <span v-if="a.ragable" class="ml-1 text-emerald-600 dark:text-emerald-400">· RAG</span>
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <a v-if="a.url" :href="a.url" target="_blank" rel="noopener noreferrer" class="text-xs text-muted-foreground hover:text-primary" :title="t('projects.artifacts.openExternal')">
              <span class="icon-[lucide--external-link]" />
            </a>
            <button
              class="text-xs text-primary hover:underline"
              data-testid="view-artifact-btn"
              @click="openView(a)"
            >
              {{ t('projects.artifacts.view') }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <!-- 在线查看 -->
    <Dialog v-model:open="viewOpen">
      <DialogScrollContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{{ viewTitle }}</DialogTitle>
          <DialogDescription>{{ t('projects.artifacts.viewDesc') }}</DialogDescription>
        </DialogHeader>
        <div class="mt-2">
          <div v-if="viewLoading" class="text-sm text-muted-foreground py-6 text-center">
            {{ t('projects.loading') }}
          </div>
          <template v-else-if="viewData">
            <p v-if="viewData.error" class="text-sm text-destructive">
              {{ viewData.error }}
            </p>
            <a
              v-else-if="viewData.render_type === 'link'"
              :href="viewData.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm text-primary underline break-all"
            >
              {{ viewData.url }}
            </a>
            <pre
              v-else-if="viewData.render_type === 'markdown' || viewData.render_type === 'text'"
              class="text-xs bg-muted/50 rounded-lg p-3 max-h-[60vh] overflow-auto whitespace-pre-wrap"
            >{{ viewData.content }}</pre>
            <div v-else-if="viewData.render_type === 'records'" class="text-xs space-y-1 max-h-[60vh] overflow-auto">
              <p class="text-muted-foreground">
                {{ t('projects.artifacts.recordCount', { n: viewData.records?.length ?? 0 }) }}
              </p>
              <pre class="bg-muted/50 rounded-lg p-3 overflow-auto">{{ JSON.stringify(viewData.records, null, 2) }}</pre>
            </div>
            <p v-else class="text-sm text-muted-foreground">
              {{ t('projects.artifacts.unsupported') }}
            </p>
          </template>
        </div>
      </DialogScrollContent>
    </Dialog>
  </div>
</template>
