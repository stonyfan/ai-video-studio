/**
 * 全局状态：当前用户 + 配置
 *
 * 使用 zustand（轻量，5KB），不用 Redux 的 boilerplate
 */
import { create } from 'zustand'

import { authApi, configApi } from '../api/client'
import type { User, AppConfig } from '../../electron/types'

interface AuthState {
  user: User | null
  config: AppConfig | null
  loading: boolean
  error: string | null

  init: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshConfig: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  config: null,
  loading: false,
  error: null,

  init: async () => {
    set({ loading: true, error: null })
    try {
      const cfg = await configApi.getAll()
      set({ config: cfg, user: cfg.user, loading: false })
    } catch (e) {
      set({ loading: false, error: (e as Error).message })
    }
  },

  login: async (username, password) => {
    set({ loading: true, error: null })
    try {
      const data = await authApi.login(username, password)
      const cfg = await configApi.getAll()
      set({ user: data.user, config: cfg, loading: false })
    } catch (e) {
      set({ loading: false, error: (e as Error).message })
      throw e
    }
  },

  logout: async () => {
    set({ loading: true })
    try {
      await authApi.logout()
    } finally {
      set({ user: null, loading: false })
    }
  },

  refreshConfig: async () => {
    const cfg = await configApi.getAll()
    set({ config: cfg, user: cfg.user })
  },

  clearError: () => set({ error: null })
}))
