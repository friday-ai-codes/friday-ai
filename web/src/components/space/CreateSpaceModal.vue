<script setup lang="ts">
import { VueFinalModal } from 'vue-final-modal'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'

const emit = defineEmits<{
  confirm: [spaceId: string]
  cancel: []
  closed: []
}>()

const spacesStore = useSpacesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 表单数据
const form = reactive({
  name: '',
  description: '',
  feishu_project_key: '',
})

// 表单验证
const errors = reactive({
  name: '',
})

function validate(): boolean {
  errors.name = ''

  if (!form.name.trim()) {
    errors.name = '请输入空间名称'
  }

  return !errors.name
}

// 提交表单
const submitting = ref(false)

async function handleSubmit() {
  if (!validate())
    return

  submitting.value = true
  try {
    const space = await spacesStore.createSpace({
      name: form.name,
      description: form.description || undefined,
      feishu_project_key: form.feishu_project_key || null,
    })
    success('创建成功，空间已创建')
    emit('confirm', space.id)
  }
  catch (e: unknown) {
    handleError(e, '创建空间')
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
          <span class="icon-[lucide--folder-plus] text-xl text-primary" />
        </div>
        <div>
          <h3 class="text-lg font-semibold text-foreground">
            新建空间
          </h3>
          <p class="text-sm text-muted-foreground">
            创建一个新空间来管理飞书工作项和 Git 仓库
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
      <!-- 空间名称 -->
      <div class="space-y-2">
        <Label for="name" class="flex items-center gap-1 text-foreground">
          空间名称
          <span class="text-destructive">*</span>
        </Label>
        <Input
          id="name"
          v-model="form.name"
          placeholder="例如：智课空间"
          class="h-10"
          :class="{ 'border-destructive': errors.name }"
        />
        <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
          <span class="icon-[lucide--alert-circle]" />
          {{ errors.name }}
        </p>
      </div>

      <!-- 空间描述 -->
      <div class="space-y-2">
        <Label for="description" class="text-foreground">空间描述</Label>
        <Textarea
          id="description"
          v-model="form.description"
          placeholder="空间的简要描述..."
          rows="3"
          class="resize-none"
        />
      </div>

      <!-- 飞书项目 Key -->
      <div class="space-y-2">
        <Label for="feishu_project_key" class="flex items-center gap-2 text-foreground">
          飞书项目 Key
          <span class="text-xs text-muted-foreground font-normal">(可选)</span>
        </Label>
        <Input
          id="feishu_project_key"
          v-model="form.feishu_project_key"
          placeholder="例如：project_key"
          class="h-10"
        />
        <p class="text-xs text-muted-foreground">
          用于飞书项目管理 API 调用，可稍后在项目详情中配置
        </p>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
        <Button type="button" variant="outline" :disabled="submitting" @click="handleCancel">
          取消
        </Button>
        <Button type="submit" :disabled="submitting">
          <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          <span v-else class="icon-[lucide--plus] mr-2" />
          创建空间
        </Button>
      </div>
    </form>
  </VueFinalModal>
</template>
