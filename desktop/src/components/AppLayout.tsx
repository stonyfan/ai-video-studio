/**
 * 应用主框架：左侧导航 + 顶部用户信息
 */
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Tag } from 'antd'
import {
  DashboardOutlined,
  PlusCircleOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  VideoCameraOutlined
} from '@ant-design/icons'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'

import { useAuthStore } from '../store/auth'
import { authApi, appApi } from '../api/client'

const { Header, Sider, Content } = Layout
const { Text } = Typography

export default function AppLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const { user, logout } = useAuthStore()
  const [collapsed, setCollapsed] = useState(false)
  const [version, setVersion] = useState('?')

  useEffect(() => {
    appApi.getVersion().then(setVersion)
  }, [])

  // 监听 session 失效事件
  useEffect(() => {
    const off1 = authApi.onSessionInvalid(() => {
      alert('会话已失效（可能在其它设备登录），请重新登录')
      logout()
      nav('/login', { replace: true })
    })
    const off2 = authApi.onLicenseExpired(() => {
      alert('授权已过期，请联系管理员续期')
      logout()
      nav('/login', { replace: true })
    })
    return () => { off1(); off2() }
  }, [nav, logout])

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '任务列表' },
    { key: '/jobs/new', icon: <PlusCircleOutlined />, label: '新建任务' },
    { key: '/settings', icon: <SettingOutlined />, label: '设置' }
  ]

  const selectedKey = menuItems
    .map(m => m.key)
    .find(k => loc.pathname === k || (k !== '/' && loc.pathname.startsWith(k))) || '/'

  const userMenu = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: async () => {
          await logout()
          nav('/login', { replace: true })
        }
      }
    ]
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}
             theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
        <div style={{
          height: 56, display: 'flex', alignItems: 'center',
          justifyContent: 'center', borderBottom: '1px solid #f0f0f0'
        }}>
          <VideoCameraOutlined style={{ fontSize: 24, color: '#1677ff' }} />
          {!collapsed && (
            <Text strong style={{ marginLeft: 8, fontSize: 16 }}>
              AI Video
            </Text>
          )}
        </div>
        <Menu mode="inline" selectedKeys={[selectedKey]} items={menuItems}
              onClick={({ key }) => nav(key)} style={{ borderRight: 0 }} />
      </Sider>
      <Layout>
        <Header style={{
          background: '#fff', padding: '0 24px',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderBottom: '1px solid #f0f0f0'
        }}>
          <Text type="secondary">v{version}</Text>
          <Dropdown menu={userMenu}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} />
              <Text>{user?.username || '未登录'}</Text>
              {user?.role === 'admin' && <Tag color="gold">admin</Tag>}
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
