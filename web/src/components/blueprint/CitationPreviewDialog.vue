<script setup lang="ts">
/**
 * 引用二级预览弹层（Phase 115-03，UI-SPEC §10.1）。
 *
 * **第一层 Dialog、无嵌套**（查看器本身是路由页，不是弹层）：`Dialog` + `DialogScrollContent`
 * + `DialogHeader` + **`DialogTitle`（必填，缺了 reka-ui 会报 a11y 警告）**。
 *
 * **分发**（六类进得来；`work_item` / `feishu_doc` / `url` 三类**根本不会到这里** ——
 * chip 本身就是 `<a target="_blank">`，见 `BlueprintCitationChip.vue`）：
 *
 * | source_type | 子件 |
 * |---|---|
 * | `knowledge_entity` | `CitationKnowledgePreview` |
 * | `repo_file` / `rag_chunk` | `CitationCodePreview`（⭐ 降级形态：路径 + 行号 + quote 快照） |
 * | `repo_charter` | `CitationCharterPreview` |
 * | `blueprint` / `artifact_version` | `CitationBlueprintPreview`（迷你只读、无批注、plainMermaid） |
 * | 其余 / 缺关键定位 | `CitationFallback` |
 *
 * ⭐ **兜底不留白，且与 analog 完全相反**：`pages/knowledge/index.vue:165-191` 的 `catch`
 * 分支是「关弹窗 + toast」；本相位任何失败（400 / 404 / 5xx / 超时 / 解析失败 / ⭐ `chunk-at`
 * 的 200-空 chunks）一律由子件渲染 `CitationFallback`，**弹窗保持打开**、⛔ 不回显后端错误体。
 * 本组件内因此**没有** `catch` 分支去关自己 —— 关闭只可能来自用户操作。
 */

import type { Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import {
  Dialog,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import CitationBlueprintPreview from './citation/CitationBlueprintPreview.vue'
import CitationCharterPreview from './citation/CitationCharterPreview.vue'
import CitationCodePreview from './citation/CitationCodePreview.vue'
import CitationFallback from './citation/CitationFallback.vue'
import CitationKnowledgePreview from './citation/CitationKnowledgePreview.vue'

const props = withDefaults(defineProps<{
  open?: boolean
  citation?: Citation | null
}>(), {
  open: false,
  citation: null,
})

const emit = defineEmits<{
  'update:open': [boolean]
}>()

const { t } = useI18n()

/** 九档 `source_type` → i18n 文案键尾段（与 `BlueprintCitationChip` 同一张表）。 */
const SOURCE_LABEL_KEY: Record<string, string> = {
  knowledge_entity: 'sourceKnowledgeEntity',
  repo_file: 'sourceRepoFile',
  rag_chunk: 'sourceRagChunk',
  repo_charter: 'sourceRepoCharter',
  blueprint: 'sourceBlueprint',
  artifact_version: 'sourceArtifactVersion',
  work_item: 'sourceWorkItem',
  feishu_doc: 'sourceFeishuDoc',
  url: 'sourceUrl',
}

const sourceType = computed(() => props.citation?.source_type ?? '')

const sourceLabel = computed(() => {
  const key = SOURCE_LABEL_KEY[sourceType.value]
  return key ? t(`knowledge.blueprints.citation.${key}`) : sourceType.value
})

const locator = computed<Record<string, unknown>>(() => props.citation?.locator ?? {})

function readLocator(key: string): string {
  const value = locator.value[key]
  return typeof value === 'string' ? value : ''
}

const fallback = computed(() => ({
  title: props.citation?.title ?? '',
  quote: props.citation?.quote ?? '',
}))

const title = computed(() => props.citation?.title || sourceLabel.value)

const repositoryId = computed(() => readLocator('repository_id') || readLocator('repo_id'))
const entityId = computed(() => props.citation?.source_id ?? '')
const artifactId = computed(() => readLocator('artifact_id') || (props.citation?.source_id ?? ''))
const versionId = computed(() => readLocator('version_id'))
const blockId = computed(() => readLocator('block_id'))

/** 分发目标；缺关键定位（如代码引用没有仓库 id）一律直接落 `fallback`。 */
const variant = computed<'knowledge' | 'code' | 'charter' | 'blueprint' | 'fallback'>(() => {
  switch (sourceType.value) {
    case 'knowledge_entity':
      return entityId.value ? 'knowledge' : 'fallback'
    case 'repo_file':
    case 'rag_chunk':
      return repositoryId.value ? 'code' : 'fallback'
    case 'repo_charter':
      return repositoryId.value ? 'charter' : 'fallback'
    case 'blueprint':
    case 'artifact_version':
      return artifactId.value ? 'blueprint' : 'fallback'
    default:
      return 'fallback'
  }
})
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogScrollContent class="w-[92vw] max-w-4xl" data-testid="citation-preview-dialog">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2 text-base">
          <Badge variant="muted">
            {{ sourceLabel }}
          </Badge>
          <span class="truncate">{{ title }}</span>
        </DialogTitle>
      </DialogHeader>

      <div class="max-h-[72vh] overflow-auto">
        <CitationKnowledgePreview
          v-if="variant === 'knowledge'"
          :entity-id="entityId"
          :fallback="fallback"
        />
        <CitationCodePreview
          v-else-if="variant === 'code'"
          :repository-id="repositoryId"
          :locator="locator"
          :fallback="fallback"
        />
        <CitationCharterPreview
          v-else-if="variant === 'charter'"
          :repository-id="repositoryId"
          :locator="locator"
          :fallback="fallback"
        />
        <CitationBlueprintPreview
          v-else-if="variant === 'blueprint'"
          :artifact-id="artifactId"
          :version-id="versionId"
          :block-id="blockId"
          :fallback="fallback"
        />
        <CitationFallback
          v-else
          :title="fallback.title"
          :quote="fallback.quote"
        />
      </div>
    </DialogScrollContent>
  </Dialog>
</template>
