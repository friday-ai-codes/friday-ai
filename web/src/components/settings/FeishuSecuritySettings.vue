<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getAllSettings, SettingKey, updateSetting } from '~/api/settings'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const { handleError } = useErrorHandler
const { success } = useToast
const encryptKey = ref('')
const signatureRequired = ref(false)
const encryptKeyDirty = ref(false)
const signatureDirty = ref(false)
const saving = ref(false)
const showEncryptKey = ref(false)
const loading = ref(true)
const hasExistingEncryptKey = ref(false)
async function load {
 loading.value = true
 try {
 const settings = await getAllSettings
 const enc = settings.find(s => s.key === SettingKey.FEISHU_ENCRYPT_KEY)
 const sig = settings.find(s => s.key === SettingKey.FEISHU_SIGNATURE_REQUIRED)
 encryptKey.value = enc?.value ?? ''
 hasExistingEncryptKey.value = enc?.has_value ?? false
 signatureRequired.value = sig?.value === 'true'
 encryptKeyDirty.value = false
 signatureDirty.value = false
 }
 catch (e) {
 handleError(e, '加载飞书安全配置')
 }
 finally {
 loading.value = false
 }
}
async function save {
 saving.value = true
 try {
 const promises: Promise<unknown> =
 if (encryptKeyDirty.value) {
 promises.push(updateSetting(SettingKey.FEISHU_ENCRYPT_KEY, encryptKey.value.trim))
 }
 if (signatureDirty.value) {
 promises.push(updateSetting(SettingKey.FEISHU_SIGNATURE_REQUIRED, signatureRequired.value ? 'true': 'false'))
 }
 if (promises.length > 0) {
 await Promise.all(promises)
 success('飞书安全配置已保存')
 if (encryptKeyDirty.value) {
 encryptKey.value = ''
 hasExistingEncryptKey.value = true
 }
 encryptKeyDirty.value = false
 signatureDirty.value = false
 await load
 }
 }
 catch (e) {
 handleError(e, '保存飞书安全配置')
 }
 finally {
 saving.value = false
 }
}
function onEncryptKeyInput {
 encryptKeyDirty.value = true
}
function onSignatureToggle(checked: boolean) {
 signatureRequired.value = checked
 signatureDirty.value = true
}
onMounted(load)
</script>
<template>
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--shield] text-2xl text-primary" />
 </div>
 <div class="flex-1">
 <h2 class="text-lg font-semibold">
 飞书安全配置
 </h2>
 <p class="text-sm text-muted-foreground">
 飞书回调签名验证与加密密钥
 </p>
 </div>
 </div>
 <div class=" space-y-6">
 <div v-if="loading" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 加载中...
 </div>
 <div v-else class="space-y-5">
 <!-- Encrypt Key -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <Label for="feishu-encrypt-key" class="text-sm font-medium">
 加密密钥 (Encrypt Key)
 </Label>
 <span
 v-if="hasExistingEncryptKey && !encryptKeyDirty"
 class="text-xs text-emerald-600"
 >
 (已配置)
 </span>
 <span
 v-else-if="encryptKeyDirty"
 class="text-xs text-amber-500"
 >
 未保存
 </span>
 </div>
 <p class="text-xs text-muted-foreground">
 飞书开放平台事件订阅加密密钥，用于解密推送消息
 </p>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 id="feishu-encrypt-key"
 v-model="encryptKey":type="showEncryptKey ? 'text': 'password'":placeholder="hasExistingEncryptKey ? '••••••••••••••••': '输入 Encrypt Key'"
 class="pl-10 pr-10 font-mono text-sm bg-muted/30 border-border/50"
 @input="onEncryptKeyInput"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="showEncryptKey = !showEncryptKey"
 >
 <span:class="showEncryptKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 </div>
 <!-- Signature Required -->
 <div class="flex items-center justify-between rounded-xl border border-border/30">
 <div>
 <div class="text-sm font-medium mb-1">
 强制签名验证
 <span v-if="signatureDirty" class="text-xs text-amber-500 ml-1">未保存</span>
 </div>
 <p class="text-xs text-muted-foreground">
 要求所有飞书回调请求携带有效签名（生产环境建议开启）
 </p>
 </div>
 <Switch:checked="signatureRequired"
 @update:checked="onSignatureToggle"
 />
 </div>
 <!-- Save -->
 <div class="flex justify-end">
 <Button:disabled="saving || (!encryptKeyDirty && !signatureDirty)"
 @click="save"
 >
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存安全配置
 </Button>
 </div>
 </div>
 </div>
 </div>
</template>
