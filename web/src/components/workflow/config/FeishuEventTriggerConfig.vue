<script setup lang="ts">
import type { FeishuEventTriggerConfig } from '~/types/workflow'
import { computed } from 'vue'

import { Button } from '~/components/ui/button'
import { Label } from '~/components/ui/label'
import { useConfigModel } from '~/composables/useConfigModel'
import { feishuEventTriggerConfigSchema } from '~/types/workflow'

// ============================================================================
// Props & Emits
// ============================================================================

interface Props {
  config: FeishuEventTriggerConfig
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:config', value: FeishuEventTriggerConfig): void
}>()

const { success } = useToast()

// ============================================================================
// Config Model
// ============================================================================

const { field } = useConfigModel({
  config: () => props.config,
  emit: v => emit('update:config', v),
  schema: feishuEventTriggerConfigSchema,
})

// 服务端在保存工作流时回填的专属端点 token（只读）
const endpointToken = field('endpoint_token', '')

// 节点专属校验 token（只读）：飞书规则需随请求发送，webhook 命中端点后比对
const verificationToken = field('verification_token', '')

// 完整端点 URL（客户端按当前 origin 拼接）
const origin = computed(() => {
  if (typeof window !== 'undefined')
    return window.location.origin
  return ''
})

const endpointUrl = computed(() => {
  const token = endpointToken.value
  if (!token)
    return ''
  return `${origin.value}/api/feishu/webhook/${token}/`
})

async function copyUrl() {
  if (!endpointUrl.value)
    return
  try {
    await navigator.clipboard.writeText(endpointUrl.value)
    success('端点 URL 已复制')
  }
  catch {
    // 剪贴板不可用时静默失败
  }
}

async function copyToken() {
  if (!verificationToken.value)
    return
  try {
    await navigator.clipboard.writeText(verificationToken.value)
    success('校验 Token 已复制')
  }
  catch {
    // 剪贴板不可用时静默失败
  }
}
</script>

<template>
  <div class="space-y-5">
    <!-- 说明 -->
    <div class="space-y-2">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--webhook] text-primary" />
        <Label class="text-sm font-medium">飞书事件触发</Label>
      </div>
      <p class="text-xs text-muted-foreground leading-relaxed">
        本节点是一个纯 Webhook 入口。<strong>"何时触发"（工作项类型、状态流转、空间等条件）请在飞书项目的自动化规则里配置</strong>，然后把规则的 Webhook 动作指向下方专属端点即可直达本工作流。
      </p>
    </div>

    <!-- 专属端点 URL -->
    <div class="space-y-2">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--link] text-primary" />
        <Label class="text-sm font-medium">专属端点 URL</Label>
      </div>

      <template v-if="endpointUrl">
        <div class="flex items-center gap-2">
          <code class="flex-1 px-3 py-2 rounded-xl border border-border/50 bg-muted/40 text-xs font-mono break-all">
            {{ endpointUrl }}
          </code>
          <Button
            type="button"
            variant="outline"
            size="sm"
            class="shrink-0"
            @click="copyUrl"
          >
            <span class="icon-[lucide--copy] mr-1" />
            复制
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">
          在飞书自动化规则的「Webhook」动作里，把 URL 填为以上地址即可。
        </p>
      </template>

      <div
        v-else
        class="px-3 py-3 rounded-xl border border-dashed border-border/60 bg-muted/20 text-xs text-muted-foreground"
      >
        <span class="icon-[lucide--info] mr-1 align-middle" />
        保存工作流后将自动生成本节点的专属端点 URL。
      </div>
    </div>

    <!-- 校验 Token（节点专属，纵深防御） -->
    <div v-if="verificationToken" class="space-y-2">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--shield-check] text-primary" />
        <Label class="text-sm font-medium">校验 Token</Label>
      </div>
      <div class="flex items-center gap-2">
        <code class="flex-1 px-3 py-2 rounded-xl border border-border/50 bg-muted/40 text-xs font-mono break-all">
          {{ verificationToken }}
        </code>
        <Button
          type="button"
          variant="outline"
          size="sm"
          class="shrink-0"
          @click="copyToken"
        >
          <span class="icon-[lucide--copy] mr-1" />
          复制
        </Button>
      </div>
      <p class="text-xs text-muted-foreground leading-relaxed">
        在飞书自动化规则的「Webhook」动作里，把请求体的 <code class="text-primary">header.token</code> 设为以上值。
        webhook 命中端点后会校验此 token，<strong>不匹配则拒绝触发</strong>——即使端点 URL 泄露也无法被随意触发。
      </p>
    </div>

    <!-- 配置指引 -->
    <div class="space-y-2 rounded-xl border border-border/50 bg-background/30 p-3">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--list-checks] text-primary" />
        <Label class="text-sm font-medium">飞书侧配置步骤</Label>
      </div>
      <ol class="text-xs text-muted-foreground space-y-1.5 list-decimal pl-4">
        <li>进入飞书项目 → 自动化 → 新建规则。</li>
        <li>配置触发器（如「工作项状态由任意状态变更为 Sprint 计划」）。</li>
        <li>添加「Webhook」动作，URL 填上方专属端点地址。</li>
        <li>保存并启用规则，符合条件的事件将自动触发本工作流。</li>
      </ol>
    </div>
  </div>
</template>
