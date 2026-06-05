import axios from 'axios'
import { configGlobal } from './hosts'

// LowLevelHelper — axios 锚点识别（work item）
export function get<T>(url: string, params = {}, config = {}) {
  return axios.get<T, T>(`${configGlobal.api}${url}`, { params, ...config })
}

export function post<T>(url: string, data = {}, config = {}) {
  return axios.post<T, T>(`${configGlobal.api}${url}`, data, config)
}

// ApiWrapper — 调用 LowLevelHelper（work item）
export function getUserInfo(params = {}) {
  return get('/api/user/info', params)
}

export function createOrder(data: { productId: string; quantity: number }) {
  return post('/api/order/create', data)
}

// 非 export function，不应被识别
function internalHelper(url: string) {
  return axios.get(url)
}
