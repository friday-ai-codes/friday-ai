import { createHead } from '@vueuse/head'
import { createPinia } from 'pinia'
import { setupLayouts } from 'virtual:generated-layouts'
import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'
import App from './App.vue'
import '~/styles/main.css'
// 路由配置
const router = createRouter({
 history: createWebHistory(import.meta.env.BASE_URL),
 routes: setupLayouts(routes),
})
// Pinia 状态管理
const pinia = createPinia
// 国际化（预留能力）
const i18n = createI18n({
 legacy: false,
 locale: 'zh-CN',
 fallbackLocale: 'en',
 messages: {},
})
// Head 管理
const head = createHead
// 创建应用
const app = createApp(App)
app.use(router)
app.use(pinia)
app.use(i18n)
app.use(head)
app.mount('#app')
