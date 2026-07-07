/**
 * Renderer 端 IPC 类型 — 从 preload 暴露的 window.api 推导
 */
export type Api = import('../../electron/preload').Api
