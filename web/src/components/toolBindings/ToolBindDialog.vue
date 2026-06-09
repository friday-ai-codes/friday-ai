<script setup lang="ts">
/**
 * 工具令牌绑定对话框
 *
 * 从 useAccessTokenStore 读取令牌，**仅列 is_valid===true** 的令牌供选择
 * （per RESEARCH Pitfall 5：绝不让用户绑到已吊销/过期令牌）。
 *
 * 安全（T-10-05）：Select 选项仅展示 name + prefix…suffix 指纹，
 * 绝不渲染任何完整明文（AccessTokenDto 本身无明文字段）。
 */
import type { BindableToolDto, ToolBindingUpsertPayload } from '~/types/toolBinding'
import { computed, ref, watch } from 'vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useAccessTokenStore } from '~/stores/accessTokens'

const props = defineProps<{
  open: boolean
  tool: BindableToolDto | null
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'submit', payload: ToolBindingUpsertPayload): void
}>()

const tokenStore = useAccessTokenStore()

/** 仅列有效令牌（未吊销且未过期）。 */
const validTokens = computed(() =>
  tokenStore.tokens.filter(t => t.is_valid),
)

const selectedTokenId = ref<string>('')

// 对话框每次打开重置选择，避免残留上次选择。
watch(
  () => props.open,
  (v) => {
    if (v)
      selectedTokenId.value = ''
  },
)

/** 令牌指纹：prefix…suffix（非完整明文）。 */
function fingerprint(prefix: string, suffix: string): string {
  return suffix ? `${prefix}…${suffix}` : prefix
}

function onConfirm() {
  if (!props.tool || !selectedTokenId.value)
    return
  emit('submit', {
    remote_tool: props.tool.id,
    access_token: selectedTokenId.value,
  })
  emit('update:open', false)
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="flex max-w-lg flex-col gap-0 overflow-hidden p-0">
      <DialogHeader class="border-b border-border/50 px-6 py-4 text-left">
        <DialogTitle class="text-base font-semibold">
          绑定工具令牌
        </DialogTitle>
        <DialogDescription class="text-xs text-muted-foreground">
          为
          <span v-if="tool" class="font-medium text-foreground">{{ tool.name }}</span>
          选择一把有效令牌；调用时将以令牌所有者身份执行。
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-4 px-6 py-5">
        <div class="space-y-2">
          <label class="text-sm font-medium">选择令牌</label>
          <Select v-model="selectedTokenId">
            <SelectTrigger class="w-full">
              <SelectValue placeholder="从有效令牌中选择…" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="token in validTokens"
                :key="token.id"
                :value="token.id"
              >
                {{ token.name }}
                <span class="ml-2 font-mono text-xs text-muted-foreground">
                  {{ fingerprint(token.token_prefix, token.token_suffix) }}
                </span>
              </SelectItem>
            </SelectContent>
          </Select>
          <p v-if="validTokens.length === 0" class="text-xs text-muted-foreground">
            暂无有效令牌，请先在上方 Access Tokens 区创建。
          </p>
        </div>
      </div>

      <div class="flex justify-end gap-2 border-t border-border/50 px-6 py-4">
        <Button variant="outline" @click="emit('update:open', false)">
          取消
        </Button>
        <Button :disabled="!selectedTokenId" @click="onConfirm">
          确认绑定
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
