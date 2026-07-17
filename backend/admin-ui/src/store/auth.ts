import { create } from 'zustand'

import { authApi, type User } from '../api/auth'

const STORAGE_KEY = 'admin-ui-auth'

interface PersistedAuth {
  accessToken: string | null
  refreshToken: string | null
  user: User | null
}

function loadPersisted(): PersistedAuth {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { accessToken: null, refreshToken: null, user: null }
    return JSON.parse(raw)
  } catch {
    return { accessToken: null, refreshToken: null, user: null }
  }
}

function persist(auth: PersistedAuth): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(auth))
}

function clearPersisted(): void {
  localStorage.removeItem(STORAGE_KEY)
}

interface AuthState extends PersistedAuth {
  loading: boolean       // 初始化中（恢复会话）
  error: string | null
  init: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** 只清本地（401 拦截器用） */
  logoutLocal: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  ...loadPersisted(),
  loading: true,
  error: null,

  async init() {
    const { accessToken } = get()
    if (!accessToken) {
      set({ loading: false })
      return
    }
    try {
      const user = await authApi.me()
      set({ user, loading: false })
    } catch {
      clearPersisted()
      set({ accessToken: null, refreshToken: null, user: null, loading: false })
    }
  },

  async login(username, password) {
    set({ error: null })
    try {
      const data = await authApi.login(username, password)
      if (data.user.role !== 'admin') {
        throw new Error('需要 admin 权限')
      }
      persist({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
      })
      set({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
      })
    } catch (e) {
      const msg = (e as Error).message || '登录失败'
      set({ error: msg })
      throw e
    }
  },

  async logout() {
    try {
      await authApi.logout()
    } catch {
      // 忽略 — 本地清掉即可
    }
    clearPersisted()
    set({ accessToken: null, refreshToken: null, user: null })
  },

  logoutLocal() {
    clearPersisted()
    set({ accessToken: null, refreshToken: null, user: null })
  },
}))
