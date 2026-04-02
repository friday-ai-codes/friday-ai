<script setup lang="ts">
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
interface Props {
 visible: boolean
 feishuTestReceiveId: string
 feishuTestReceiveIdType: 'open_id' | 'chat_id'
 feishuTestMessage: string
 testingFeishuIM: boolean
 feishuTestResult: { success: boolean, message: string } | null
}
const props = defineProps<Props>
const emit = defineEmits<{
 'update:feishuTestReceiveId': [value: string]
 'update:feishuTestReceiveIdType': [value: 'open_id' | 'chat_id']
 'update:feishuTestMessage': [value: string]
 'test':
}>
</script>
<template>
 <div v-if="props.visible" class="px-6 py-4 border-t border-border/50 space-y-4 bg-muted/20">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--flask-conical] text-amber-500" />
 测试消息发送
 </div>
 <div class="space-y-3">
 <div class="space-y-1.5">
 <Label class="text-sm">发送类型</Label>
 <div class="flex gap-4">
 <label class="flex items-center gap-2 cursor-pointer">
 <input:checked="props.feishuTestReceiveIdType === 'open_id'"
 type="radio"
 value="open_id"
 class="accent-primary"
 @change="emit('update:feishuTestReceiveIdType', 'open_id')"
 >
 <span class="text-sm">用户 (open_id)</span>
 </label>
 <label class="flex items-center gap-2 cursor-pointer">
 <input:checked="props.feishuTestReceiveIdType === 'chat_id'"
 type="radio"
 value="chat_id"
 class="accent-primary"
 @change="emit('update:feishuTestReceiveIdType', 'chat_id')"
 >
 <span class="text-sm">群聊 (chat_id)</span>
 </label>
 </div>
 </div>
 <div class="space-y-1.5">
 <Label class="text-sm">{{ props.feishuTestReceiveIdType === 'chat_id' ? '群聊 ID': '用户 ID' }}</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground":class="props.feishuTestReceiveIdType === 'chat_id' ? 'icon-[lucide--users]': 'icon-[lucide--user]'" />
 <Input:model-value="props.feishuTestReceiveId":placeholder="props.feishuTestReceiveIdType === 'chat_id' ? 'oc_xxxxxxxxxx': 'ou_xxxxxxxxxx'"
 class="pl-10 font-mono text-sm bg-background border-border/50"
 @update:model-value="(v: string | number) => emit('update:feishuTestReceiveId', String(v))"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 {{ props.feishuTestReceiveIdType === 'chat_id' ? '获取方式：把机器人拉入群聊后，从群设置中复制群链接获取': '获取方式：飞书管理后台 -> 成员管理 -> 点击成员 -> 复制 Open ID' }}
 </p>
 </div>
 <div class="space-y-1.5">
 <Label class="text-sm">测试消息</Label>
 <Textarea:model-value="props.feishuTestMessage"
 rows="2"
 class="text-sm resize-none bg-background border-border/50"
 @update:model-value="(v: string | number) => emit('update:feishuTestMessage', String(v))"
 />
 </div>
 <div class="flex items-center gap-3">
 <button
 class="btn btn-secondary btn-sm":disabled="props.testingFeishuIM"
 @click="emit('test')"
 >
 <span v-if="props.testingFeishuIM" class="icon-[lucide--loader-circle] animate-spin" />
 <span v-else class="icon-[lucide--send]" />
 发送测试消息
 </button>
 <!-- 测试结果 -->
 <div
 v-if="props.feishuTestResult"
 class="flex-1 rounded-lg px-3 py-2 text-xs":class="props.feishuTestResult.success ? 'bg-emerald-500/10 text-emerald-600': 'bg-destructive/10 text-destructive'"
 >
 <span:class="props.feishuTestResult.success ? 'icon-[lucide--check-circle]': 'icon-[lucide--x-circle]'" class="mr-1.5" />
 {{ props.feishuTestResult.message }}
 </div>
 </div>
 </div>
 </div>
</template>
