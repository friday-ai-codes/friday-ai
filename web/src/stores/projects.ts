/**
 * Projects Store
 * 管理项目列表和项目相关操作
 */
import type { FeishuConfig, GitCredential, Project, ProjectCreate, ProjectUpdate } from '~/types'
import { projectsApi } from '~/api'
export const useProjectsStore = defineStore('projects', => {
 // ============================================================================
 // State
 // ============================================================================
 const projects = ref<Project>
 const currentProject = ref<Project | null>(null)
 const currentCredential = ref<GitCredential | null>(null)
 const currentFeishuConfig = ref<FeishuConfig | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 const projectById = computed( => {
 return (id: string) => projects.value.find(p => p.id === id)
 })
 const projectCount = computed( => projects.value.length)
 // ============================================================================
 // Actions
 // ============================================================================
 /**
 * 获取项目列表
 */
 async function fetchProjects {
 loading.value = true
 error.value = null
 try {
 projects.value = await projectsApi.list
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取项目列表失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 获取单个项目详情
 */
 async function fetchProject(projectId: string) {
 loading.value = true
 error.value = null
 try {
 currentProject.value = await projectsApi.get(projectId)
 return currentProject.value
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取项目详情失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 创建项目
 */
 async function createProject(data: ProjectCreate) {
 loading.value = true
 error.value = null
 try {
 const newProject = await projectsApi.create(data)
 projects.value.unshift(newProject)
 return newProject
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '创建项目失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 更新项目
 */
 async function updateProject(projectId: string, data: ProjectUpdate) {
 loading.value = true
 error.value = null
 try {
 const updatedProject = await projectsApi.update(projectId, data)
 // 更新列表中的项目
 const index = projects.value.findIndex(p => p.id === projectId)
 if (index !== -1) {
 projects.value[index] = updatedProject
 }
 // 更新当前项目
 if (currentProject.value?.id === projectId) {
 currentProject.value = updatedProject
 }
 return updatedProject
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '更新项目失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 删除项目
 */
 async function deleteProject(projectId: string) {
 loading.value = true
 error.value = null
 try {
 await projectsApi.delete(projectId)
 // 从列表中移除
 projects.value = projects.value.filter(p => p.id !== projectId)
 // 清空当前项目
 if (currentProject.value?.id === projectId) {
 currentProject.value = null
 }
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '删除项目失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 // ============================================================================
 // 凭证管理
 // ============================================================================
 /**
 * 获取项目凭证
 */
 async function fetchCredential(projectId: string) {
 try {
 currentCredential.value = await projectsApi.getCredential(projectId)
 return currentCredential.value
 }
 catch {
 // 404 表示没有凭证，不是错误
 currentCredential.value = null
 return null
 }
 }
 /**
 * 上传 SSH 密钥
 */
 async function uploadSshKey(
 projectId: string,
 file: File,
 gitUserName?: string,
 gitUserEmail?: string,
 ) {
 loading.value = true
 error.value = null
 try {
 currentCredential.value = await projectsApi.uploadSshKey(
 projectId,
 file,
 gitUserName,
 gitUserEmail,
 )
 // 更新项目的 has_credential 状态
 const project = projects.value.find(p => p.id === projectId)
 if (project) {
 project.has_credential = true
 }
 if (currentProject.value?.id === projectId) {
 currentProject.value.has_credential = true
 }
 return currentCredential.value
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '上传 SSH 密钥失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 设置 Access Token
 */
 async function setAccessToken(
 projectId: string,
 token: string,
 gitUserName?: string,
 gitUserEmail?: string,
 ) {
 loading.value = true
 error.value = null
 try {
 currentCredential.value = await projectsApi.setAccessToken(
 projectId,
 token,
 gitUserName,
 gitUserEmail,
 )
 // 更新项目的 has_credential 状态
 const project = projects.value.find(p => p.id === projectId)
 if (project) {
 project.has_credential = true
 }
 if (currentProject.value?.id === projectId) {
 currentProject.value.has_credential = true
 }
 return currentCredential.value
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '设置 Access Token 失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 删除凭证
 */
 async function deleteCredential(projectId: string) {
 loading.value = true
 error.value = null
 try {
 await projectsApi.deleteCredential(projectId)
 currentCredential.value = null
 // 更新项目的 has_credential 状态
 const project = projects.value.find(p => p.id === projectId)
 if (project) {
 project.has_credential = false
 }
 if (currentProject.value?.id === projectId) {
 currentProject.value.has_credential = false
 }
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '删除凭证失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 清空当前项目
 */
 function clearCurrent {
 currentProject.value = null
 currentCredential.value = null
 currentFeishuConfig.value = null
 }
 // ============================================================================
 // 飞书配置管理
 // ============================================================================
 /**
 * 获取飞书配置
 */
 async function fetchFeishuConfig(projectId: string) {
 try {
 currentFeishuConfig.value = await projectsApi.getFeishuConfig(projectId)
 return currentFeishuConfig.value
 }
 catch {
 // 404 表示没有配置，不是错误
 currentFeishuConfig.value = null
 return null
 }
 }
 return {
 // State
 projects,
 currentProject,
 currentCredential,
 currentFeishuConfig,
 loading,
 error,
 // Getters
 projectById,
 projectCount,
 // Actions
 fetchProjects,
 fetchProject,
 createProject,
 updateProject,
 deleteProject,
 fetchCredential,
 uploadSshKey,
 setAccessToken,
 deleteCredential,
 fetchFeishuConfig,
 clearCurrent,
 }
})
