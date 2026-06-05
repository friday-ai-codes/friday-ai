<script setup lang="ts">
import type {
  ProviderCredentialCreatePayload,
  ProviderCredentialDto,
  ProviderCredentialUpdatePayload,
} from '~/types/providerCredential'
/**
 * Provider 凭证管理容器组件
 *
 * scope-aware 设计：
 * - scope='system' → 挂 /admin/providers（由 ）
 * - scope='project' → 挂 /spaces/:id/settings#providers（由 复用）
 *
 * 职责：
 * - mount 调 store.fetchCredentials + store.fetchProviderTypes（动态表单数据源）
 * - 渲染 PageHeader（标题按 scope 切换）+ 新建 CTA + ListTable（或空态）
 * - 承接 ListTable emits：edit / delete / toggleActive / testConnection / refreshModels
 * - Form Dialog 新建/编辑；未保存退出二次确认
 * - AlertDialog 删除二次确认（UI-SPEC §Destructive）
 *
 * Typography：PageHeader 标题 text-xl font-semibold，描述 text-xs text-muted-foreground；
 * 严格遵守 UI-SPEC 2-weight 契约（font-normal + font-semibold）。
 */
import { computed, onMounted, ref } from 'vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { getProviderBrandColor } from '~/lib/providerBrandColors'
import { useProviderCredentialStore } from '~/stores/providerCredential'
import ProviderCredentialForm from './ProviderCredentialForm.vue'
import ProviderCredentialListTable from './ProviderCredentialListTable.vue'

interface Props {
  scope: 'system' | 'project'
  spaceId?: string
  /** 嵌入模式：隐藏独立 PageHeader，由外层卡片承载标题 */
  embedded?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  spaceId: undefined,
  embedded: false,
})

const store = useProviderCredentialStore()
const { handleError } = useErrorHandler()
const toast = useToast()

// ==== 文案（UI-SPEC §Copywriting L123-127 + §Empty State L152-158）====
const pageTitle = computed(() =>
  props.scope === 'system' ? 'Provider 凭证管理' : 'Provider 凭证',
)
const pageDesc = computed(() =>
  props.scope === 'system'
    ? '管理系统级 LLM Provider 凭证，供全部空间共享；空间级覆盖请前往空间设置页'
    : '仅本空间可见的 Provider 凭证，覆盖系统默认',
)
const emptyTitle = computed(() =>
  props.scope === 'system'
    ? '尚未配置任何 Provider 凭证'
    : '本空间暂未配置覆盖凭证',
)
const emptyDesc = computed(() =>
  props.scope === 'system'
    ? '至少添加一条凭证后，工作流与对话才能调用 LLM。建议先添加默认 Anthropic 凭证。'
    : '未配置时将沿用系统默认 Provider 凭证。如需本空间独享某个 Provider，点击新建。',
)
const emptyCta = computed(() =>
  props.scope === 'system' ? '新建凭证' : '新建空间凭证',
)
const emptyIcon = computed(() =>
  props.scope === 'system' ? 'icon-[lucide--key-round]' : 'icon-[lucide--folder-lock]',
)

// ==== 本地状态 ====
const formOpen = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formInitial = ref<ProviderCredentialDto | undefined>(undefined)
const formDirty = ref(false)

const deleteTarget = ref<ProviderCredentialDto | null>(null)
const deleteConfirmOpen = ref(false)

const cancelConfirmOpen = ref(false)

// ==== 弹窗标题区品牌识别（edit 模式按 provider 品牌色 + 图标，create 用统一 primary）====
const PROVIDER_ICON: Record<string, string> = {
  anthropic: 'icon-[simple-icons--anthropic]',
  openai_chat: 'icon-[simple-icons--openai]',
  openai_responses: 'icon-[simple-icons--openai]',
  gemini: 'icon-[simple-icons--googlegemini]',
  ollama: 'icon-[lucide--cpu]',
}

const dialogBrand = computed(() => {
  if (formMode.value === 'edit' && formInitial.value) {
    const brand = getProviderBrandColor(formInitial.value.provider_type)
    return { bg: brand.bg, text: brand.text, icon: PROVIDER_ICON[formInitial.value.provider_type] ?? 'icon-[lucide--key-round]' }
  }
  return { bg: 'bg-primary/10', text: 'text-primary', icon: 'icon-[lucide--plus]' }
})

