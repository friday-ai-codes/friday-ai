<script setup lang="ts">
</script>
<template>
 <section class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center">
 <span class="icon-[lucide--info] text-xl text-muted-foreground" />
 </div>
 <div class="space-y-2">
 <h3 class="font-medium">
 配置优先级说明
 </h3>
 <p class="text-sm text-muted-foreground">
 Claude Code 配置按以下优先级应用（高到低）：
 </p>
 <ol class="list-decimal list-inside space-y-1 text-sm text-muted-foreground ml-2">
 <li><strong class="text-foreground">项目级配置</strong> - 在项目设置中单独配置的值</li>
 <li><strong class="text-foreground">系统级配置</strong> - 在此页面配置的全局默认值</li>
 </ol>
 </div>
 </div>
 </section>
</template>
