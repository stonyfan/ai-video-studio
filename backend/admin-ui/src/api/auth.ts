import axios from 'axios'
import client from './client'

export interface User {
  id: number
  username: string
  role: 'user' | 'admin'
  license_expires_at: string | null
  is_active: boolean
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  expires_in: number
  token_type: string
  user: User
}

export interface RefreshResponse {
  access_token: string
  expires_in: number
}

export const authApi = {
  async login(username: string, password: string): Promise<LoginResponse> {
    const r = await client.post('/auth/login', {
      username,
      password,
      device_fp: `admin-ui-${navigator.userAgent.length}`,
      user_agent: navigator.userAgent.slice(0, 255),
      session_type: 'web',
    })
    return r.data
  },

  async logout(): Promise<void> {
    await client.post('/auth/logout')
  },

  async me(): Promise<User> {
    const r = await client.get('/auth/me')
    return r.data
  },

  /** 用 refresh_token 换新的 access_token（不走 client 拦截器，避免循环） */
  async refresh(refreshToken: string): Promise<RefreshResponse> {
    const r = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
    return r.data
  },
}
