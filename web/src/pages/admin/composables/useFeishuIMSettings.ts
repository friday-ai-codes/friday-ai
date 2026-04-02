import type { Ref } from 'vue'
import type { SettingRead } from '~/api/settings'
import { ref } from 'vue'
import { toast } from 'vue-sonner'
import {
 deleteSetting,
 SettingKey,
 testFeishuIM,
 updateSetting,
} from '~/api/settings'
export function useFeishuIMSettings(
 settings: Ref<SettingRead>,
 loadSettings: => Promise<void>,
) {
 // 表单值
 const feishuAppIdValue = ref('')
 const feishuAppSecretValue = ref('')
 const feishuAppIdDirty = ref(false)
 const feishuAppSecretDirty = ref(false)
 const showFeishuAppSecret = ref(false)
 const savingFeishuIM = ref(false)
 // 飞书 IM 测试
 const feishuTestReceiveId = ref('')
 const feishuTestReceiveIdType = ref<'open_id' | 'chat_id'>('open_id')
 const feishuTestMessage = ref('这是一条测试消息，来自 Friday AI Agent 配置测试。')
 const testingFeishuIM = ref(false)
 const feishuTestResult = ref<{ success: boolean, message: string } | null>(null)
 // 辅助函数
 function getSettingByKey(key: SettingKey): SettingRead | undefined {
 return settings.value.find(s => s.key === key)
 }
 function onFeishuAppIdInput {
 feishuAppIdDirty.value = true
 }
 function onFeishuAppSecretInput {
 feishuAppSecretDirty.value = true
 }
 function hasFeishuIMConfig: boolean {
 return getSettingByKey(SettingKey.FEISHU_APP_ID)?.has_value ?? false
 }
 // 从已加载的 settings 初始化飞书配置值
 function initFromSettings {
 const feishuAppIdSetting = settings.value.find(s => s.key === SettingKey.FEISHU_APP_ID)
 const feishuAppSecretSetting = settings.value.find(s => s.key === SettingKey.FEISHU_APP_SECRET)
 feishuAppIdValue.value = feishuAppIdSetting?.value ?? ''
 feishuAppSecretValue.value = (feishuAppSecretSetting?.has_value && feishuAppSecretSetting.value) ? feishuAppSecretSetting.value: ''
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 }
 async function saveFeishuIMConfig {
 if (!feishuAppIdValue.value.trim) {
 toast.error('请输入 App ID')
 return
 }
 const hasExistingSecret = getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value
 if (!feishuAppSecretValue.value.trim && !hasExistingSecret) {
 toast.error('请输入 App Secret')
 return
 }
 savingFeishuIM.value = true
 try {
 const promises: Promise<unknown> =
 if (feishuAppIdDirty.value && feishuAppIdValue.value.trim) {
 promises.push(updateSetting(SettingKey.FEISHU_APP_ID, feishuAppIdValue.value.trim))
 }
 if (feishuAppSecretDirty.value && feishuAppSecretValue.value.trim) {
 promises.push(updateSetting(SettingKey.FEISHU_APP_SECRET, feishuAppSecretValue.value.trim))
 }
 if (promises.length > 0) {
 await Promise.all(promises)
 toast.success('飞书 IM 配置已保存')
 feishuAppSecretValue.value = ''
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 await loadSettings
 }
 else {
 toast.info('没有需要保存的更改')
 }
 }
 catch {
 toast.error('保存失败')
 }
 finally {
 savingFeishuIM.value = false
 }
 }
 async function removeFeishuIMConfig {
 savingFeishuIM.value = true
 try {
 await Promise.all([
 deleteSetting(SettingKey.FEISHU_APP_ID),
 deleteSetting(SettingKey.FEISHU_APP_SECRET),
 ])
 toast.success('飞书 IM 配置已删除')
 feishuAppIdValue.value = ''
 feishuAppSecretValue.value = ''
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 await loadSettings
 }
 catch {
 toast.error('删除失败')
 }
 finally {
 savingFeishuIM.value = false
 }
 }
 async function testFeishuIMConfig {
 if (!feishuTestReceiveId.value.trim) {
 toast.error(feishuTestReceiveIdType.value === 'chat_id' ? '请输入群聊 ID': '请输入用户 ID')
 return
 }
 testingFeishuIM.value = true
 feishuTestResult.value = null
 try {
 const result = await testFeishuIM({
 receive_id: feishuTestReceiveId.value.trim,
 receive_id_type: feishuTestReceiveIdType.value,
 message: feishuTestMessage.value,
 })
 feishuTestResult.value = result
 if (result.success) {
 toast.success('消息已发送，请检查飞书')
 }
 else {
 toast.error(result.message)
 }
 }
 catch (error) {
 const message = error instanceof Error ? error.message: '测试失败'
 feishuTestResult.value = { success: false, message }
 toast.error(message)
 }
 finally {
 testingFeishuIM.value = false
 }
 }
 return {
 feishuAppIdValue,
 feishuAppSecretValue,
 feishuAppIdDirty,
 feishuAppSecretDirty,
 showFeishuAppSecret,
 savingFeishuIM,
 feishuTestReceiveId,
 feishuTestReceiveIdType,
 feishuTestMessage,
 testingFeishuIM,
 feishuTestResult,
 getSettingByKey,
 onFeishuAppIdInput,
 onFeishuAppSecretInput,
 hasFeishuIMConfig,
 initFromSettings,
 saveFeishuIMConfig,
 removeFeishuIMConfig,
 testFeishuIMConfig,
 }
}
