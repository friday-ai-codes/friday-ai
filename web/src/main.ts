import { VueQueryPlugin } from '@tanstack/vue-query'
import { createHead } from '@vueuse/head'
import { createPinia } from 'pinia'
import { setupLayouts } from 'virtual:generated-layouts'
import { createApp } from 'vue'
import { createVfm } from 'vue-final-modal'
import { createI18n } from 'vue-i18n'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'
import App from './App.vue'
import { useAuthStore } from './stores/auth'
import 'vue-final-modal/style.css'
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
// Vue Final Modal
const vfm = createVfm
// 创建应用
const app = createApp(App)
app.use(pinia) // 先注册 Pinia
app.use(VueQueryPlugin) // TanStack Query
app.use(router)
app.use(i18n)
app.use(head)
app.use(vfm)
// 路由守卫
router.beforeEach(async (to, from, next) => {
 const authStore = useAuthStore
 // 初始化认证状态（应用启动时恢复登录）
 if (!authStore.isInitialized) {
 await authStore.initAuth
 }
 // 公开页面和强制修改密码页面
 const publicPages = ['/login', '/force-change-password']
 const authRequired = !publicPages.includes(to.path)
 if (authRequired && !authStore.isAuthenticated) {
 // 需要认证但未登录 -> 跳转登录页
 return next({ path: '/login', query: { redirect: to.fullPath } })
 }
 if (to.path === '/login' && authStore.isAuthenticated) {
 // 已登录访问登录页 -> 检查是否需要修改密码
 if (authStore.mustChangePassword) {
 return next('/force-change-password')
 }
 return next('/')
 }
 // 如果需要强制修改密码，只允许访问强制修改密码页面
 if (authStore.isAuthenticated && authStore.mustChangePassword && to.path !== '/force-change-password') {
 return next('/force-change-password')
 }
 next
})
app.mount('#app')
