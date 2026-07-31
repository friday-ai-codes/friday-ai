<script setup lang="ts">
/**
 * 关联段（Phase 115-05，UI-SPEC §6.1 段 9 / §10.2；VIEW-04 / SC-4）。
 *
 * ⭐ **本相位显式范围收窄：只兑现两块** —— 「本蓝图引用了」（`content.citations` 引用池的纯前端
 * 聚合，**零端点**）与「关联项目」（`meta.project_id` + 站内跳转）。
 *
 * **为什么收窄（P-5，证据链）**：原设计的「引用了本蓝图 / 关联知识」依赖知识库那两个反向关联
 * 查询端点，实测它们查的是 `initiatives.Artifact` 投影出来的 KnowledgeEntity
 * （`server/knowledge/artifact_associations.py:75`：`generate_entity_id(EntityKind.DOCUMENT,
 * 'artifact', artifact_id)` 之后 `KnowledgeEntity.objects.filter(id=...)`），而蓝图存在
 * `delivery.Artifact` ⇒ 拿蓝图 id 去调**必然 404 / 空**。知识图谱物化明确是 **Phase 116**
 * （ROADMAP:42）。⛔ 因此本段**一次都不调它们** —— 靠 404 兜底糊过去，等于把「这块没做」
 * 伪装成「暂时没数据」，评审人看不出差别（T-115-43）。
 *
 * ⭐ **收窄已完成对账（plan-checker BLOCKER-2 之后）**：ROADMAP Phase 115 的 SC-4 原文已改写为
 * 「蓝图引用的知识/仓库/其它蓝图可查（**反向「被谁引用」随 Phase 116 知识图谱物化交付**）」，
 * REQUIREMENTS 的 VIEW-04 已标 PARTIAL 并写明顺延目标。⛔ 执行期不得再把 SC-4 理解成
 * 「双向可查」——那个措辞已作废。顺延项同时登记在 115-05-SUMMARY 与 STATE 的 Pending Todos。
 *
 * **分工边界（P-4）**：`<section id="associations">` 容器与导航项由页面（115-06）无条件渲染；
 * 引用 chip 的点击经 `citation-click` 交给页面开**同一个**二级预览弹层（⛔ 本段不自建弹层）。
 */

import type { Citation, CitationSourceType } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import BlueprintCitationChip from './BlueprintCitationChip.vue'

const props = withDefaults(defineProps<{
  /** 蓝图所在的 `delivery.Artifact` id（用于可追溯的 `data-*` 标记，⛔ 不用于发起任何关联查询）。 */
  artifactId: string
  citations?: Record<string, Citation>
  projectId?: string | null
  projectName?: string
}>(), {
  citations: () => ({}),
  projectId: null,
  projectName: '',
})

const emit = defineEmits<{
  'citation-click': [citationId: string]
}>()

const { t } = useI18n()

/** 九档 `source_type` → i18n 文案键尾段（与 `BlueprintCitationChip` 同源，⛔ 不另发明档）。 */
const SOURCE_LABEL_KEY: Record<CitationSourceType, string> = {
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

/** 引用池按 `source_type` 分组统计（组内保持引用池的原始顺序）。 */
const groups = computed(() => {
  const pool = props.citations ?? {}
  const buckets = new Map<string, Citation[]>()
  for (const citation of Object.values(pool)) {
    if (!citation?.citation_id)
      continue
    const sourceType = citation.source_type
    const bucket = buckets.get(sourceType)
    if (bucket)
      bucket.push(citation)
    else
      buckets.set(sourceType, [citation])
  }
  return [...buckets.entries()].map(([sourceType, list]) => ({
    sourceType,
    label: SOURCE_LABEL_KEY[sourceType as CitationSourceType]
      ? t(`knowledge.blueprints.citation.${SOURCE_LABEL_KEY[sourceType as CitationSourceType]}`)
      : sourceType,
    items: list,
  }))
})

const hasProject = computed(() => Boolean(props.projectId))
const isEmpty = computed(() => !groups.value.length && !hasProject.value)
</script>

<template>
  <div data-testid="blueprint-associations" :data-artifact-id="artifactId" class="space-y-4">
    <CompactEmptyState
      v-if="isEmpty"
      icon="lucide--link"
      :title="t('knowledge.blueprints.citation.empty')"
    />

    <template v-else>
      <!-- ① 本蓝图引用了：引用池按 source_type 分组统计 + 可点 chip（零端点） -->
      <div v-if="groups.length" class="space-y-2" data-testid="blueprint-associations-citations">
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.associations.citedByThis') }}
        </p>
        <div
          v-for="group in groups"
          :key="group.sourceType"
          class="space-y-1"
          data-testid="blueprint-associations-group"
          :data-source-type="group.sourceType"
        >
          <div class="flex items-center gap-1.5">
            <span class="text-xs text-muted-foreground">{{ group.label }}</span>
            <Badge variant="muted">
              {{ group.items.length }}
            </Badge>
          </div>
          <div class="flex flex-wrap gap-1">
            <BlueprintCitationChip
              v-for="(citation, index) in group.items"
              :key="citation.citation_id"
              :citation="citation"
              :index="index + 1"
              @click="emit('citation-click', $event)"
            />
          </div>
        </div>
      </div>

      <!-- ② 关联项目 -->
      <div v-if="hasProject" class="space-y-1" data-testid="blueprint-associations-project">
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.associations.relatedProject') }}
        </p>
        <RouterLink
          :to="`/projects/${projectId}`"
          class="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          data-testid="blueprint-associations-project-link"
        >
          <span class="icon-[lucide--external-link]" aria-hidden="true" />
          <span>{{ projectName || projectId }}</span>
        </RouterLink>
      </div>
    </template>
  </div>
</template>
