import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { ConfigProvider, Spin, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import { useAuthStore } from './store/auth'
import AppLayout from './components/AppLayout'
import ErrorBoundary from './components/ErrorBoundary'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Users from './pages/Users'
import Releases from './pages/Releases'
import Providers from './pages/Providers'
import Usage from './pages/Usage'
import Sessions from './pages/Sessions'
import AuditLogs from './pages/AuditLogs'
import ErrorReports from './pages/ErrorReports'
import PromptSets from './pages/PromptSets'

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const { user, loading } = useAuthStore()
  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }
  if (!user || user.role !== 'admin') {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  }
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { user } = useAuthStore()
  if (user && user.role === 'admin') {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

export default function App() {
  const init = useAuthStore((s) => s.init)

  useEffect(() => {
    init()
  }, [init])

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff' } }}>
      <AntdApp>
        <ErrorBoundary>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={
                <RedirectIfAuthed><Login /></RedirectIfAuthed>
              } />
              <Route element={
                <RequireAdmin><AppLayout /></RequireAdmin>
              }>
                <Route path="/" element={<Dashboard />} />
                <Route path="/users" element={<Users />} />
                <Route path="/releases" element={<Releases />} />
                <Route path="/prompt-sets" element={<PromptSets />} />
                <Route path="/providers" element={<Providers />} />
                <Route path="/usage" element={<Usage />} />
                <Route path="/sessions" element={<Sessions />} />
                <Route path="/audit" element={<AuditLogs />} />
                <Route path="/error-reports" element={<ErrorReports />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </ErrorBoundary>
      </AntdApp>
    </ConfigProvider>
  )
}
