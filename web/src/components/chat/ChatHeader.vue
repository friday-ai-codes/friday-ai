<script setup lang="ts">
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import ProviderSelect from '~/components/provider/ProviderSelect.vue'
import { ROLE_OPTIONS } from '~/types/chat'
import { getModels } from '~/api/chat'
import type { Model } from '~/api/chat'
const chatStore = useChatStore
const projectsStore = useProjectsStore
// 获取模型列表
const models = ref<Model>
onMounted(async => {
 try {
 const resp = await getModels(
 chatStore.selectedProvider
 ? { provider_type: chatStore.selectedProvider }: {},
 )
 models.value = resp.models
 }
 catch {
 // 静默处理模型列表加载失败
 }
})
// 监听 Provider 切换，自动刷新模型列表
watch( => chatStore.selectedProvider, async (newProvider) => {
 if (newProvider) {
 chatStore.selectedModel = '__default__'
 models.value =
 try {
 const resp = await getModels({ provider_type: newProvider })
 models.value = resp.models
 }
 catch {
 // 静默处理
 }
 }
})
</script>
<template>
 <div class="px-4 py-2 border-b border-border/40 bg-background/80 backdrop-blur-sm flex items-center gap-3 flex-wrap">
 <!-- 项目选择 -->
 <Select v-model="chatStore.selectedProjectId">
 <SelectTrigger class="w-48 text-xs">
 <SelectValue placeholder="选择项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 角色选择 -->
 <Select v-model="chatStore.selectedRole">
 <SelectTrigger class="w-32 text-xs">
 <SelectValue placeholder="角色" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="role in ROLE_OPTIONS":key="role.value":value="role.value"
 >
 {{ role.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- Provider 选择 -->
 <ProviderSelect
 v-model="chatStore.selectedProvider"
 config-source="conversation"
 />
 <!-- 模型选择 -->
 <Select v-model="chatStore.selectedModel">
 <SelectTrigger class="w-56 text-xs">
 <SelectValue placeholder="模型（默认）" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__default__">
 系统默认
 </SelectItem>
 <SelectItem
 v-for="model in models":key="model.id":value="model.id"
 >
 {{ model.name || model.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
</template>
