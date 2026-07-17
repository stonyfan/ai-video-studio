/**
 * 应用主框架：左侧导航 + 顶部用户信息
 */
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Tag, App, Alert } from 'antd'
import {
  DashboardOutlined,
  PlusCircleOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  VideoCameraOutlined,
  BugOutlined
} from '@ant-design/icons'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'

import { useAuthStore } from '../store/auth'
import { authApi, appApi, errorReportApi } from '../api/client'

const { Header, Sider, Content } = Layout
const { Text } = Typography

export default function AppLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const { user, logout } = useAuthStore()
  const [collapsed, setCollapsed] = useState(false)
  const [version, setVersion] = useState('?')
  // 授权过期：不踢出（用户可能还是有效的），只禁新建任务
  const [licenseExpired, setLicenseExpired] = useState(false)
  const { modal, message } = App.useApp()

  useEffect(() => {
    appApi.getVersion().then(setVersion)
  }, [])

  // 监听 session 失效 / license 过期事件
  useEffect(() => {
    const off1 = authApi.onSessionInvalid(() => {
      // session 失效：必须重新登录（多设备顶替、token 真失效）
      modal.warning({
        title: '会话已失效',
        content: '可能是因为在其它设备登录，或者授权信息已变更。请重新登录。',
        okText: '重新登录',
        onOk: () => {
          logout()
          nav('/login', { replace: true })
        }
      })
    })
    const off2 = authApi.onLicenseExpired(() => {
      // 授权过期：保留 session（用户身份可能仍有效），只标记禁用新建
      setLicenseExpired(true)
      modal.error({
        title: '授权已过期',
        content: '已完成的任务可继续查看，但不能新建任务。请联系管理员续期。',
        okText: '我知道了'
      })
    })
    return () => { off1(); off2() }
  }, [nav, logout, modal])

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '任务列表' },
    {
      key: '/jobs/new',
      icon: <PlusCircleOutlined />,
      label: licenseExpired ? '新建任务（已禁用）' : '新建任务',
      disabled: licenseExpired
    },
    { key: '/settings', icon: <SettingOutlined />, label: '设置' }
  ]

  const selectedKey = menuItems
    .map(m => m.key)
    .find(k => loc.pathname === k || (k !== '/' && loc.pathname.startsWith(k))) || '/'

  const userMenu = {
    items: [
      {
        key: 'feedback',
        icon: <BugOutlined />,
        label: '反馈问题',
        onClick: () => {
          let messageText = ''
          modal.confirm({
            title: '反馈问题',
            content: (
              <div style={{ marginTop: 8 }}>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  请描述遇到的问题或建议，将自动附带系统信息：
                </Typography.Paragraph>
                <input
                  type="text"
                  placeholder="简要描述..."
                  style={{ width: '100%', padding: '6px 8px', border: '1px solid #d9d9d9', borderRadius: 4 }}
                  onChange={e => { messageText = e.target.value }}
                  autoFocus
                />
              </div>
            ),
            okText: '提交',
            cancelText: '取消',
            onOk: async () => {
              if (!messageText.trim()) {
                message.warning('请填写问题描述')
                return Promise.reject()
              }
              const r = await errorReportApi.submit(messageText.trim())
              if (r.ok) {
                message.success(`已提交（#${r.id}）`)
              } else {
                message.error(r.error || '提交失败')
                return Promise.reject()
              }
            }
          })
        }
      },
      { type: 'divider' as const },
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
          {licenseExpired && (
            <Alert
              type="error"
              message="授权已过期 — 已完成任务可查看，但不能新建任务"
              description="请联系管理员续期。续期后自动恢复，无需重新登录。"
              showIcon
              style={{ marginBottom: 16 }}
            />
          )}
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
