/**
 * Renderer 端 IPC 客户端 — 强类型封装 window.api
 *
 * 所有调用都通过这里，便于：
 * - 类型推导
 * - 集中加错误处理
 * - 后续如果换 RPC 协议（如改用 socket）只改一处
 */
import type { Api } from '../../electron/preload'

declare global {
  interface Window {
    api: Api
  }
}

export const api = window.api

// 把 IPC 暴露给业务模块
export const authApi = api.auth
export const configApi = api.config
export const workerApi = api.worker
export const dialogApi = api.dialog
export const appApi = api.app
export const updaterApi = api.updater
export const errorReportApi = api.errorReport
export const promptSetApi = api.promptSet
export const curateApi = api.curate
