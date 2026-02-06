<script setup lang="ts">
import { X6WorkflowCanvas } from '~/components/workflow/x6'
</script>
<template>
 <div class="w-screen h-screen bg-background">
 <!-- Header -->
 <div class="absolute top-4 left-4 z-10 rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50">
 <h1 class="text-lg font-semibold">
 X6 Canvas Test
 </h1>
 <p class="text-sm text-muted-foreground">
 Drag to pan, Ctrl/Cmd + scroll to zoom
 </p>
 </div>
 <!-- X6 Canvas -->
 <X6WorkflowCanvas />
 </div>
</template>
