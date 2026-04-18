<script setup lang="ts">
import type { SettingRead } from '~/api/settings'
import { SettingKey } from '~/api/settings'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
interface Props {
 feishuAppIdValue: string
 feishuAppSecretValue: string
 feishuAppIdDirty: boolean
 feishuAppSecretDirty: boolean
 showFeishuAppSecret: boolean
 savingFeishuIM: boolean
 hasFeishuIMConfig: boolean
 getSettingByKey: (key: SettingKey) => SettingRead | undefined
}
const props = defineProps<Props>
const emit = defineEmits<{
 'update:feishuAppIdValue': [value: string]
 'update:feishuAppSecretValue': [value: string]
 'update:showFeishuAppSecret': [value: boolean]
 'feishuAppIdInput':
 'feishuAppSecretInput':
 'save':
 'remove':
}>
</script>
<template>
 <section class="group relative">
 <div class="card overflow-hidden">
 <!-- 卡片头部 -->
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--message-circle] text-2xl text-primary" />
 </div>
 <div class="flex-1">
 <h2 class="text-lg font-semibold">
 飞书 IM 配置
 </h2>
 <p class="text-sm text-muted-foreground">
 用于 AI Agent 发送飞书消息（提问卡片、通知等）
 </p>
 </div>
 <span
 v-if="props.hasFeishuIMConfig"
 class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-600 bg-emerald-500/10 rounded-full"
 >
 <span class="icon-[lucide--check-circle]" />
 已配置
 </span>
 </div>
 <!-- 表单内容 -->
 <div class=" space-y-6">
 <!-- 说明 -->
 <div class="rounded-lg bg-primary/5 border border-primary/20 text-sm text-muted-foreground space-y-2">
 <p class="font-medium text-primary flex items-center gap-2">
 <span class="icon-[lucide--info]" />
 配置说明
 </p>
 <p>用于 AI Agent 通过飞书发送消息和接收用户回复。</p>
 <p>需要在<strong>飞书开放平台</strong>创建自建应用，并开启消息权限和长连接模式。</p>
 </div>
 <!-- App ID -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="feishu-app-id" class="text-base font-medium">
 App ID
 </Label>
 </div>
 <p class="text-sm text-muted-foreground">
 飞书开放平台 -> 应用管理 -> 凭证与基础信息
 </p>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="feishu-app-id":model-value="props.feishuAppIdValue"
 placeholder="cli_xxxxxxxxxx"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => emit('update:feishuAppIdValue', String(v))"
 @input="emit('feishuAppIdInput')"
 />
 </div>
 </div>
 <!-- App Secret -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="feishu-app-secret" class="text-base font-medium">
 App Secret
 </Label>
 <span
 v-if="props.getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value"
 class="text-xs text-emerald-600"
 >
 (已配置，留空则保持不变)
 </span>
 </div>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 id="feishu-app-secret":model-value="props.feishuAppSecretValue":type="props.showFeishuAppSecret ? 'text': 'password'":placeholder="props.getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value ? '••••••••••••••••': '输入 App Secret'"
 class="pl-10 pr-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => emit('update:feishuAppSecretValue', String(v))"
 @input="emit('feishuAppSecretInput')"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="emit('update:showFeishuAppSecret', !props.showFeishuAppSecret)"
 >
 <span:class="props.showFeishuAppSecret ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 </div>
 </div>
 <!-- 保存按钮区域 -->
 <div class="flex justify-between px-6 py-4 border-t border-border/50">
 <Button
 v-if="props.hasFeishuIMConfig"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="props.savingFeishuIM"
 @click="emit('remove')"
 >
 <span class="icon-[lucide--trash-2]" />
 删除配置
 </Button>
 <div v-else />
 <Button:disabled="props.savingFeishuIM || (!props.feishuAppIdDirty && !props.feishuAppSecretDirty)"
 @click="emit('save')"
 >
 <span v-if="props.savingFeishuIM" class="icon-[lucide--loader-circle] animate-spin" />
 <span v-else class="icon-[lucide--save]" />
 保存 IM 配置
 </Button>
 </div>
 </div>
 </section>
</template>
