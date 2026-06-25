<script setup lang="ts">
import type { Space } from '~/types'
import { onMounted, reactive, ref } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { projectsApi, spacesApi } from '~/api'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'

const emit = defineEmits<{
  confirm: [projectId: string]
  cancel: []
  closed: []
}>()

const { handleError } = useErrorHandler()
const { success } = useToast()

// 可选空间列表（创建项目需先选所属空间）
const spaces = ref<Space[]>([])
const loadingSpaces = ref(true)

const form = reactive({
  space_id: '',
  name: '',
  feishu_project_key: '',
  feishu_board_url: '',
  description: '',
})

const errors = reactive({
  space_id: '',
  name: '',
})

onMounted(async () => {
  try {
    spaces.value = await spacesApi.list()
    if (spaces.value.length === 1)
      form.space_id = spaces.value[0].id
  }
  catch (e: unknown) {
    handleError(e, '加载空间列表')
  }
  finally {
    loadingSpaces.value = false
  }
})

function validate(): boolean {
  errors.space_id = ''
  errors.name = ''
  if (!form.space_id)
    errors.space_id = '请选择所属空间'
  if (!form.name.trim())
    errors.name = '请输入项目名称'
  return !errors.space_id && !errors.name
}

const submitting = ref(false)

async function handleSubmit() {
  if (!validate())
    return

  submitting.value = true
  try {
    const project = await projectsApi.create({
      space_id: form.space_id,
      name: form.name.trim(),
      description: form.description || undefined,
      feishu_project_key: form.feishu_project_key || undefined,
      feishu_board_url: form.feishu_board_url || undefined,
    })
    success('项目创建成功')
    emit('confirm', project.id)
  }
  catch (e: unknown) {
    handleError(e, '创建项目')
  }
  finally {
    submitting.value = false
  }
}

function handleCancel() {
  emit('cancel')
}
</script>

<template>
  <VueFinalModal
    class="flex justify-center items-center"
    content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4"
    overlay-transition="vfm-fade"
    content-transition="vfm-zoom"
    @closed="emit('closed')"
  >
    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-5 border-b border-border/50">
      <div class="flex items-center gap-3">
        <div class="p-2.5 rounded-xl bg-primary/10">
          <span class="icon-[lucide--folder-kanban] text-xl text-primary" />
        </div>
        <div>
          <h3 class="text-lg font-semibold text-foreground">
            新建项目
          </h3>
          <p class="text-sm text-muted-foreground">
            在某个空间下创建项目，关联飞书"项目跟踪"看板
          </p>
        </div>
      </div>
      <button
        type="button"
        class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        @click="handleCancel"
      >
        <span class="icon-[lucide--x] text-lg" />
      </button>
    </div>

    <!-- Body -->
    <form class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
      <!-- 所属空间 -->
      <div class="space-y-2">
        <Label for="space_id" class="flex items-center gap-1 text-foreground">
          所属空间
          <span class="text-destructive">*</span>
        </Label>
        <select
          id="space_id"
          v-model="form.space_id"
          :disabled="loadingSpaces"
          class="flex h-10 w-full rounded-lg border border-border/60 bg-background/90 px-3 py-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-ring/50"
          :class="{ 'border-destructive': errors.space_id }"
        >
          <option value="" disabled>
            {{ loadingSpaces ? '加载中…' : '请选择空间' }}
          </option>
          <option v-for="s in spaces" :key="s.id" :value="s.id">
            {{ s.name }}
          </option>
        </select>
        <p v-if="errors.space_id" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.space_id }}
        </p>
      </div>

      <!-- 项目名称 -->
      <div class="space-y-2">
        <Label for="name" class="flex items-center gap-1 text-foreground">
          项目名称
          <span class="text-destructive">*</span>
        </Label>
        <Input
          id="name"
          v-model="form.name"
          placeholder="例如：v0.15.0 项目聚合根"
          class="h-10"
          :class="{ 'border-destructive': errors.name }"
        />
        <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.name }}
        </p>
      </div>

      <!-- 飞书看板链接 -->
      <div class="space-y-2">
        <Label for="feishu_board_url" class="flex items-center gap-2 text-foreground">
          飞书"项目跟踪"看板链接
          <span class="text-xs text-muted-foreground font-normal">(可选)</span>
        </Label>
        <Input
          id="feishu_board_url"
          v-model="form.feishu_board_url"
          placeholder="https://project.feishu.cn/..."
          class="h-10"
        />
      </div>

      <!-- 飞书项目 Key（幂等键） -->
      <div class="space-y-2">
        <Label for="feishu_project_key" class="flex items-center gap-2 text-foreground">
          飞书项目 Key
          <span class="text-xs text-muted-foreground font-normal">(可选，幂等键)</span>
        </Label>
        <Input
          id="feishu_project_key"
          v-model="form.feishu_project_key"
          placeholder="例如：demo_project"
          class="h-10"
        />
        <p class="text-xs text-muted-foreground">
          同一空间下相同 Key 的项目幂等去重；留空则每次新建独立项目。
        </p>
      </div>

      <!-- 项目描述 -->
      <div class="space-y-2">
        <Label for="description" class="text-foreground">项目描述</Label>
        <Textarea
          id="description"
          v-model="form.description"
          placeholder="项目的简要描述..."
          rows="3"
          class="resize-none"
        />
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
        <Button type="button" variant="outline" :disabled="submitting" @click="handleCancel">
          取消
        </Button>
        <Button type="submit" :disabled="submitting">
          <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          <span v-else class="icon-[lucide--plus] mr-2" />
          创建项目
        </Button>
      </div>
    </form>
  </VueFinalModal>
</template>
