/**
 * 登录页：用户名 + 密码
 *
 * 默认后端地址：http://localhost:8000/api/v1
 * 如果改后端 URL，输入框旁边有"配置"按钮
 */
import { Card, Form, Input, Button, Alert, Space, Typography, Modal } from 'antd'
import { CloudServerOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import { configApi } from '../api/client'

const { Title, Text, Link } = Typography

export default function Login() {
  const nav = useNavigate()
  const { login, loading, error, clearError } = useAuthStore()
  const [backendUrl, setBackendUrl] = useState('')
  const [showSettings, setShowSettings] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      await login(values.username, values.password)
      nav('/', { replace: true })
    } catch {
      // error 在 store 里
    }
  }

  const onSaveBackend = async () => {
    if (backendUrl.trim()) {
      await configApi.setBackendUrl(backendUrl.trim())
      setShowSettings(false)
      setBackendUrl('')
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <Card style={{ width: 400, boxShadow: '0 8px 32px rgba(0,0,0,0.2)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0 }}>AI Video Studio</Title>
          <Text type="secondary">智能视频剪辑平台</Text>
        </div>

        {error && (
          <Alert
            type="error"
            message={error}
            closable
            onClose={clearError}
            style={{ marginBottom: 16 }}
          />
        )}

        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码"
                            autoComplete="current-password" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: 'center' }}>
          <Link onClick={() => setShowSettings(true)}>
            <Space>
              <CloudServerOutlined />
              配置后端地址
            </Space>
          </Link>
        </div>
      </Card>

      <Modal
        title="后端服务地址"
        open={showSettings}
        onOk={onSaveBackend}
        onCancel={() => setShowSettings(false)}
        okText="保存"
      >
        <Input
          placeholder="http://localhost:8000/api/v1"
          value={backendUrl}
          onChange={e => setBackendUrl(e.target.value)}
        />
        <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
          配置后会写入 %APPDATA%/ai-video-studio/config.json
        </Text>
      </Modal>
    </div>
  )
}
