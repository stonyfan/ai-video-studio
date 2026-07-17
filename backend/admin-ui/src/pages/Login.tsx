import { useState } from 'react'
import { Form, Input, Button, Card, Typography, Alert, App } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'

import { useAuthStore } from '../store/auth'

const { Title, Text } = Typography

export default function Login() {
  const { message } = App.useApp()
  const login = useAuthStore((s) => s.login)
  const [submitting, setSubmitting] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    setSubmitting(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
    } catch (e) {
      const err = e as Error
      message.error(err.message || '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    }}>
      <Card style={{ width: 380, boxShadow: '0 8px 32px rgba(0,0,0,0.18)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ marginBottom: 4 }}>AI Video Studio</Title>
          <Text type="secondary">管理后台</Text>
        </div>
        <Form
          name="login"
          onFinish={onFinish}
          autoComplete="off"
          size="large"
        >
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting}>
              登录
            </Button>
          </Form.Item>
        </Form>
        <Alert
          type="info"
          showIcon
          message="需要 admin 权限"
          description="普通用户登录会被拒绝。"
          style={{ marginTop: 8 }}
        />
      </Card>
    </div>
  )
}
