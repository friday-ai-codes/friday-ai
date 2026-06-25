<script setup lang="ts">
import type { ArtifactType } from '~/api/artifactTypes'
import type { ArtifactCarrier } from '~/api/artifacts'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ARTIFACT_CARRIERS, artifactTypesApi } from '~/api/artifactTypes'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'

definePage({ meta: { requiresAdmin: true } })

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()
const queryClient = useQueryClient()

useHead({ title: () => `${t('artifactTypes.title')} - Friday AI` })

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['artifact-types'],
  queryFn: () => artifactTypesApi.list(),
})
const types = computed<ArtifactType[]>(() => data.value ?? [])

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['artifact-types'] })
}

// ---- 新增类型 ----
const showCreate = ref(false)
const form = reactive({
  key: '',
  name: '',
  carrier: 'markdown' as ArtifactCarrier,
  ragable: false,
})
const createError = ref('')

const createMutation = useMutation({
  mutationFn: () =>
    artifactTypesApi.create({
      key: form.key.trim(),
      name: form.name.trim(),
      carrier: form.carrier,
      ragable: form.ragable,
    }),
  onSuccess: () => {
    success(t('artifactTypes.created'))
    showCreate.value = false
    form.key = ''
    form.name = ''
    form.carrier = 'markdown'
    form.ragable = false
    invalidate()
  },
  onError: (e: unknown) => handleError(e, t('artifactTypes.createFailed')),
})

function submitCreate() {
  createError.value = ''
  if (!form.key.trim() || !form.name.trim()) {
    createError.value = t('artifactTypes.form.required')
    return
  }
  createMutation.mutate()
}

