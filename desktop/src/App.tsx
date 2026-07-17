/**
 * 根组件 — 路由 + Auth 守卫
 *
 * 启动时初始化 auth store（拉本地 config）
 * 未登录访问受保护路由 → 跳 /login
 * 已登录访问 /login → 跳 /
 */
import { useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { ConfigProvider, Spin, Result, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import { useAuthStore } from './store/auth'
import AppLayout from './components/AppLayout'
import UpdateNotifier from './components/UpdateNotifier'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import NewJob from './pages/NewJob'
import JobDetail from './pages/JobDetail'
import Curate from './pages/Curate'
import Settings from './pages/Settings'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const { user, loading } = useAuthStore()
  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  }
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore()
  if (user) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  const init = useAuthStore(s => s.init)
  const error = useAuthStore(s => s.error)

  useEffect(() => {
    init()
  }, [init])

  return (
    <ConfigProvider locale={zhCN} theme={{
      token: { colorPrimary: '#1677ff' }
    }}>
      <AntdApp>
        <UpdateNotifier />
        {error && !window.location.hash.includes('login') && (
          <Result
            status="warning"
            title="初始化失败"
            subTitle={error}
          />
        )}
        <HashRouter>
          <Routes>
            <Route path="/login" element={
              <RedirectIfAuthed><Login /></RedirectIfAuthed>
            } />
            <Route element={
              <RequireAuth><AppLayout /></RequireAuth>
            }>
              <Route path="/" element={<Dashboard />} />
              <Route path="/jobs/new" element={<NewJob />} />
              <Route path="/jobs/:jobId" element={<JobDetail />} />
              <Route path="/jobs/:jobId/curate" element={<Curate />} />
              <Route path="/settings" element={<Settings />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </HashRouter>
      </AntdApp>
    </ConfigProvider>
  )
}
