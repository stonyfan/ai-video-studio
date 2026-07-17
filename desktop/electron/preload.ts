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
    setProviderKey: (provider: 'qwen-vl' | 'doubao' | 'glm', key: string, model?: string) =>
      ipcRenderer.invoke('config:setProviderKey', { provider, key, model }),
    setModelMode: (mode: 'A' | 'C') =>
      ipcRenderer.invoke('config:setModelMode', { mode })
  },

  // worker
  worker: {
    startJob: (opts: unknown) => ipcRenderer.invoke('worker:startJob', opts),
    resumeJob: (jobId: string) => ipcRenderer.invoke('worker:resumeJob', { jobId }),
    cancel: (jobId: string) => ipcRenderer.invoke('worker:cancel', { jobId }),
    listJobs: () => ipcRenderer.invoke('worker:listJobs'),
    getJobDetail: (jobId: string) => ipcRenderer.invoke('worker:getJobDetail', { jobId }),
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
  },

  // updater
  updater: {
    check: () => ipcRenderer.invoke('updater:check'),
    download: () => ipcRenderer.invoke('updater:download'),
    install: () => ipcRenderer.invoke('updater:install'),
    getState: () => ipcRenderer.invoke('updater:getState'),
    remindLater: () => ipcRenderer.invoke('updater:remindLater'),
    onAvailable: (cb: (info: UpdateInfo) => void) => {
      const handler = (_e: unknown, info: UpdateInfo) => cb(info)
      ipcRenderer.on('update:available', handler)
      return () => ipcRenderer.removeListener('update:available', handler)
    },
    onDeprecated: (cb: (info: UpdateInfo) => void) => {
      const handler = (_e: unknown, info: UpdateInfo) => cb(info)
      ipcRenderer.on('update:deprecated', handler)
      return () => ipcRenderer.removeListener('update:deprecated', handler)
    },
    onForceUpgrade: (cb: (info: UpdateInfo) => void) => {
      const handler = (_e: unknown, info: UpdateInfo) => cb(info)
      ipcRenderer.on('update:force-upgrade', handler)
      return () => ipcRenderer.removeListener('update:force-upgrade', handler)
    },
    onProgress: (cb: (p: { progress: number }) => void) => {
      const handler = (_e: unknown, p: { progress: number }) => cb(p)
      ipcRenderer.on('update:progress', handler)
      return () => ipcRenderer.removeListener('update:progress', handler)
    },
    onDownloaded: (cb: (p: { installerPath: string; version: string | null; inGrace?: boolean }) => void) => {
      const handler = (_e: unknown, p: { installerPath: string; version: string | null; inGrace?: boolean }) => cb(p)
      ipcRenderer.on('update:downloaded', handler)
      return () => ipcRenderer.removeListener('update:downloaded', handler)
    },
    onFailed: (cb: (p: { error: string }) => void) => {
      const handler = (_e: unknown, p: { error: string }) => cb(p)
      ipcRenderer.on('update:failed', handler)
      return () => ipcRenderer.removeListener('update:failed', handler)
    }
  },

  // error report
  errorReport: {
    submit: (message: string, jobId?: string) =>
      ipcRenderer.invoke('error-report:submit', { message, jobId })
  },

  // prompt set
  promptSet: {
    sync: () => ipcRenderer.invoke('prompt-set:sync'),
    getState: () => ipcRenderer.invoke('prompt-set:getState'),
    listOptions: () => ipcRenderer.invoke('prompt-set:listOptions'),
    select: (promptSetId: number) => ipcRenderer.invoke('prompt-set:select', promptSetId),
  },

  // curate (手动剪辑) — subprocess 模式，无轮询
  curate: {
    getData: (jobId: string, inputDir?: string) =>
      ipcRenderer.invoke('curate:getData', { jobId, inputDir }),
    buildPreviews: (jobId: string) =>
      ipcRenderer.invoke('curate:buildPreviews', { jobId }),
    submit: (jobId: string, payload: unknown, inputDir?: string) =>
      ipcRenderer.invoke('curate:submit', { jobId, payload, inputDir }),
    regenerate: (jobId: string, payload: unknown, inputDir?: string) =>
      ipcRenderer.invoke('curate:regenerate', { jobId, payload, inputDir }),
    cancel: (jobId: string) =>
      ipcRenderer.invoke('curate:cancel', { jobId }),
    onLog: (cb: (p: { jobId: string; level: string; msg: string }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; level: string; msg: string }) => cb(p)
      ipcRenderer.on('curate:log', handler)
      return () => ipcRenderer.removeListener('curate:log', handler)
    },
    onProgress: (cb: (p: { jobId: string; done: number; todo: number; stage: string; msg: string }) => void) => {
      const handler = (_e: unknown, p: { jobId: string; done: number; todo: number; stage: string; msg: string }) => cb(p)
      ipcRenderer.on('curate:progress', handler)
      return () => ipcRenderer.removeListener('curate:progress', handler)
    }
  }
}

interface UpdateInfo {
  has_update: boolean
  latest_version: string | null
  download_url: string | null
  sha256: string | null
  release_notes: string | null
  min_supported: string | null
  current_deprecated: boolean
  force_upgrade?: boolean
  grace_hours?: number | null
}

contextBridge.exposeInMainWorld('api', api)

// 暴露类型给 renderer（import type 用）
export type Api = typeof api
