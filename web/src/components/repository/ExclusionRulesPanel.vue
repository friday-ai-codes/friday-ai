<script setup lang="ts">
import type { CreateExclusionPayload, ExclusionRuleType, GlobalDefaultRule } from '~/api/exclusions'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import { exclusionsApi } from '~/api/exclusions'
import { Switch } from '~/components/ui/switch'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repositoryId: string
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const queryKey = computed(() => ['repository-exclusions', props.repositoryId])

const { data, isLoading, isError } = useQuery({
  queryKey,
  queryFn: () => exclusionsApi.list(props.repositoryId),
})

const globalDefaults = computed(() => data.value?.global_defaults ?? [])
const repoRules = computed(() => data.value?.rules ?? [])

function invalidate() {
  queryClient.invalidateQueries({ queryKey: queryKey.value })
}

const ruleTypeOptions: ExclusionRuleType[] = ['glob', 'dir', 'regex']

function ruleTypeLabel(rt: ExclusionRuleType): string {
  return t(`exclusion.ruleType.${rt}`)
}

/**
 * 提取后端错误：优先 DRF 字段级错误（如非法 regex 的 `{pattern: [...]}`），
 * 回退到 ApiError.detail。使「非法 regex → 400」能展示具体原因。
 */
function fieldError(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as Record<string, unknown> | null
    if (body) {
      if (typeof body.detail === 'string')
        return body.detail
      for (const v of Object.values(body)) {
        if (Array.isArray(v) && typeof v[0] === 'string')
          return v[0]
        if (typeof v === 'string')
          return v
      }
    }
    return e.detail
  }
  return t('exclusion.error.create')
}

// ==================== 新增 per-repo 规则 ====================
const newRuleType = ref<ExclusionRuleType>('glob')
const newPattern = ref('')
const formError = ref<string | null>(null)

const createMutation = useMutation({
  mutationFn: (payload: CreateExclusionPayload) =>
    exclusionsApi.create(props.repositoryId, payload),
})

async function addRule() {
  formError.value = null
  const pattern = newPattern.value.trim()
  if (!pattern) {
    formError.value = t('exclusion.error.emptyPattern')
    return
  }
  try {
    await createMutation.mutateAsync({ pattern, rule_type: newRuleType.value })
    newPattern.value = ''
    success(t('exclusion.toast.created'))
    invalidate()
  }
  catch (e) {
    formError.value = fieldError(e)
  }
}

// ==================== 删除 per-repo 规则 ====================
const deleteMutation = useMutation({
  mutationFn: (ruleId: string) => exclusionsApi.remove(props.repositoryId, ruleId),
})

