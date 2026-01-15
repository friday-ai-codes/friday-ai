/// <reference types="vite/client" />
// 声明 Vue 文件类型
declare module '*.vue' {
 import type { DefineComponent } from 'vue'
 const component: DefineComponent<object, object, unknown>
 export default component
}
// 声明虚拟模块
declare module 'virtual:generated-layouts' {
 import type { RouteRecordRaw } from 'vue-router'
 export function setupLayouts(routes: RouteRecordRaw): RouteRecordRaw
}
declare module 'vue-router/auto-routes' {
 import type { RouteRecordRaw } from 'vue-router'
 export const routes: RouteRecordRaw
}
// 扩展 ImportMeta
interface ImportMetaEnv {
 readonly VITE_APP_TITLE: string
 readonly BASE_URL: string
}
interface ImportMeta {
 readonly env: ImportMetaEnv
}
