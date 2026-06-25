<script setup lang="ts">
/**
 * 调用下钻抽屉（UI-04 §5.3）：会话原始 / 调用明细 / webhook 原始，三 tab 切换。
 *
 * 按 context 可用性渲染 tab，并按激活 tab 懒加载（vue-query enabled 受控）：
 * - 会话原始：context.conversationId → getConversationDrilldown(id)
 *   （conversation 元信息 + created_by + messages + related_logs / related_runs 摘要）。
 * - 调用明细：context.runId / requestId → getCallDrilldown({run_id|request_id})
 *   （run + 触发用户(username/fingerprint，**不显 token**) + tool_calls / retrieval /
 *   model_usages / events）。
 * - webhook 原始：context.webhookEventId → getWebhookEvent(id)
 *   （kind / received_at / verified + 脱敏 headers / raw_body）。
 *
 * 安全（T-75-04-02）：**全部原始内容用 `<pre>` / 文本插值渲染，禁 v-html**；后端写入时已
 * redact_for_ledger / redact_secrets_in_text 脱敏，前端只读直出，绝不重拼明文 / token。
 * UI-SPEC §0：骨架 / 错误（ApiError.detail）/ 空态友好；sheet 标题与关闭 aria-label。
 */
import type { CallDrilldown, ConversationDrilldown, WebhookEventRow } from '~/api/system'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { getCallDrilldown, getConversationDrilldown, getWebhookEvent } from '~/api/system'
import { Badge } from '~/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '~/components/ui/sheet'
import { Skeleton } from '~/components/ui/skeleton'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '~/components/ui/tabs'
import { extractErrorMessage } from '~/composables/useErrorHandler'
import { EMPTY, formatDateTime } from './format'

export interface DrilldownContext {
  conversationId?: string
  runId?: string
  requestId?: string
  webhookEventId?: number
}

const props = defineProps<{
  open: boolean
  context: DrilldownContext | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

type TabKey = 'conversation' | 'call' | 'webhook'

const hasConversation = computed(() => !!props.context?.conversationId)
const hasCall = computed(() => !!(props.context?.runId || props.context?.requestId))
const hasWebhook = computed(() => props.context?.webhookEventId != null)
const anyAvailable = computed(() => hasConversation.value || hasCall.value || hasWebhook.value)

const activeTab = ref<TabKey>('conversation')

// 打开 / context 变化时，把激活 tab 落到第一个可用维度。
watch(
  () => [props.open, props.context] as const,
  ([open]) => {
    if (!open)
      return
    if (hasConversation.value)
      activeTab.value = 'conversation'
    else if (hasCall.value)
      activeTab.value = 'call'
    else if (hasWebhook.value)
      activeTab.value = 'webhook'
  },
  { immediate: true },
)

// ── 会话原始（懒加载：open + tab 激活 + 有 conversationId） ─────────────
const convEnabled = computed(() => props.open && activeTab.value === 'conversation' && hasConversation.value)
const convQuery = useQuery({
  queryKey: ['obs-drilldown-conversation', computed(() => props.context?.conversationId)] as const,
  queryFn: () => getConversationDrilldown(props.context!.conversationId!),
  enabled: convEnabled,
  retry: 1,
})
const conversation = computed<ConversationDrilldown | undefined>(() => convQuery.data.value)

// ── 调用明细 ─────────────────────────────────────────────────────────────
const callEnabled = computed(() => props.open && activeTab.value === 'call' && hasCall.value)
const callQuery = useQuery({
  queryKey: ['obs-drilldown-call', computed(() => props.context?.runId), computed(() => props.context?.requestId)] as const,
  queryFn: () => getCallDrilldown({ run_id: props.context?.runId, request_id: props.context?.requestId }),
  enabled: callEnabled,
  retry: 1,
})
const call = computed<CallDrilldown | undefined>(() => callQuery.data.value)

// ── webhook 原始 ─────────────────────────────────────────────────────────
const webhookEnabled = computed(() => props.open && activeTab.value === 'webhook' && hasWebhook.value)
const webhookQuery = useQuery({
  queryKey: ['obs-drilldown-webhook', computed(() => props.context?.webhookEventId)] as const,
  queryFn: () => getWebhookEvent(props.context!.webhookEventId!),
  enabled: webhookEnabled,
  retry: 1,
})
const webhook = computed<WebhookEventRow | undefined>(() => webhookQuery.data.value)

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  }
  catch {
    return String(value)
  }
}