async function deleteRule(ruleId: string) {
  const ok = await confirm({
    title: t('exclusion.actions.deleteConfirmTitle'),
    description: t('exclusion.actions.deleteConfirmDescription'),
    confirmText: t('exclusion.actions.delete'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await deleteMutation.mutateAsync(ruleId)
    success(t('exclusion.toast.deleted'))
    invalidate()
  }
  catch (e) {
    handleError(e, t('exclusion.error.delete'))
  }
}

// ==================== 关闭/启用全局默认（override） ====================
const togglingPattern = ref<string | null>(null)

async function toggleGlobalDefault(rule: GlobalDefaultRule, enabled: boolean) {
  togglingPattern.value = rule.pattern
  try {
    if (!enabled) {
      // 关闭：创建 source=global + enabled=false 的 override 行
      await exclusionsApi.create(props.repositoryId, {
        pattern: rule.pattern,
        rule_type: rule.rule_type,
        source: 'global',
        enabled: false,
      })
      success(t('exclusion.toast.defaultDisabled'))
    }
    else if (rule.override_id) {
      // 启用：删除 override 行
      await exclusionsApi.remove(props.repositoryId, rule.override_id)
      success(t('exclusion.toast.defaultEnabled'))
    }
    invalidate()
  }
  catch (e) {
    handleError(e, t('exclusion.error.toggle'))
  }
  finally {
    togglingPattern.value = null
  }
}
</script>

<template>
  <div class="card">
    <div class="px-5 py-3.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--eye-off] text-primary" />
        <h3 class="text-sm font-semibold">
          {{ t('exclusion.title') }}
        </h3>
      </div>
      <p class="text-xs text-muted-foreground mt-0.5">
        {{ t('exclusion.subtitle') }}
      </p>
    </div>

    <div class="p-5 space-y-5">
      <!-- 安全边界如实措辞（DOMAIN §9.1：仅承诺 Friday 不可见，不承诺 git 物理删除） -->
      <div class="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
        <span class="icon-[lucide--shield-alert] mt-0.5 shrink-0" />
        <span>{{ t('exclusion.securityNote') }}</span>
      </div>

      <div v-if="isLoading" class="text-xs text-muted-foreground">
        <span class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
        {{ t('exclusion.title') }}…
      </div>
      <div v-else-if="isError" class="text-xs text-destructive">
        {{ t('exclusion.error.load') }}
      </div>

      <template v-else>
        <!-- 全局默认（只读 + 可关闭） -->
        <div class="space-y-2">
          <div>
            <p class="text-sm font-medium">
              {{ t('exclusion.globalDefaults.title') }}
            </p>
            <p class="text-xs text-muted-foreground">
              {{ t('exclusion.globalDefaults.description') }}
            </p>
          </div>
          <ul class="divide-y divide-border/40 rounded-lg border border-border/40">
            <li
              v-for="g in globalDefaults"
              :key="`${g.rule_type}:${g.pattern}`"
              class="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                  {{ ruleTypeLabel(g.rule_type) }}
                </span>
                <code class="text-xs font-mono truncate" :class="g.enabled ? '' : 'line-through text-muted-foreground'">
                  {{ g.pattern }}
                </code>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-[10px] text-muted-foreground">
                  {{ g.enabled ? t('exclusion.globalDefaults.enabledHint') : t('exclusion.globalDefaults.disabledHint') }}
                </span>
                <Switch
                  :model-value="g.enabled"
                  :disabled="togglingPattern === g.pattern"
                  @update:model-value="(val: boolean) => toggleGlobalDefault(g, val)"
                />
              </div>
            </li>
          </ul>
        </div>

        <!-- per-repo 规则 -->
        <div class="space-y-2">
          <p class="text-sm font-medium">
            {{ t('exclusion.repoRules.title') }}
          </p>
          <p v-if="repoRules.length === 0" class="text-xs text-muted-foreground">
            {{ t('exclusion.repoRules.empty') }}
          </p>
          <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40">
            <li
              v-for="rule in repoRules"
              :key="rule.id"
              class="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                  {{ ruleTypeLabel(rule.rule_type) }}
                </span>
                <code class="text-xs font-mono truncate">{{ rule.pattern }}</code>
              </div>
              <button
                class="p-1.5 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                :title="t('exclusion.actions.delete')"
                @click="deleteRule(rule.id)"
              >
                <span class="icon-[lucide--trash-2] text-sm" />
              </button>
            </li>
          </ul>
        </div>

        <!-- 新增表单 -->
        <div class="space-y-2 pt-1">
          <div class="flex items-center gap-2">
            <select
              v-model="newRuleType"
              class="h-9 rounded-lg border border-border/50 bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option v-for="rt in ruleTypeOptions" :key="rt" :value="rt">
                {{ ruleTypeLabel(rt) }}
              </option>
            </select>
            <input
              v-model="newPattern"
              type="text"
              :placeholder="t('exclusion.form.patternPlaceholder')"
              class="flex-1 h-9 rounded-lg border border-border/50 bg-background px-3 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary"
              @keyup.enter="addRule"
            >
            <button
              class="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-border/50 hover:bg-muted/50 transition-colors disabled:opacity-50 shrink-0"
              :disabled="createMutation.isPending.value"
              @click="addRule"
            >
              <span v-if="createMutation.isPending.value" class="icon-[lucide--loader-circle] animate-spin" />
              <span v-else class="icon-[lucide--plus]" />
              {{ createMutation.isPending.value ? t('exclusion.form.adding') : t('exclusion.form.add') }}
            </button>
          </div>
          <p v-if="formError" class="text-xs text-destructive flex items-center gap-1">
            <span class="icon-[lucide--alert-circle]" />
            {{ formError }}
          </p>
        </div>
      </template>
    </div>
  </div>
</template>
