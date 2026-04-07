<script setup lang="ts">
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { ROLE_OPTIONS } from '~/types/chat'
const chatStore = useChatStore
const projectsStore = useProjectsStore
</script>
<template>
 <div class="chat-header">
 <!-- 项目选择 -->
 <Select v-model="chatStore.selectedProjectId">
 <SelectTrigger class="w-44 text-xs border-border/40 bg-transparent shadow-none">
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
 <SelectTrigger class="w-28 text-xs border-border/40 bg-transparent shadow-none">
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
 </div>
</template>
<style scoped>
.chat-header {
 display: flex;
 align-items: center;
 gap: 0.5rem;
 padding: 0.5rem 1rem;
 border-bottom: 1px solid hsl(var(--border) / 0.3);
}
</style>