// ---- 启停 ----
async function toggleEnabled(type: ArtifactType) {
  try {
    await artifactTypesApi.update(type.id, { enabled: !type.enabled })
    success(type.enabled ? t('artifactTypes.disabled') : t('artifactTypes.enabled'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('artifactTypes.updateFailed'))
  }
}

// ---- 删除（builtin/有实例禁删）----
function deleteDisabledReason(type: ArtifactType): string {
  if (type.builtin)
    return t('artifactTypes.deleteProtected.builtin')
  if (type.instance_count > 0)
    return t('artifactTypes.deleteProtected.hasInstances', { n: type.instance_count })
  return ''
}

async function removeType(type: ArtifactType) {
  if (deleteDisabledReason(type))
    return
  const ok = await confirm({
    title: t('artifactTypes.deleteTitle'),
    description: t('artifactTypes.deleteConfirm', { name: type.name }),
    confirmText: t('artifactTypes.deleteConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await artifactTypesApi.remove(type.id)
    success(t('artifactTypes.deleted'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('artifactTypes.deleteFailed'))
  }
}
</script>

<template>
  <PageContainer>
    <PageHeader
      icon="lucide--shapes"
      :title="t('artifactTypes.title')"
      :description="t('artifactTypes.subtitle')"
    >
      <template #actions>
        <Button data-testid="create-type-btn" @click="showCreate = !showCreate">
          <span class="icon-[lucide--plus] mr-1.5" />
          {{ t('artifactTypes.create') }}
        </Button>
      </template>
    </PageHeader>

    <!-- 新增表单 -->
    <form
      v-if="showCreate"
      class="card p-5 space-y-4"
      data-testid="create-type-form"
      @submit.prevent="submitCreate"
    >
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="space-y-1.5">
          <Label for="type-key">{{ t('artifactTypes.form.key') }}</Label>
          <Input id="type-key" v-model="form.key" placeholder="custom_type" class="h-9" />
        </div>
        <div class="space-y-1.5">
          <Label for="type-name">{{ t('artifactTypes.form.name') }}</Label>
          <Input id="type-name" v-model="form.name" :placeholder="t('artifactTypes.form.namePlaceholder')" class="h-9" />
        </div>
        <div class="space-y-1.5">
          <Label for="type-carrier">{{ t('artifactTypes.form.carrier') }}</Label>
          <select
            id="type-carrier"
            v-model="form.carrier"
            class="flex h-9 w-full rounded-lg border border-border/60 bg-background/90 px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            <option v-for="c in ARTIFACT_CARRIERS" :key="c" :value="c">
              {{ t(`projects.artifacts.carrier.${c}`) }}
            </option>
          </select>
        </div>
        <label class="flex items-center gap-2 text-sm self-end pb-2 cursor-pointer">
          <input v-model="form.ragable" type="checkbox" class="rounded border-border/60">
          {{ t('artifactTypes.form.ragable') }}
        </label>
      </div>
      <p v-if="createError" class="text-sm text-destructive">
        {{ createError }}
      </p>
      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="showCreate = false">
          {{ t('artifactTypes.form.cancel') }}
        </Button>
        <Button type="submit" :disabled="createMutation.isPending.value">
          {{ t('artifactTypes.form.submit') }}
        </Button>
      </div>
    </form>

    <LoadingState v-if="isLoading" variant="card" :count="3" />
    <div v-else-if="isError" class="py-12 text-center space-y-3">
      <p class="text-sm text-destructive">
        {{ t('artifactTypes.loadError') }}
      </p>
      <Button variant="outline" size="sm" @click="() => refetch()">
        {{ t('projects.retry') }}
      </Button>
    </div>
    <EmptyState
      v-else-if="types.length === 0"
      icon="lucide--shapes"
      :title="t('artifactTypes.empty')"
    />

    <div v-else class="overflow-x-auto rounded-lg border border-border/40 bg-card">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border/40 text-left text-xs text-muted-foreground">
            <th class="px-4 py-3 font-medium">
              {{ t('artifactTypes.col.name') }}
            </th>
            <th class="px-4 py-3 font-medium">
              {{ t('artifactTypes.col.key') }}
            </th>
            <th class="px-4 py-3 font-medium">
              {{ t('artifactTypes.col.carrier') }}
            </th>
            <th class="px-4 py-3 font-medium">
              {{ t('artifactTypes.col.rag') }}
            </th>
            <th class="px-4 py-3 font-medium">
              {{ t('artifactTypes.col.status') }}
            </th>
            <th class="px-4 py-3 font-medium text-right">
              {{ t('artifactTypes.col.actions') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="type in types"
            :key="type.id"
            class="border-b border-border/20 last:border-0"
            data-testid="type-row"
          >
            <td class="px-4 py-3 font-medium text-foreground">
              {{ type.name }}
              <span
                v-if="type.builtin"
                class="ml-1.5 px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground"
              >{{ t('artifactTypes.builtin') }}</span>
            </td>
            <td class="px-4 py-3 text-muted-foreground font-mono text-xs">
              {{ type.key }}
            </td>
            <td class="px-4 py-3 text-muted-foreground">
              {{ t(`projects.artifacts.carrier.${type.carrier}`) }}
            </td>
            <td class="px-4 py-3">
              <span v-if="type.ragable" class="icon-[lucide--check] text-emerald-600" />
              <span v-else class="text-muted-foreground/50">—</span>
            </td>
            <td class="px-4 py-3">
              <span
                class="px-2 py-0.5 rounded-full text-xs font-medium"
                :class="type.enabled ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-muted text-muted-foreground'"
              >
                {{ type.enabled ? t('artifactTypes.statusEnabled') : t('artifactTypes.statusDisabled') }}
              </span>
            </td>
            <td class="px-4 py-3">
              <div class="flex items-center justify-end gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  :data-testid="`toggle-${type.key}`"
                  @click="toggleEnabled(type)"
                >
                  {{ type.enabled ? t('artifactTypes.disable') : t('artifactTypes.enable') }}
                </Button>
                <TooltipProvider v-if="deleteDisabledReason(type)">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <span class="inline-block">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled
                          :data-testid="`delete-${type.key}`"
                          class="text-muted-foreground/50"
                        >
                          <span class="icon-[lucide--trash-2]" />
                        </Button>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>{{ deleteDisabledReason(type) }}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <Button
                  v-else
                  size="sm"
                  variant="ghost"
                  class="text-destructive hover:text-destructive"
                  :data-testid="`delete-${type.key}`"
                  @click="removeType(type)"
                >
                  <span class="icon-[lucide--trash-2]" />
                </Button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </PageContainer>
</template>