// ==== 生命周期 ====
onMounted(() => {
  // 并行拉取 provider types + credentials，错误由 handleError 承接，不阻塞另一路
  void store
    .fetchProviderTypes()
    .catch(e => handleError(e, '加载 Provider 类型'))
  void store
    .fetchCredentials({ scope: props.scope, spaceId: props.spaceId })
    .catch(e => handleError(e, '加载凭证列表'))
})

// ==== Handlers ====
function openCreate() {
  formMode.value = 'create'
  formInitial.value = undefined
  formDirty.value = false
  formOpen.value = true
}

function onEdit(c: ProviderCredentialDto) {
  formMode.value = 'edit'
  formInitial.value = c
  formDirty.value = false
  formOpen.value = true
}

async function onSubmit(
  payload: ProviderCredentialCreatePayload | ProviderCredentialUpdatePayload,
) {
  try {
    if (formMode.value === 'create') {
      // 空间级容器补 scope / scope_id 兜底（避免表单未设时跨 scope 创建）
      if (props.scope === 'project' && props.spaceId) {
        ;(payload as ProviderCredentialCreatePayload).scope = 'project'
        ;(payload as ProviderCredentialCreatePayload).scope_id = props.spaceId
      }
      await store.createCredential(payload as ProviderCredentialCreatePayload)
      toast.success('凭证已保存')
    }
    else {
      if (!formInitial.value)
        throw new Error('编辑目标丢失，请重新打开对话框')
      const id = formInitial.value.id
      if (!id) {
        throw new Error(
          `凭证 ID 缺失（formInitial.id=${id}），可能是列表数据未包含 id 字段或缓存脏数据。请刷新页面后重试。`,
        )
      }
      await store.updateCredential(
        id,
        payload as ProviderCredentialUpdatePayload,
      )
      toast.success('凭证已更新')
    }
    formOpen.value = false
    formDirty.value = false
  }
  catch (e) {
    handleError(e, '保存凭证')
  }
}

function onCancel() {
  if (formDirty.value)
    cancelConfirmOpen.value = true
  else
    formOpen.value = false
}

function onConfirmDiscard() {
  cancelConfirmOpen.value = false
  formOpen.value = false
  formDirty.value = false
}

function onDelete(c: ProviderCredentialDto) {
  deleteTarget.value = c
  deleteConfirmOpen.value = true
}

async function onConfirmDelete() {
  if (!deleteTarget.value)
    return
  const target = deleteTarget.value
  try {
    await store.deleteCredential(target.id)
    toast.success(`凭证 ${target.name} 已删除`)
  }
  catch (e) {
    handleError(e, '删除凭证')
  }
  finally {
    deleteConfirmOpen.value = false
    deleteTarget.value = null
  }
}

async function onToggleActive(c: ProviderCredentialDto) {
  const wasActive = c.is_active
  try {
    await store.toggleActive(c.id)
    toast.success(wasActive ? `凭证 ${c.name} 已禁用` : `凭证 ${c.name} 已启用`)
  }
  catch (e) {
    handleError(e, '切换状态')
  }
}

async function onTestConnection(c: ProviderCredentialDto) {
  try {
    const resp = await store.testConnection(c.id)
    if (resp.status === 'ok')
      toast.success(`${c.name} 连接正常`)
    else
      toast.error(`${c.name} 连接失败`, resp.error ?? '未知错误')
  }
  catch (e) {
    handleError(e, '连接测试')
  }
}

async function onRefreshModels(c: ProviderCredentialDto) {
  try {
    const list = await store.refreshModels(c.id)
    toast.success(`${c.name} 模型清单已更新`, `共 ${list.length} 个模型`)
  }
  catch (e) {
    handleError(e, '刷新模型清单')
  }
}

async function onSetDefault(c: ProviderCredentialDto) {
  try {
    await store.setDefault(c.id)
    toast.success(`已将 ${c.name} 设为默认 ${c.provider_type} 凭证`)
  }
  catch (e) {
    handleError(e, '设置默认凭证')
  }
}

