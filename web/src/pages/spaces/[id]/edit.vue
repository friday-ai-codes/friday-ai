<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'

const route = useRoute('/spaces/[id]/edit')
const router = useRouter()
const spacesStore = useSpacesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

const spaceId = route.params.id

useHead({
  title: '编辑空间 - Friday AI',
})

// 表单数据
const form = reactive({
  name: '',
  description: '',
  feishu_project_key: '',
})

// 加载空间数据
const loading = ref(true)

onMounted(async () => {
  try {
    const spaceData = await spacesStore.fetchSpace(spaceId)
    if (spaceData) {
      form.name = spaceData.name
      form.description = spaceData.description || ''
      form.feishu_project_key = spaceData.feishu_project_key || ''
    }
  }
  catch (e: unknown) {
    handleError(e, '加载空间')
    router.push('/spaces')
  }
  finally {
    loading.value = false
  }
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
    await spacesStore.updateSpace(spaceId, {
      name: form.name,
      description: form.description || undefined,
      feishu_project_key: form.feishu_project_key || null,
    })
    success('更新成功', '空间信息已更新')
    router.push(`/spaces/${spaceId}`)
  }
  catch (e: unknown) {
    handleError(e, '更新空间')
  }
  finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="max-w-2xl mx-auto space-y-8">
    <!-- 返回按钮 -->
    <RouterLink :to="`/spaces/${spaceId}`" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
      <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
      返回空间详情
    </RouterLink>

    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="spinner" text="加载空间信息..." />

    <!-- 表单卡片 -->
    <div v-else class="relative">
      <!-- 卡片光晕 -->
      <!-- 卡片主体 -->
      <div class="relative bg-card/80 backdrop-blur-sm rounded-2xl border border-border/50 overflow-hidden">
        <!-- 标题区域 -->
        <div class="p-6 border-b border-border/50">
          <div class="flex items-center gap-3">
            <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
              <span class="icon-[lucide--pencil] text-2xl text-primary" />
            </div>
            <div>
              <h1 class="text-xl font-bold">
                编辑空间
              </h1>
              <p class="text-sm text-muted-foreground">
                修改空间基本信息
              </p>
            </div>
          </div>
        </div>

        <!-- 表单内容 -->
        <form class="p-6 space-y-6" @submit.prevent="handleSubmit">
          <!-- 空间名称 -->
          <div class="space-y-2">
            <Label for="name" class="flex items-center gap-1">
              空间名称
              <span class="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              v-model="form.name"
              placeholder="例如：智课空间"
              class="h-11 bg-muted/30 border-border/50 focus:border-primary/50"
              :class="{ 'border-destructive': errors.name }"
            />
            <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
              <span class="icon-[lucide--alert-circle]" />
              {{ errors.name }}
            </p>
          </div>

          <!-- 空间描述 -->
          <div class="space-y-2">
            <Label for="description">空间描述</Label>
            <Textarea
              id="description"
              v-model="form.description"
              placeholder="空间的简要描述..."
              rows="3"
              class="bg-muted/30 border-border/50 focus:border-primary/50 resize-none"
            />
          </div>

          <!-- 飞书项目 Key -->
          <div class="space-y-2">
            <Label for="feishu_project_key" class="flex items-center gap-2">
              飞书项目 Key
              <span class="text-xs text-muted-foreground font-normal">（可选）</span>
            </Label>
            <Input
              id="feishu_project_key"
              v-model="form.feishu_project_key"
              placeholder="例如：project_key"
              class="h-11 bg-muted/30 border-border/50 focus:border-primary/50"
            />
            <p class="text-xs text-muted-foreground">
              用于飞书项目管理 API 调用
            </p>
          </div>

          <!-- 提交按钮 -->
          <div class="flex items-center gap-4 pt-4 border-t border-border/50">
            <Button
              type="submit"
              :disabled="submitting"
              class="group relative overflow-hidden"
            >
              <span class="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
              <template v-if="submitting">
                <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
                保存中...
              </template>
              <template v-else>
                <span class="icon-[lucide--save] mr-2" />
                保存更改
              </template>
            </Button>
            <RouterLink :to="`/spaces/${spaceId}`">
              <Button type="button" variant="outline">
                取消
              </Button>
            </RouterLink>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