function onOpenChange(v: boolean) {
  emit('update:open', v)
}
</script>

<template>
  <Sheet :open="open" @update:open="onOpenChange">
    <SheetContent class="flex w-full flex-col overflow-hidden sm:max-w-2xl" aria-label="调用下钻详情">
      <SheetHeader>
        <SheetTitle class="flex items-center gap-2">
          <span class="icon-[lucide--search] text-primary" />
          调用下钻
        </SheetTitle>
        <SheetDescription>
          查看该日志关联的会话、调用链与 webhook 原始记录
        </SheetDescription>
      </SheetHeader>

      <div v-if="!anyAvailable" class="flex flex-col items-center gap-2 px-4 py-16 text-center text-muted-foreground">
        <span class="icon-[lucide--unlink] text-2xl opacity-50" />
        <p class="text-sm">
          该日志行没有可下钻的关联记录
        </p>
      </div>

      <Tabs v-else v-model="activeTab" class="flex min-h-0 flex-1 flex-col px-4 pb-4">
        <TabsList class="w-full">
          <TabsTrigger value="conversation" :disabled="!hasConversation" class="flex-1">
            会话原始
          </TabsTrigger>
          <TabsTrigger value="call" :disabled="!hasCall" class="flex-1">
            调用明细
          </TabsTrigger>
          <TabsTrigger value="webhook" :disabled="!hasWebhook" class="flex-1">
            webhook 原始
          </TabsTrigger>
        </TabsList>

        <!-- 会话原始 -->
        <TabsContent value="conversation" class="mt-3 min-h-0 flex-1 overflow-y-auto">
          <div v-if="convQuery.isLoading.value" class="space-y-2">
            <Skeleton v-for="i in 5" :key="i" class="h-12 w-full rounded-lg" />
          </div>
          <div v-else-if="convQuery.isError.value" class="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
            <span class="icon-[lucide--message-square-off] text-2xl opacity-50" />
            <p class="text-sm">
              {{ extractErrorMessage(convQuery.error.value) }}
            </p>
          </div>
          <div v-else-if="conversation" class="space-y-4 text-sm">
            <!-- 会话元信息 -->
            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--messages-square]" /> 会话信息
              </h4>
              <dl class="grid grid-cols-2 gap-x-4 gap-y-2">
                <div class="col-span-2">
                  <dt class="text-xs text-muted-foreground">
                    标题
                  </dt>
                  <dd class="font-medium">
                    {{ conversation.conversation?.title || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    状态
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ conversation.conversation?.status || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    模型
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ conversation.conversation?.model || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    创建者
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ conversation.created_by?.username || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    创建时间
                  </dt>
                  <dd class="font-mono text-xs tabular-nums">
                    {{ formatDateTime(conversation.conversation?.created_at) }}
                  </dd>
                </div>
              </dl>
            </section>

            <!-- 消息（pre 文本，禁 v-html） -->
            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--list]" /> 消息（{{ conversation.messages?.length ?? 0 }}）
              </h4>
              <div v-if="conversation.messages?.length" class="space-y-2">
                <div
                  v-for="msg in conversation.messages"
                  :key="msg.id"
                  class="rounded-lg border border-border/50 p-2.5"
                >
                  <div class="mb-1 flex items-center gap-2">
                    <Badge variant="muted" class="text-[10px] uppercase">
                      {{ msg.role || EMPTY }}
                    </Badge>
                    <span class="font-mono text-[11px] text-muted-foreground tabular-nums">
                      {{ formatDateTime(msg.created_at) }}
                    </span>
                  </div>
                  <pre class="overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs break-all whitespace-pre-wrap">{{ msg.content || EMPTY }}</pre>
                </div>
              </div>
              <p v-else class="text-xs text-muted-foreground">
                无消息
              </p>
            </section>

            <!-- 关联日志 / run 摘要 -->
            <section v-if="conversation.related_logs?.length || conversation.related_runs?.length" class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--link]" /> 关联摘要
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson({ related_logs: conversation.related_logs, related_runs: conversation.related_runs }) }}</pre>
            </section>
          </div>
        </TabsContent>

        <!-- 调用明细 -->
        <TabsContent value="call" class="mt-3 min-h-0 flex-1 overflow-y-auto">
          <div v-if="callQuery.isLoading.value" class="space-y-2">
            <Skeleton v-for="i in 5" :key="i" class="h-12 w-full rounded-lg" />
          </div>
          <div v-else-if="callQuery.isError.value" class="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
            <span class="icon-[lucide--search-x] text-2xl opacity-50" />
            <p class="text-sm">
              该日志未关联到具体的调用链记录
            </p>
          </div>
          <div v-else-if="call" class="space-y-4 text-sm">
            <!-- run + 触发用户（不显 token） -->
            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--play]" /> 调用归因
              </h4>
              <dl class="grid grid-cols-2 gap-x-4 gap-y-2">
                <div>
                  <dt class="text-xs text-muted-foreground">
                    run_id
                  </dt>
                  <dd class="font-mono text-xs break-all">
                    {{ call.run?.run_id || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    状态
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ call.run?.status || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    触发用户
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ call.user?.username || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    fingerprint（哈希）
                  </dt>
                  <dd class="font-mono text-xs break-all text-muted-foreground">
                    {{ call.user?.fingerprint || EMPTY }}
                  </dd>
                </div>
              </dl>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--wrench]" /> 工具调用（{{ call.tool_calls?.length ?? 0 }}）
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(call.tool_calls) }}</pre>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--search-code]" /> 召回（{{ call.retrieval?.length ?? 0 }}）
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(call.retrieval) }}</pre>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--cpu]" /> 模型用量（{{ call.model_usages?.length ?? 0 }}）
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(call.model_usages) }}</pre>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--activity]" /> 事件（{{ call.events?.length ?? 0 }}）
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(call.events) }}</pre>
            </section>
          </div>
        </TabsContent>

        <!-- webhook 原始 -->
        <TabsContent value="webhook" class="mt-3 min-h-0 flex-1 overflow-y-auto">
          <div v-if="webhookQuery.isLoading.value" class="space-y-2">
            <Skeleton v-for="i in 4" :key="i" class="h-12 w-full rounded-lg" />
          </div>
          <div v-else-if="webhookQuery.isError.value" class="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
            <span class="icon-[lucide--webhook] text-2xl opacity-50" />
            <p class="text-sm">
              {{ extractErrorMessage(webhookQuery.error.value) }}
            </p>
          </div>
          <div v-else-if="webhook" class="space-y-4 text-sm">
            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--webhook]" /> webhook 信息
              </h4>
              <dl class="grid grid-cols-2 gap-x-4 gap-y-2">
                <div>
                  <dt class="text-xs text-muted-foreground">
                    类型 kind
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ webhook.kind || EMPTY }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    校验
                  </dt>
                  <dd>
                    <Badge :variant="webhook.verified ? 'success' : 'warning'" class="text-[10px]">
                      {{ webhook.verified ? '已校验' : '未校验' }}
                    </Badge>
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    接收时间
                  </dt>
                  <dd class="font-mono text-xs tabular-nums">
                    {{ formatDateTime(webhook.received_at) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs text-muted-foreground">
                    来源 IP
                  </dt>
                  <dd class="font-mono text-xs">
                    {{ webhook.source_ip || EMPTY }}
                  </dd>
                </div>
              </dl>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--file-text]" /> 脱敏 headers
              </h4>
              <pre class="max-h-56 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(webhook.headers) }}</pre>
            </section>

            <section class="space-y-2">
              <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <span class="icon-[lucide--braces]" /> 脱敏 raw_body
              </h4>
              <pre class="max-h-72 overflow-auto rounded-md bg-muted/40 p-2 font-mono text-xs">{{ prettyJson(webhook.raw_body) }}</pre>
            </section>
          </div>
        </TabsContent>
      </Tabs>
    </SheetContent>
  </Sheet>
</template>
