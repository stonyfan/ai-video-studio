/**
 * Preload — 通过 contextBridge 安全暴露 IPC API
 *
 * 暴露的 API 在 window.api 上，类型见 src/api/ipc.ts
 *
 * 事件订阅（main → renderer）通过 ipcRenderer.on 注册
 */
import { contextBridge, ipcRenderer } from 'electron'

const api = {
  // auth
  auth: {
    login: (username: string, password: string) =>
      ipcRenderer.invoke('auth:login', { username, password }),
    logout: () => ipcRenderer.invoke('auth:logout'),
    getCurrentUser: () => ipcRenderer.invoke('auth:getCurrentUser'),
    onSessionInvalid: (cb: (payload: { reason: string }) => void) => {
      const handler = (_e: unknown, payload: { reason: string }) => cb(payload)
      ipcRenderer.on('auth:session-invalid', handler)
      return () => ipcRenderer.removeListener('auth:session-invalid', handler)
    },
    onLicenseExpired: (cb: (payload: { reason: string }) => void) => {
      const handler = (_e: unknown, payload: { reason: string }) => cb(payload)
      ipcRenderer.on('auth:license-expired', handler)
      return () => ipcRenderer.removeListener('auth:license-expired', handler)
    }
  },

  // config
  config: {
    getAll: () => ipcRenderer.invoke('config:getAll'),
    setBackendUrl: (url: string) =>
      ipcRenderer.invoke('config:setBackendUrl', { url }),
    setProviderKey: (provider: 'qwen-vl' | 'doubao', key: string, model?: string) =>
      ipcRenderer.invoke('config:setProviderKey', { provider, key, model })
  },

  // worker
  worker: {
    startJob: (opts: unknown) => ipcRenderer.invoke('worker:startJob', opts),
    cancel: (jobId: string) => ipcRenderer.invoke('worker:cancel', { jobId }),
    listJobs: () => ipcRenderer.invoke('worker:listJobs'),
    openFolder: (jobId: string) => ipcRenderer.invoke('worker:openFolder', { jobId }),
    onProgress: (cb: (p: { jobId: string; progress: unknown }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; progress: unknown }) => cb(p)
      ipcRenderer.on('job:progress', handler)
      return () => ipcRenderer.removeListener('job:progress', handler)
    },
    onLog: (cb: (p: { jobId: string; line: string; level?: string }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; line: string; level?: string }) => cb(p)
      ipcRenderer.on('job:log', handler)
      return () => ipcRenderer.removeListener('job:log', handler)
    },
    onDone: (cb: (p: { jobId: string; result: unknown }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; result: unknown }) => cb(p)
      ipcRenderer.on('job:done', handler)
      return () => ipcRenderer.removeListener('job:done', handler)
    },
    onFailed: (cb: (p: { jobId: string; code: number; message: string; result?: unknown }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; code: number; message: string; result?: unknown }) => cb(p)
      ipcRenderer.on('job:failed', handler)
      return () => ipcRenderer.removeListener('job:failed', handler)
    }
  },

  // dialog
  dialog: {
    chooseFolder: () => ipcRenderer.invoke('dialog:chooseFolder')
  },

  // app
  app: {
    getVersion: () => ipcRenderer.invoke('app:getVersion'),
    getBackendUrl: () => ipcRenderer.invoke('app:getBackendUrl')
  }
}

contextBridge.exposeInMainWorld('api', api)

// 暴露类型给 renderer（import type 用）
export type Api = typeof api
