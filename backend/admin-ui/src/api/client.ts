import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { notification } from 'antd'

import { useAuthStore } from '../store/auth'
import { authApi } from './auth'

const client: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
})

// 请求拦截器：注入 Authorization Bearer
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const { accessToken } = useAuthStore.getState()
  if (accessToken) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

// ===== silent refresh =====
type PendingResolver = (token: string | null) => void
let isRefreshing = false
let pendingQueue: PendingResolver[] = []

function notifySubscribers(token: string | null) {
  pendingQueue.forEach(fn => fn(token))
  pendingQueue = []
}

async function tryRefresh(): Promise<string | null> {
  const { refreshToken, logoutLocal } = useAuthStore.getState()
  if (!refreshToken) return null
  try {
    const data = await authApi.refresh(refreshToken)
    useAuthStore.setState({
      accessToken: data.access_token,
    })
    // 同步到 localStorage
    try {
      const raw = localStorage.getItem('admin-ui-auth')
      if (raw) {
        const parsed = JSON.parse(raw)
        parsed.accessToken = data.access_token
        localStorage.setItem('admin-ui-auth', JSON.stringify(parsed))
      }
    } catch {
      // ignore
    }
    return data.access_token
  } catch {
    logoutLocal()
    return null
  }
}

// 响应拦截器
client.interceptors.response.use(
  (resp) => resp,
  async (err: AxiosError) => {
    const original = err.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const status = err.response?.status

    // 401 且未重试过 & 不是 login/refresh 自己 → 尝试 refresh
    if (status === 401 && original && !original._retried) {
      const url = original.url || ''
      const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/refresh')
      if (!isAuthEndpoint) {
        original._retried = true
        if (!isRefreshing) {
          isRefreshing = true
          try {
            const newToken = await tryRefresh()
            isRefreshing = false
            if (newToken) {
              notifySubscribers(newToken)
              original.headers = original.headers || {}
              original.headers.Authorization = `Bearer ${newToken}`
              return client(original)
            }
          } catch (e) {
            isRefreshing = false
            notifySubscribers(null)
            return Promise.reject(e)
          }
        } else {
          // 已经在 refresh 了，等结果
          return new Promise((resolve, reject) => {
            pendingQueue.push((token: string | null) => {
              if (!token) {
                reject(err)
                return
              }
              original.headers = original.headers || {}
              original.headers.Authorization = `Bearer ${token}`
              resolve(client(original))
            })
          })
        }
      }
    }

    // 全局错误提示（除 401，401 由组件提示）
    if (status && status >= 500) {
      const detail = (err.response?.data as any)?.detail || err.message
      notification.error({
        message: '服务器错误',
        description: typeof detail === 'string' ? detail : JSON.stringify(detail),
        placement: 'topRight',
      })
    } else if (!err.response) {
      // 网络错误
      notification.error({
        message: '网络错误',
        description: err.message,
        placement: 'topRight',
      })
    }

    return Promise.reject(err)
  }
)

export default client
