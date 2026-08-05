<script setup lang="ts">
/**
 * 阶段活动流面板（Phase 119，LIVE-01/02/03）。
 *
 * 两张视图，对应用户在编排过程中真正想看的两件事：
 *
 * 1. **路由适配度**：召回了多少仓、每个仓的加权总分与三分量、建议角色、证据计数与引用数。
 *    改动前这些只以 `payload` kv 的形式躺在阶段时间线的折叠层里（`candidate_count 42`），
 *    要用户自己把数字翻译成结论。
 * 2. **分仓每仓进度**：每个仓在第几波、是在跑 / 在等依赖 / 已产出，产出了多少实现项与接口。
 *    改动前分仓阶段前端**只能靠 `context.entry_appended` 间接猜**（波次在 `stage_state` 里
 *    而事件接口不暴露），一份跑着五个仓的蓝图在界面上和跑着一个仓没有区别。
 *
 * ## 三条纪律
 *
 * 1. ⭐ **派生全在 `~/utils/blueprintActivity` 的纯函数里**：本组件只呈现（与
 *    `BlueprintStageTimeline` 委托 `buildStageTimeline` 同一分工）。⛔ 不在这里 reduce 事件。
 * 2. ⭐ **只在有内容时渲染**：两张视图都空 ⇒ 整块不出现。⛔ 不出「暂无数据」的空卡片 ——
 *    编排还没跑到路由阶段是**正常态**，一张空卡只会挤占正文首屏。
 * 3. ⛔ **零颜色字面量**：语义色一律走 `Badge` 的 `variant`（沿用查看器既有纪律）。
 */

import type { BlueprintEvent } from '~/types/blueprint'
import type { RepoPlanProgressRow } from '~/utils/blueprintActivity'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { buildRepoPlanProgress, buildRouteFitness } from '~/utils/blueprintActivity'

const props = withDefaults(defineProps<{
  events?: BlueprintEvent[]
  /** 生成中（三态之一 + 等澄清）⇒ 默认展开；已收官的蓝图默认折叠成一行。 */
  isLive?: boolean
}>(), {
  events: () => [],
  isLive: false,
})

const { t } = useI18n()

const fitnessRows = computed(() => buildRouteFitness(props.events))
const repoRows = computed(() => buildRepoPlanProgress(props.events))
const hasContent = computed(() => fitnessRows.value.length > 0 || repoRows.value.length > 0)

/** 分仓状态 → Badge variant（三态语义色）。 */
const REPO_STATE_VARIANT: Record<RepoPlanProgressRow['state'], 'info' | 'success' | 'warning'> = {
  running: 'info',
  done: 'success',
  waiting: 'warning',
}

const REPO_STATE_LABEL_KEY: Record<RepoPlanProgressRow['state'], string> = {
  running: 'repoStateRunning',
  done: 'repoStateDone',
  waiting: 'repoStateWaiting',
}

/** 适配度 → 百分比文案；无分数返回空串（⛔ 不把缺失显示成 0%）。 */
function percent(total: number | null): string {
  return total === null ? '' : `${(total * 100).toFixed(2)}%`
}

/**
 * ⭐ 仓名兜底解析：事件 payload 的 `repository_name` 是 Phase 118 之后才带的，
 * 旧部署产生的历史事件只有裸 id —— 裸 id 对用户不可读，缺名时按 id 从仓库列表接口补全。
 * 只在真的有行缺名字时才发这一次请求（enabled 闸），列表全站低频变动，5 分钟 staleTime 足够。
 */
const needsNameLookup = computed(() =>
  [...fitnessRows.value, ...repoRows.value].some(row => row.repositoryId && !row.repositoryName),
)
const reposQuery = useQuery({
  queryKey: ['repositories', 'list'],
  queryFn: () => repositoriesApi.list(),
  enabled: needsNameLookup,
  staleTime: 5 * 60_000,
})
const repoNameById = computed<Map<string, string>>(() => {
  const map = new Map<string, string>()
  for (const repo of reposQuery.data.value ?? [])
    map.set(String(repo.id), repo.name)
  return map
})

/** 仓名三级回落：payload 名 → 仓库列表补全 → 短 id（没有名字也得让人分得清是哪一行）。 */
function repoLabel(name: string, id: string): string {
  const resolved = name || repoNameById.value.get(id) || ''
  return resolved || (id ? `${id.slice(0, 8)}…` : t('knowledge.blueprints.activity.repoUnknown'))
}

/** 仓库详情页地址（新窗口跳转用）；无 id 返回空串 ⇒ 模板渲染纯文本。 */
function repoHref(id: string): string {
  return id ? `/repositories/${id}` : ''
}
</script>

