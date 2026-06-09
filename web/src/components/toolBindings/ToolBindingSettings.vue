<script setup lang="ts">
/**
 * 工具令牌绑定区容器
 *
 * 仿 AccessTokenSettings 编排：onMounted 并行拉取可绑定工具 + 当前绑定
 * （并确保 access token store 有数据供绑定下拉）；ToolBindDialog 绑定/换绑、
 * AlertDialog 二次确认解绑；错误走 useErrorHandler，成功走 useToast。
 *
 * 安全核心（T-10-05）：store 仅缓存绑定/工具元数据，明文绝无来源；
 * 本组件不引入任何明文渲染路径。
 */
import type { BindableToolDto, ToolBindingDto, ToolBindingUpsertPayload } from '~/types/toolBinding'
import { onMounted, ref } from 'vue'
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
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useAccessTokenStore } from '~/stores/accessTokens'
import { useToolBindingStore } from '~/stores/toolBindings'
import ToolBindDialog from './ToolBindDialog.vue'
import ToolBindingTable from './ToolBindingTable.vue'

const store = useToolBindingStore()
const tokenStore = useAccessTokenStore()
const { handleError } = useErrorHandler()
const toast = useToast()

// ==== 本地状态 ====
const bindOpen = ref(false)
const bindTarget = ref<BindableToolDto | null>(null)
const unbindTarget = ref<ToolBindingDto | null>(null)
const unbindConfirmOpen = ref(false)

onMounted(() => {
  store.fetchBindable().catch(e => handleError(e, '加载可绑定工具'))
  store.fetchBindings().catch(e => handleError(e, '加载工具绑定'))
  // 确保绑定下拉有令牌数据可选。
  tokenStore.fetchTokens().catch(e => handleError(e, '加载 Access Token'))
})

// ==== Handlers ====
function onBindRequest(tool: BindableToolDto) {
  bindTarget.value = tool
  bindOpen.value = true
}

async function onBindSubmit(payload: ToolBindingUpsertPayload) {
  try {
    await store.upsertBinding(payload)
    toast.success('工具令牌已绑定')
    bindOpen.value = false
  }
  catch (e) {
    handleError(e, '绑定工具令牌')
  }
}

function onUnbindRequest(binding: ToolBindingDto) {
  unbindTarget.value = binding
  unbindConfirmOpen.value = true
}

async function onConfirmUnbind() {
  if (!unbindTarget.value)
    return
  try {
    await store.unbindBinding(unbindTarget.value.id)
    toast.success('工具令牌已解绑')
  }
  catch (e) {
    handleError(e, '解绑工具令牌')
  }
  finally {
    unbindConfirmOpen.value = false
    unbindTarget.value = null
  }
}
</script>

<template>
  <section class="space-y-6">
    <!-- 列表 -->
    <ToolBindingTable
      :tools="store.bindableTools"
      :bindings="store.bindings"
      @bind="onBindRequest"
      @unbind="onUnbindRequest"
    />

    <!-- 绑定 / 换绑对话框 -->
    <ToolBindDialog
      v-model:open="bindOpen"
      :tool="bindTarget"
      @submit="onBindSubmit"
    />

    <!-- 解绑二次确认 -->
    <AlertDialog v-model:open="unbindConfirmOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>解除此绑定？</AlertDialogTitle>
          <AlertDialogDescription>
            解绑后该工具将不再以此令牌身份执行（在途任务跑完不受影响），确认解绑？
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            @click="onConfirmUnbind"
          >
            解绑
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>
</template>
