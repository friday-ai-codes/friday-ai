import { VueQueryPlugin } from '@tanstack/vue-query'
import { createHead } from '@vueuse/head'
import { createPinia } from 'pinia'
import { setupLayouts } from 'virtual:generated-layouts'
import { createApp } from 'vue'
import { createVfm } from 'vue-final-modal'
import { createI18n } from 'vue-i18n'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from 'vue-router/auto-routes'

import { getSetupStatus } from '~/api/setup'
import { hasResumableSetup } from '~/lib/setupProgress'
import zhCN from '~/locales/zh-CN.json'
import App from './App.vue'
import { useAuthStore } from './stores/auth'
import '@vue-flow/core/dist/style.css'
import 'vue-final-modal/style.css'
import 'vue-sonner/style.css'
import '~/styles/main.css'

// 路由配置
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: setupLayouts(routes),
  // 页面切换时重置滚动位置：避免从「知识」底部切到「首页」仍停留在底部。
  // 浏览器前进/后退恢复历史位置；带 hash 时锚点定位；其余一律回到顶部。
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition)
      return savedPosition
    if (to.hash)
      return { el: to.hash, top: 80, behavior: 'smooth' }
    if (to.path === from.path)
      return {}
    return { top: 0, left: 0 }
  },
})

// Pinia 状态管理
const pinia = createPinia()

// 国际化
const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en',
  messages: {
    'zh-CN': zhCN,
  },
})

// Head 管理
const head = createHead()

// Vue Final Modal
const vfm = createVfm()

// 创建应用
const app = createApp(App)

app.use(pinia) // 先注册 Pinia
app.use(VueQueryPlugin) // TanStack Query
app.use(router)
app.use(i18n)
app.use(head)
app.use(vfm)

// 路由守卫
router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // ── Step 1：初始化状态检测（每次 app 首次守卫触发时检查一次）──
  if (!authStore.setupStatusChecked) {
    try {
      const status = await getSetupStatus()
      authStore.needsSetup = status.needs_setup
    }
    catch {
      // fail-safe：后端不可达时按「已初始化」处理，
      // 防止误导向向导重置/接管生产实例（T-1-04）
      authStore.needsSetup = false
    }
    authStore.setupStatusChecked = true
  }

  // ── Step 2：setup 路由守卫（必须在 initAuth 之前）──
  // Vue Router 4：返回值即结果——返回路由跳转、返回 true 放行（不再用 next() 回调）。
  if (authStore.needsSetup && to.path !== '/setup') {
    return '/setup'
  }
  if (!authStore.needsSetup && to.path === '/setup') {
    // 管理员已创建（needs_setup=false）但首启向导仍在进行（provider/feishu/rag），
    // 刷新后允许停留在 /setup 恢复进度，避免“直接进去了”。完成后进度被清除即正常重定向。
    if (hasResumableSetup()) {
      return true
    }
    return '/login'
  }

  // ── Step 3：原有认证守卫（不变，/setup 已加入 publicPages）──

  // 初始化认证状态（应用启动时恢复登录）
  if (!authStore.isInitialized) {
    await authStore.initAuth()
  }

  // 公开页面和强制修改密码页面
  const publicPages = ['/login', '/force-change-password', '/403', '/oidc/callback', '/invite', '/setup']
  const authRequired = !publicPages.some(p => to.path === p || to.path.startsWith(`${p}/`))

  if (authRequired && !authStore.isAuthenticated) {
    // 需要认证但未登录 -> 跳转登录页
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.path === '/login' && authStore.isAuthenticated) {
    // 已登录访问登录页 -> 检查是否需要修改密码
    if (authStore.mustChangePassword) {
      return '/force-change-password'
    }
    return '/'
  }

  // 如果需要强制修改密码，只允许访问强制修改密码页面
  if (authStore.isAuthenticated && authStore.mustChangePassword && to.path !== '/force-change-password') {
    return '/force-change-password'
  }

  // 检查管理员专属页面
  if (to.meta.requiresAdmin && !authStore.isAdmin) {
    return '/403'
  }

  return true
})

// 监听 403 事件，跳转无权访问页面
function onForbidden() {
  router.push('/403')
}

// 监听 401 登出事件（多标签页场景：其他标签页登出后 refresh 失败触发）
function onLogout() {
  const authStore = useAuthStore()
  authStore.$reset()
  router.push('/login')
}

window.addEventListener('auth:forbidden', onForbidden)
window.addEventListener('auth:logout', onLogout)

// HMR 热重载时移除旧监听器，防止累积
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    window.removeEventListener('auth:forbidden', onForbidden)
    window.removeEventListener('auth:logout', onLogout)
  })
}

app.mount('#app')
