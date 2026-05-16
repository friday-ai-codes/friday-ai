import axios from 'axios'
// VITE_API_URL 变体
export function httpGet<T>(url: string, params = {}) {
 return axios.get<T, T>(`${import.meta.env.VITE_API_URL}${url}`, { params })
}
export function fetchUserProfile(userId: string) {
 return httpGet<{ name: string; avatar: string }>(`/user/profile/${userId}`)
}
// VUE_APP_API_URL 变体
export function vueAppGet<T>(url: string) {
 return axios.get<T, T>(`${import.meta.env.VUE_APP_API_URL}${url}`)
}
export function getSystemConfig {
 return vueAppGet<{ theme: string }>('/system/config')
}
