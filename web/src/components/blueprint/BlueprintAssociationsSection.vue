<script setup lang="ts">
/**
 * 关联段（Phase 115-05，UI-SPEC §6.1 段 9 / §10.2；VIEW-04 / SC-4）。
 *
 * ⭐ **Phase 116 已交付反向反查**：本段现在四块 —— 「本蓝图引用了」（`content.citations`
 * 引用池的纯前端聚合，**零端点**）、「关联项目」（`meta.project_id` + 站内跳转），加上
 * 116-04 物化 REFERENCES 边之后新增的「被哪些方案 / 知识引用」（`direction: 'in'`）与
 * 「关联知识」（`direction: 'out'`）。
 *
 * ⭐ **证据链的结论部分依然成立，⛔ 因此仍然一次都不调 `getArtifactAssociations`**：它查的是
 * `initiatives.Artifact` 投影出来的 KnowledgeEntity（`server/knowledge/artifact_associations.py:75`：
 * `generate_entity_id(EntityKind.DOCUMENT, 'artifact', artifact_id)` 之后
 * `KnowledgeEntity.objects.filter(id=...)`），而蓝图活在 `delivery.Artifact` ⇒ 拿蓝图 id 去调
 * **依然必然落空**。116 不是把它修好了，而是**改走另一条链**：`getRelated` + 116 物化的
 * REFERENCES 边，实参是后端 `GET .../blueprint/` 新增的 `knowledge_entity_id`
 * （⛔ 前端不复制实体 id 的派生规则）。
 *
 * ⭐ **`maxHops: 1` 必须显式传**：view 与 `api/knowledge.ts` 的默认都是 **2**，「被谁引用」要的是
 * **直接引用者**——不传会把二跳实体也列进来，用户会据错误的引用关系做决策（T-116-35）。
 * ⭐ **`relations: ['REFERENCES']` 必须显式传**：`_DEFAULT_RELATIONS` 不含 `REFERENCES`，
 * 不传等于查一个恒空的集合（T-116-27）。
 *
 * 两块的失败**不进错误分档**（沿 115 的「关联面失败只降级不报错」口径）：空态走
 * `CompactEmptyState`，⛔ 不弹 toast、⛔ 零轮询（实时数据一律经 `useBlueprintLive`，
 * 源码守卫 `src/__tests__/blueprint-source-guard.spec.ts` 逐字锁死轮询字面量的出现位置）。
 *
 * **分工边界（P-4）**：`<section id="associations">` 容器与导航项由页面（115-06）无条件渲染；
 * 引用 chip 的点击经 `citation-click` 交给页面开**同一个**二级预览弹层（⛔ 本段不自建弹层）。
 */

import type { Citation, CitationSourceType } from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { knowledgeApi } from '~/api'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import BlueprintCitationChip from './BlueprintCitationChip.vue'

const props = withDefaults(defineProps<{
  /** 蓝图所在的 `delivery.Artifact` id（用于可追溯的 `data-*` 标记，⛔ 不用于发起任何关联查询）。 */
  artifactId: string
  citations?: Record<string, Citation>
  projectId?: string | null
  projectName?: string
  /**
   * 蓝图在交付知识图谱里的实体 id —— 来自 `GET .../blueprint/` 的第 8 键
   * `knowledge_entity_id`（116-04 纯追加）。⛔ 前端不自行派生它。
   * 为空（旧数据 / 尚未入图）时两块**都不发请求**。
   */
  knowledgeEntityId?: string | null
}>(), {
  citations: () => ({}),
  projectId: null,
  projectName: '',
  knowledgeEntityId: null,
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

/** 图谱反查开关：`knowledge_entity_id` 为空即两块都不发请求（`enabled` 不是摆设）。 */
const graphEnabled = computed(() => Boolean(props.knowledgeEntityId))

/** 「被哪些方案 / 知识引用」：入边 + 只走 REFERENCES + ⭐ 只要直接引用者（`maxHops: 1`）。 */
const referrersQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'related-in', props.artifactId, props.knowledgeEntityId]),
  queryFn: () => knowledgeApi.getRelated(String(props.knowledgeEntityId), {
    direction: 'in',
    relations: ['REFERENCES'],
    maxHops: 1,
  }),
  enabled: graphEnabled,
})