<template>
  <Collapsible
    v-if="hasContent"
    class="card"
    data-testid="blueprint-activity-panel"
    :default-open="isLive"
  >
    <CollapsibleTrigger
      class="flex w-full items-center gap-2 px-5 py-3.5 text-left transition-colors hover:bg-muted/30"
      data-testid="blueprint-activity-trigger"
    >
      <span class="icon-[lucide--activity] text-primary" aria-hidden="true" />
      <h2 class="text-base font-semibold">
        {{ t('knowledge.blueprints.activity.title') }}
      </h2>
      <Badge v-if="repoRows.length" variant="muted">
        {{ t('knowledge.blueprints.activity.repoCount', { n: repoRows.length }) }}
      </Badge>
      <span class="icon-[lucide--chevron-down] ml-auto shrink-0 text-muted-foreground" aria-hidden="true" />
    </CollapsibleTrigger>

    <CollapsibleContent>
      <div class="space-y-5 border-t border-border/50 p-5">
        <!-- ① 路由适配度 -->
        <section v-if="fitnessRows.length" data-testid="blueprint-activity-fitness">
          <h3 class="mb-2 text-sm font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.activity.fitnessTitle') }}
          </h3>
          <ul class="space-y-2">
            <li
              v-for="row in fitnessRows"
              :key="row.repositoryId"
              class="rounded-xl border border-border/60 bg-card p-3"
              :data-repository-id="row.repositoryId"
            >
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <!-- ⭐ 仓名可点：新窗口打开仓库详情页（有 id 才是链接，纯展示行保持 span） -->
                <a
                  v-if="repoHref(row.repositoryId)"
                  :href="repoHref(row.repositoryId)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="min-w-0 truncate text-sm font-medium hover:text-primary hover:underline"
                  data-testid="blueprint-activity-repo-link"
                >
                  {{ repoLabel(row.repositoryName, row.repositoryId) }}
                </a>
                <span v-else class="min-w-0 truncate text-sm font-medium">
                  {{ repoLabel(row.repositoryName, row.repositoryId) }}
                </span>
                <Badge v-if="row.roleSuggestion" variant="secondary">
                  {{ row.roleSuggestion }}
                </Badge>
                <Badge v-if="row.confidence" variant="muted">
                  {{ row.confidence }}
                </Badge>
                <!-- ⭐ 分数取 Heading 档 `text-base font-semibold`：它是这一行的主角，
                     而 §14 四档表里 Body 档字号加粗会让它与正文同号（源码守卫锁死该写法）。 -->
                <span
                  v-if="percent(row.total)"
                  class="ml-auto text-base font-semibold tabular-nums"
                  data-testid="blueprint-activity-fitness-score"
                >
                  {{ percent(row.total) }}
                </span>
              </div>

              <!-- 三分量：让「79.87% 是怎么来的」可核对 -->
              <dl v-if="row.breakdown.length" class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                <div v-for="part in row.breakdown" :key="part.key" class="inline-flex gap-1">
                  <dt>{{ t(`knowledge.blueprints.activity.component.${part.key}`) }}</dt>
                  <dd class="tabular-nums">
                    {{ part.value.toFixed(3) }}
                  </dd>
                </div>
              </dl>

              <p class="mt-1 text-xs text-muted-foreground">
                {{ t('knowledge.blueprints.activity.evidence', {
                  nodes: row.matchedNodePathCount,
                  domains: row.matchedDomainCount,
                  citations: row.citationCount,
                }) }}
                <span v-if="row.violatedBoundaryCount > 0">
                  · {{ t('knowledge.blueprints.activity.boundaryHit', { n: row.violatedBoundaryCount }) }}
                </span>
              </p>
            </li>
          </ul>
        </section>

        <!-- ② 分仓每仓进度 -->
        <section v-if="repoRows.length" data-testid="blueprint-activity-repos">
          <h3 class="mb-2 text-sm font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.activity.repoPlanTitle') }}
          </h3>
          <ul class="space-y-2">
            <li
              v-for="row in repoRows"
              :key="row.repositoryId"
              class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-border/60 bg-card p-3"
              :data-repository-id="row.repositoryId"
              :data-repo-state="row.state"
            >
              <span
                v-if="row.state === 'running'"
                class="icon-[lucide--loader-2] shrink-0 animate-spin text-base"
                aria-hidden="true"
              />
              <span
                v-else-if="row.state === 'done'"
                class="icon-[lucide--check-circle] shrink-0 text-base"
                aria-hidden="true"
              />
              <span v-else class="icon-[lucide--hourglass] shrink-0 text-base" aria-hidden="true" />

              <a
                v-if="repoHref(row.repositoryId)"
                :href="repoHref(row.repositoryId)"
                target="_blank"
                rel="noopener noreferrer"
                class="min-w-0 truncate text-sm hover:text-primary hover:underline"
                data-testid="blueprint-activity-repo-link"
              >
                {{ repoLabel(row.repositoryName, row.repositoryId) }}
              </a>
              <span v-else class="min-w-0 truncate text-sm">
                {{ repoLabel(row.repositoryName, row.repositoryId) }}
              </span>
              <Badge :variant="REPO_STATE_VARIANT[row.state]">
                {{ t(`knowledge.blueprints.activity.${REPO_STATE_LABEL_KEY[row.state]}`) }}
              </Badge>
              <Badge v-if="row.wave !== null" variant="muted">
                {{ t('knowledge.blueprints.activity.wave', { n: row.wave }) }}
              </Badge>

              <span
                v-if="row.itemCount !== null || row.apiCount !== null"
                class="ml-auto text-xs text-muted-foreground"
              >
                {{ t('knowledge.blueprints.activity.repoOutput', {
                  items: row.itemCount ?? 0,
                  apis: row.apiCount ?? 0,
                }) }}
              </span>
            </li>
          </ul>
        </section>
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>
