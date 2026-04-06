<script setup lang="ts">
export interface QuickAction {
 icon: string
 title: string
 description: string
 link: string
 iconBg: string
}
defineProps<{
 actions: QuickAction
}>
</script>
<template>
 <section class="flex flex-wrap gap-3">
 <RouterLink
 v-for="action in actions":key="action.title":to="action.link"
 class="group inline-flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-card/80 backdrop-blur-sm border border-border/50 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-200"
 >
 <span class="text-base text-muted-foreground group-hover:text-primary transition-colors":class="`icon-[${action.icon}]`" />
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ action.title }}</span>
 </RouterLink>
 </section>
</template>
