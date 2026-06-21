<script setup lang="ts">
/**
 * FeishuConfigModal — 飞书配置管理弹窗
 *
 * 把原独立路由页 `pages/spaces/[id]/feishu.vue` 的全部功能迁入空间详情页弹窗：
 *  - 飞书项目集成（插件 ID / Secret / 用户 Key，保存 / 测试连接 / 删除）— 复用 FeishuConfigForm
 *  - 飞书文档导出（目标文件夹 Token）
 *  - Webhook 配置说明
 *
 * 配置变更后 emit('updated')，由详情页刷新飞书配置状态徽标。
 * 点击「去设置」飞书项目 Key 时 emit('edit-space')，由详情页关闭本弹窗并打开编辑空间弹窗。
 */
import type { FeishuDocConfig } from '~/api/spaces'
import type { FeishuConfig } from '~/types'
import { getFeishuConfig, getFeishuDocConfig, updateFeishuDocConfig } from '~/api/spaces'
import { FeishuConfigForm } from '~/components/feishu'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { useErrorHandler } from '~/composables/useErrorHandler'

const props = defineProps<{
  spaceId: string
}>()

const emit = defineEmits<{
  updated: []
  editSpace: []
}>()

const open = defineModel<boolean>('open', { default: false })

const { handleError } = useErrorHandler()
const { success } = useToast()

// 飞书插件配置
const loading = ref(false)
const feishuConfig = ref<FeishuConfig | null>(null)

// 飞书文档导出配置
const docConfig = ref<FeishuDocConfig | null>(null)
const folderToken = ref('')
const savingDocConfig = ref(false)

// Webhook URL（在客户端计算）—— 空间级共享端点（向后兼容 / 副作用入口）。
// 注意：工作流触发推荐使用各 feishu_event_trigger 节点的专属端点 URL。
const webhookUrl = computed(() => {
  if (typeof window !== 'undefined') {
    return `${window.location.origin}/api/feishu/webhook/`
  }
  return '/api/feishu/webhook/'
})

async function loadData() {
  loading.value = true
  try {
    try {
      feishuConfig.value = await getFeishuConfig(props.spaceId)
    }
    catch {
      feishuConfig.value = null
    }
    try {
      docConfig.value = await getFeishuDocConfig(props.spaceId)
      folderToken.value = docConfig.value.feishu_doc_folder_token
    }
    catch {
      docConfig.value = null
    }
  }
  finally {
    loading.value = false
  }
}

// 弹窗打开时加载配置
watch(open, (isOpen) => {
  if (isOpen)
    loadData()
}, { immediate: true })

async function saveDocConfig() {
  savingDocConfig.value = true
  try {
    await updateFeishuDocConfig(props.spaceId, {
      feishu_doc_folder_token: folderToken.value,
    })
    success('保存成功', '飞书文档导出配置已更新')
  }
  catch (e: unknown) {
    handleError(e, '保存飞书文档导出配置')
  }
  finally {
    savingDocConfig.value = false
  }
}

// 插件配置更新后刷新本地状态并通知详情页
async function handleUpdated() {
  try {
    feishuConfig.value = await getFeishuConfig(props.spaceId)
  }
  catch {
    feishuConfig.value = null
  }
  emit('updated')
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <span class="icon-[lucide--message-square] text-primary" />
          飞书配置
        </DialogTitle>
        <DialogDescription>
          配置飞书插件凭证与文档导出，用于接收 Webhook 和调用飞书项目 API
        </DialogDescription>
      </DialogHeader>

      <!-- 加载状态 -->
      <LoadingState v-if="loading" variant="skeleton" :count="2" />

      <div v-else class="space-y-6">
        <!-- 飞书配置表单 -->
        <FeishuConfigForm
          :space-id="spaceId"
          :config="feishuConfig"
          @updated="handleUpdated"
          @edit-space="emit('editSpace')"
        />

        <!-- 飞书文档导出配置 -->
        <div class="card">
          <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
            <span class="icon-[lucide--file-up] text-primary" />
            <h2 class="font-semibold">
              飞书文档导出
            </h2>
          </div>
          <div class="p-5 space-y-4">
            <div class="space-y-2">
              <label class="text-sm font-medium">目标文件夹 Token</label>
              <Input
                v-model="folderToken"
                placeholder="输入飞书文件夹 token"
                class="font-mono"
              />
              <p class="text-xs text-muted-foreground">
                在飞书中打开目标文件夹，从 URL 中复制 token（如 https://feishu.cn/drive/folder/xxxxx 中的 xxxxx）
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              :disabled="savingDocConfig"
              @click="saveDocConfig"
            >
              <span v-if="savingDocConfig" class="icon-[lucide--loader-2] animate-spin mr-1" />
              保存
            </Button>
          </div>
        </div>

        <!-- 使用说明 -->
        <div class="p-5 rounded-2xl border border-dashed border-border/50 bg-card/80">
          <div class="flex items-start gap-3">
            <span class="icon-[lucide--info] text-xl text-emerald-500 shrink-0 mt-0.5" />
            <div class="space-y-3">
              <h3 class="font-semibold">
                配置说明
              </h3>
              <ol class="list-decimal list-inside space-y-2 text-sm text-muted-foreground">
                <li>
                  在
                  <button type="button" class="text-primary hover:underline" @click="emit('editSpace')">
                    编辑空间
                  </button>
                  中填写「飞书项目 Key」（飞书项目 URL 中域名后的第一段路径），用于匹配 Webhook 事件来源
                </li>
                <li>在飞书项目管理后台创建插件，获取插件 ID 和插件 Secret</li>
                <li>在插件权限页面申请飞书项目相关权限（如获取工作项详情）</li>
                <li>在飞书项目中配置自动化规则，添加 Webhook 操作</li>
                <li class="flex items-start gap-2">
                  <span>Webhook URL 填写：</span>
                  <code class="px-2 py-1 bg-muted/50 rounded-lg text-xs font-mono border border-border/50">{{ webhookUrl }}</code>
                </li>
                <li>Webhook Token 在空间详情页管理，请在飞书自动化规则中填写相同的 Token</li>
              </ol>
            </div>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