async function onSetDefaultModel(c: ProviderCredentialDto, modelId: string) {
  try {
    await store.updateCredential(c.id, { default_model: modelId })
    toast.success(`${c.name} 默认模型已切换为 ${modelId}`)
  }
  catch (e) {
    handleError(e, '切换默认模型')
  }
}

// 供外层卡片头部「新建凭证」按钮调用（embedded 模式）
defineExpose({ openCreate })
</script>

<template>
  <section class="space-y-8">
    <!-- PageHeader（embedded 模式下由外层卡片承载） -->
    <header v-if="!props.embedded" class="flex items-start justify-between gap-4">
      <div class="space-y-1">
        <h1 class="text-xl font-semibold">
          {{ pageTitle }}
        </h1>
        <p class="text-xs text-muted-foreground">
          {{ pageDesc }}
        </p>
      </div>
      <Button
        v-if="store.credentials.length > 0"
        variant="default"
        @click="openCreate"
      >
        <span class="icon-[lucide--plus] w-4 h-4 mr-1" aria-hidden="true" />
        新建凭证
      </Button>
    </header>

    <!-- embedded 模式：新建按钮由外层卡片头部承载（同标题一行），此处不再渲染 -->

    <!-- 空态（UI-SPEC §Empty State L152-158） -->
    <div
      v-if="!store.loading && store.credentials.length === 0"
      class="flex flex-col items-center py-16 space-y-4"
    >
      <span
        class="w-16 h-16 text-muted-foreground" :class="[emptyIcon]"
        aria-hidden="true"
      />
      <h2 class="text-base font-semibold">
        {{ emptyTitle }}
      </h2>
      <p class="text-sm text-muted-foreground max-w-md text-center font-normal">
        {{ emptyDesc }}
      </p>
      <Button variant="default" @click="openCreate">
        {{ emptyCta }}
      </Button>
    </div>

    <!-- 列表 -->
    <ProviderCredentialListTable
      v-else
      :credentials="store.credentials"
      @edit="onEdit"
      @delete="onDelete"
      @toggle-active="onToggleActive"
      @test-connection="onTestConnection"
      @refresh-models="onRefreshModels"
      @set-default="onSetDefault"
      @set-default-model="onSetDefaultModel"
    />

    <!-- 表单 Dialog（新建/编辑） -->
    <Dialog v-model:open="formOpen">
      <DialogContent
        class="flex max-h-[88vh] max-w-2xl flex-col gap-0 overflow-hidden p-0"
      >
        <DialogHeader
          class="flex-row items-start gap-3 space-y-0 border-b border-border/50 px-6 py-4 text-left"
        >
          <span
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
            :class="dialogBrand.bg"
            aria-hidden="true"
          >
            <span class="h-5 w-5" :class="[dialogBrand.icon, dialogBrand.text]" />
          </span>
          <div class="min-w-0 space-y-1">
            <DialogTitle class="text-base font-semibold">
              {{ formMode === 'create' ? '新建 Provider 凭证' : '编辑 Provider 凭证' }}
            </DialogTitle>
            <DialogDescription class="text-xs text-muted-foreground">
              按所选 Provider 类型填写凭证字段，保存后将加密存储。
            </DialogDescription>
          </div>
        </DialogHeader>
        <ProviderCredentialForm
          :mode="formMode"
          :initial="formInitial"
          :default-scope="props.scope"
          :default-space-id="props.spaceId ?? null"
          @submit="onSubmit"
          @cancel="onCancel"
          @dirty="formDirty = $event"
        />
      </DialogContent>
    </Dialog>

    <!-- 未保存退出二次确认（UI-SPEC §I-5） -->
    <AlertDialog v-model:open="cancelConfirmOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>有未保存的修改</AlertDialogTitle>
          <AlertDialogDescription>
            离开将丢失已填写内容，确认放弃？
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction @click="onConfirmDiscard">
            放弃修改
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <!-- 删除凭证二次确认（UI-SPEC §Destructive L181-184） -->
    <AlertDialog v-model:open="deleteConfirmOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除此凭证？</AlertDialogTitle>
          <AlertDialogDescription>
            删除后
            <strong>{{ deleteTarget?.name }}</strong>
            （{{ deleteTarget?.provider_type }}）将立即对全部空间不可用，已运行的对话 /
            工作流不受影响。此操作不可撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            @click="onConfirmDelete"
          >
            永久删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>