/**
 * 「关联知识」：出边 —— 本蓝图**已物化成边**的图谱邻居。
 * 与上面的「本蓝图引用了」**互补而非重复**：那块是引用池原样（含还没入图、甚至不成边的
 * `url` 条目），这块是真的落到 `KnowledgeEdge` 上、可以点进去继续查的邻居。
 */
const relatedKnowledgeQuery = useQuery({
  queryKey: computed(() => ['blueprint', 'related-out', props.artifactId, props.knowledgeEntityId]),
  queryFn: () => knowledgeApi.getRelated(String(props.knowledgeEntityId), {
    direction: 'out',
    relations: ['REFERENCES'],
    maxHops: 1,
  }),
  enabled: graphEnabled,
})

const referrers = computed(() => referrersQuery.data.value ?? [])
const relatedKnowledge = computed(() => relatedKnowledgeQuery.data.value ?? [])

/** 图谱条目的展示名：优先 metadata.title，退到 kind + 短 id（⛔ 不留白、⛔ 不渲染 undefined）。 */
function entityLabel(item: { entity_id: string, kind: string, metadata?: { title?: string } }) {
  return item.metadata?.title || `${item.kind} · ${item.entity_id.slice(0, 8)}`
}

const isEmpty = computed(
  () => !groups.value.length
    && !hasProject.value
    && !referrers.value.length
    && !relatedKnowledge.value.length,
)
</script>

<template>
  <div data-testid="blueprint-associations" :data-artifact-id="artifactId" class="space-y-4">
    <CompactEmptyState
      v-if="isEmpty"
      icon="lucide--link"
      :title="t('knowledge.blueprints.citation.empty')"
    />

    <template v-else>
      <!-- ① 本蓝图引用了：引用池原样按 source_type 分组统计 + 可点 chip（零端点） -->
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

      <!-- ② 被哪些方案 / 知识引用：图谱入边（116-04 物化的 REFERENCES 边） -->
      <div v-if="graphEnabled" class="space-y-1" data-testid="blueprint-associations-referrers">
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.associations.referencedBy') }}
        </p>
        <ul v-if="referrers.length" class="space-y-1">
          <li
            v-for="item in referrers"
            :key="item.entity_id"
            class="flex items-center gap-1.5 text-sm"
            data-testid="blueprint-associations-referrer-item"
          >
            <RouterLink
              :to="`/knowledge/entities/${item.entity_id}`"
              class="text-primary hover:underline"
            >
              {{ entityLabel(item) }}
            </RouterLink>
            <Badge variant="muted">
              {{ item.kind }}
            </Badge>
          </li>
        </ul>
        <p v-else class="text-xs text-muted-foreground">
          {{ t('knowledge.blueprints.associations.referencedByEmpty') }}
        </p>
      </div>

      <!-- ③ 关联知识：图谱出边（与「本蓝图引用了」互补——这块是已物化成边的邻居） -->
      <div v-if="graphEnabled" class="space-y-1" data-testid="blueprint-associations-related">
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.associations.relatedKnowledge') }}
        </p>
        <ul v-if="relatedKnowledge.length" class="space-y-1">
          <li
            v-for="item in relatedKnowledge"
            :key="item.entity_id"
            class="flex items-center gap-1.5 text-sm"
            data-testid="blueprint-associations-related-item"
          >
            <RouterLink
              :to="`/knowledge/entities/${item.entity_id}`"
              class="text-primary hover:underline"
            >
              {{ entityLabel(item) }}
            </RouterLink>
            <Badge variant="muted">
              {{ item.kind }}
            </Badge>
          </li>
        </ul>
        <p v-else class="text-xs text-muted-foreground">
          {{ t('knowledge.blueprints.associations.relatedKnowledgeEmpty') }}
        </p>
      </div>

      <!-- ④ 关联项目 -->
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
