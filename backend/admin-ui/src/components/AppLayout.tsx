import { useMemo } from 'react'
import { Layout, Menu, Dropdown, Button, Space, Typography } from 'antd'
import {
  DashboardOutlined,
  TeamOutlined,
  CloudUploadOutlined,
  ApiOutlined,
  HistoryOutlined,
  KeyOutlined,
  BarChartOutlined,
  LogoutOutlined,
  DownOutlined,
  BugOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/auth'

const { Sider, Header, Content } = Layout
const { Text } = Typography

export default function AppLayout() {
  const nav = useNavigate()
  const loc = useLocation()
  const { user, logout } = useAuthStore()

  const items = useMemo(() => [
    { key: '/', icon: <DashboardOutlined />, label: <NavLink to="/">Dashboard</NavLink> },
    { key: '/users', icon: <TeamOutlined />, label: <NavLink to="/users">用户</NavLink> },
    { key: '/releases', icon: <CloudUploadOutlined />, label: <NavLink to="/releases">版本</NavLink> },
    { key: '/prompt-sets', icon: <FileTextOutlined />, label: <NavLink to="/prompt-sets">Prompt 集</NavLink> },
    { key: '/providers', icon: <KeyOutlined />, label: <NavLink to="/providers">Provider Keys</NavLink> },
    { key: '/usage', icon: <BarChartOutlined />, label: <NavLink to="/usage">用量</NavLink> },
    { key: '/sessions', icon: <ApiOutlined />, label: <NavLink to="/sessions">会话</NavLink> },
    { key: '/error-reports', icon: <BugOutlined />, label: <NavLink to="/error-reports">错误报告</NavLink> },
    { key: '/audit', icon: <HistoryOutlined />, label: <NavLink to="/audit">审计日志</NavLink> },
  ], [])

  const selectedKey = useMemo(() => {
    // 取最匹配的项（'/' 单独处理）
    if (loc.pathname === '/') return '/'
    return items.filter((it) => it.key !== '/').find((it) => loc.pathname.startsWith(it.key))?.key || '/'
  }, [loc.pathname, items])

  const onLogout = async () => {
    await logout()
    nav('/login', { replace: true })
  }

  const userMenu = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: onLogout,
      },
    ],
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible style={{ background: '#fff' }}>
        <div style={{ height: 56, padding: 16, textAlign: 'center', fontWeight: 600 }}>
          AI Video Studio
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={items}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
          <Dropdown menu={userMenu} trigger={['click']}>
            <Button type="text">
              <Space>
                <Text>{user?.username || '?'}</Text>
                <DownOutlined />
              </Space>
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
